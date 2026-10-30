"""The observation hub: what the live channel's instance topics show, and the broker subscriptions behind them.

An instance topic is `instance:<node id>/<instance>` (cluster/protocol/live.py):

    pool    <subsystem>-<index>, a node's scene or trajectory generation pool. While a browser
            observes it, the hub subscribes with the master's own broker account to the
            pool's preview topics under its scope, scenegems/<master>/<node>/<instance>/, and
            translates what the pool publishes into scene_sample and trajectory_preview
            updates (rate limited; a final sample or result is never dropped). The last
            observer leaving ends the subscription. One broker connection serves every pool;
            it opens with the first pool observed.
    job     job-<job id>-<attempt>. Its status comes from the job's activity and state (topics.py
            JobTopics passes them on). A running simulation's frames come from its node:
            on_job_observation tells the master's ObservedJobs (cluster/master/observed_jobs.py)
            when a job's instance gets its first observer and loses its last, so it sends the
            node Observe on and off, and the node's ObservationFrames come back through
            publish_simulation_frames. The speed of an observed run belongs to the job: a
            subscribe's options or a configure set it (the latest wins), observed_speed reads
            it, on_job_speed reports a change while observed, and every observer of the job
            gets a status update with the new observed_speed.

Broker messages arrive on the broker client's thread and are handed to the event loop.
"""

import asyncio
import json
import logging
import threading
import uuid
from dataclasses import dataclass
from functools import partial
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Set, Tuple, Union

import anyio
from pydantic import ValidationError

from scenegems_tool.cluster.master.control_plane import ControlPlane
from scenegems_tool.cluster.master.job_activity import JobProgress
from scenegems_tool.cluster.master.live.live_channel import InvalidOptions, LiveChannel, UnknownTopic
from scenegems_tool.cluster.node.instance_scope import node_topic_scope
from scenegems_tool.cluster.protocol.live import (
    DEFAULT_OBSERVED_SPEED,
    JOB_INSTANCE_KINDS,
    InstanceKind,
    InstanceName,
    InstanceSnapshot,
    InstanceStatus,
    SceneSample,
    SimulationFrames,
    Topic,
    TopicOptions,
    TrajectoryPreview,
    instance_topic,
    is_rated,
    job_instance,
    parse_instance,
)
from scenegems_tool.persistence.stores import JobRecord
from scenegems_tool.subsystems.scene_generation.scene_generation_types import SCENE_GENERATION_SERVICE_TOPIC
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_types import TRAJECTORY_GENERATION_SERVICE_TOPIC

logger = logging.getLogger(__name__)

InstanceUpdateModel = Union[SceneSample, TrajectoryPreview, SimulationFrames, InstanceStatus]

GENERATED_SCENE_TOPIC = f"{SCENE_GENERATION_SERVICE_TOPIC}/sensor/generated_scene"
TRAJECTORY_PREVIEW_TOPIC = f"{TRAJECTORY_GENERATION_SERVICE_TOPIC}/sensor/planned_trajectory_preview"
TRAJECTORY_RESULT_TOPIC = f"{TRAJECTORY_GENERATION_SERVICE_TOPIC}/sensor/planned_trajectory"
# The topics a pool publishes its previews on, relative to its scope (messaging/mqtt_*_generation_service.py)
POOL_TOPICS: Dict[InstanceKind, Tuple[str, ...]] = {
    InstanceKind.SCENE_GENERATION: (GENERATED_SCENE_TOPIC,),
    InstanceKind.TRAJECTORY_GENERATION: (TRAJECTORY_PREVIEW_TOPIC, TRAJECTORY_RESULT_TOPIC),
}
SUPERSEDED = "superseded"  # the state of a job instance whose job has moved on to a later attempt


class BrokerClient(Protocol):
    """The hub's connection to the cluster broker. on_message runs on the client's own thread."""

    def start(self, on_message: Callable[[str, bytes], None]) -> None: ...

    def subscribe(self, topic_filter: str) -> None: ...

    def unsubscribe(self, topic_filter: str) -> None: ...

    def stop(self) -> None: ...


BrokerClientFactory = Callable[[], BrokerClient]


class PahoBrokerClient:
    """paho on the cluster broker, which is plain and anonymous on the VPN; resubscribes its filters after every reconnect."""

    def __init__(self, host: str, port: int, client_id: Optional[str] = None):
        self.host = host
        self.port = port
        self._client_id = client_id or f"scenegems-master-observer-{uuid.uuid4().hex[:8]}"
        self._filters: Set[str] = set()
        self._lock = threading.Lock()
        self._client: Any = None

    def start(self, on_message: Callable[[str, bytes], None]) -> None:
        import paho.mqtt.client as mqtt

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self._client_id)
        client.on_connect = self._on_connect
        client.on_message = lambda _client, _userdata, message: on_message(message.topic, message.payload)
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client = client
        client.connect_async(self.host, self.port, keepalive=30)
        client.loop_start()

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code.is_failure:
            logger.warning("The observation hub's connection to the broker at %s:%d failed: %s", self.host, self.port, reason_code)
            return
        with self._lock:
            filters = sorted(self._filters)
        for topic_filter in filters:
            client.subscribe(topic_filter)
        logger.info("The observation hub is connected to the cluster broker at %s:%d (%d subscriptions)", self.host, self.port, len(filters))

    def subscribe(self, topic_filter: str) -> None:
        with self._lock:
            self._filters.add(topic_filter)
        if self._client is not None and self._client.is_connected():
            self._client.subscribe(topic_filter)

    def unsubscribe(self, topic_filter: str) -> None:
        with self._lock:
            self._filters.discard(topic_filter)
        if self._client is not None and self._client.is_connected():
            self._client.unsubscribe(topic_filter)

    def stop(self) -> None:
        if self._client is not None:
            self._client.disconnect()
            self._client.loop_stop()
            self._client = None


def translate_pool_message(topic: str, message: Mapping[str, Any]) -> Optional[InstanceUpdateModel]:
    """A pool's message on one of its preview topics (relative to its scope) as an instance update; None for anything else."""
    request_id = str(message.get("request-id", ""))
    try:
        if topic == GENERATED_SCENE_TOPIC:
            return SceneSample(
                request_id=request_id,
                valid=bool(message.get("valid")),
                final=bool(message.get("final", False)),
                scene=message.get("generated-frame"),
                evaluation_data=message.get("evaluation-data") or {},
            )
        if topic == TRAJECTORY_PREVIEW_TOPIC:
            return TrajectoryPreview(request_id=request_id, trajectories=message.get("trajectory-data"))
        if topic == TRAJECTORY_RESULT_TOPIC:
            return TrajectoryPreview(
                request_id=request_id,
                trajectories=message.get("trajectory-data"),
                final=True,
                valid=bool(message.get("valid")),
                complete=bool(message.get("complete", False)),
                error_message=message.get("error-message"),
            )
    except ValidationError as error:
        logger.debug("A pool message on %s does not translate: %s", topic, error)
    return None


@dataclass
class _Observed:
    topic: str  # the live topic
    node_id: str
    instance: str
    name: InstanceName
    prefix: str = ""  # a pool's scope on the broker
    filters: Tuple[str, ...] = ()


class ObservationHub:
    def __init__(self, channel: LiveChannel, plane: ControlPlane, broker: Optional[BrokerClientFactory] = None):
        self._channel = channel
        self._plane = plane
        self._broker_factory = broker
        self._broker: Optional[BrokerClient] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._observed: Dict[str, _Observed] = {}  # by live topic
        self._pools: Dict[str, _Observed] = {}  # by broker scope prefix
        self._jobs: Dict[str, Set[str]] = {}  # job id to its observed instance topics
        self._job_attempts: Dict[str, int] = {}  # the latest attempt of an observed job
        self._job_states: Dict[str, str] = {}
        self._sent_status: Dict[str, tuple] = {}
        self._job_status: Dict[str, Tuple[str, str, Optional[float]]] = {}  # job id to its latest (state, message, progress)
        self._speeds: Dict[str, float] = {}  # job id to the speed an observer chose, while the job is observed or being subscribed to
        # Called with (node id, job id, attempt, observed) when a job instance gets its first observer (True) and loses its last (False)
        self.on_job_observation: Optional[Callable[[str, str, int, bool], None]] = None
        # Called with (job id, speed) when the speed of an observed job changes
        self.on_job_speed: Optional[Callable[[str, float], None]] = None

    @property
    def broker_configured(self) -> bool:
        return self._broker_factory is not None

    # TopicSource

    async def snapshot(self, topic: Topic) -> Any:
        name = parse_instance(topic.instance)
        if name.is_job:
            return await self._job_snapshot(topic, name)
        if not self.broker_configured:
            raise UnknownTopic("this master observes no pools: its broker account is not configured (SCENEGEMS_BROKER_HOST, SCENEGEMS_BROKER_MASTER_PASSWORD)")
        node = await self._plane.registry.node(topic.node_id)
        if node is None:
            raise UnknownTopic(f"no node {topic.node_id}")
        return InstanceSnapshot(node_id=topic.node_id, instance=topic.instance, kind=name.kind, state=node.status.value).model_dump(mode="json")

    async def _job_snapshot(self, topic: Topic, name: InstanceName) -> Any:
        job = await anyio.to_thread.run_sync(self._plane.jobs.get, name.job_id)
        if job is None:
            raise UnknownTopic(f"no job {name.job_id}")
        if job.attempt < name.attempt:
            raise UnknownTopic(f"job {name.job_id} has not started attempt {name.attempt} (it is at attempt {job.attempt})")
        if name.job_id in self._jobs:
            self._job_attempts[name.job_id] = job.attempt
            self._job_states[name.job_id] = job.state.value
        state = job.state.value if job.attempt == name.attempt else SUPERSEDED
        snapshot = InstanceSnapshot(
            node_id=topic.node_id,
            instance=topic.instance,
            kind=JOB_INSTANCE_KINDS[job.job_type],
            state=state,
            job_id=name.job_id,
            attempt=name.attempt,
            observed_speed=self.observed_speed(name.job_id),
        )
        return snapshot.model_dump(mode="json")

    def configure(self, topic: Topic, options: TopicOptions) -> None:
        """A subscribe's options or a configure message: the job's speed, which the latest request sets for every observer."""
        name = parse_instance(topic.instance)
        if not name.is_job:
            raise InvalidOptions("only job instance topics take options")
        if options.speed is None:
            return
        changed = options.speed != self.observed_speed(name.job_id)
        self._speeds[name.job_id] = options.speed
        if not changed or name.job_id not in self._jobs:
            return  # not observed yet: the activation sends the speed to the node
        if self.on_job_speed is not None:
            try:
                self.on_job_speed(name.job_id, options.speed)
            except Exception:
                logger.exception("Telling the node of job %s its new speed failed", name.job_id)
        state, message, progress = self._job_status.get(name.job_id, (self._job_states.get(name.job_id, "running"), "", None))
        self._publish_status(name.job_id, state, message, progress)

    def observed_speed(self, job_id: str) -> float:
        """The pace of the job's observed run, as a multiple of real time."""
        return self._speeds.get(job_id, DEFAULT_OBSERVED_SPEED)

    def activate(self, topic: Topic) -> None:
        name = parse_instance(topic.instance)
        observed = _Observed(topic.name, topic.node_id, topic.instance, name)
        self._observed[topic.name] = observed
        if name.is_job:
            self._jobs.setdefault(name.job_id, set()).add(topic.name)
            self._tell_node(observed, True)
            return
        if not self.broker_configured:
            return
        observed.prefix = f"{node_topic_scope(self._plane.master_id, topic.node_id)}{topic.instance}/"
        observed.filters = tuple(observed.prefix + suffix for suffix in POOL_TOPICS[name.kind])
        self._pools[observed.prefix] = observed
        broker = self._ensure_broker()
        for topic_filter in observed.filters:
            broker.subscribe(topic_filter)

    def deactivate(self, topic: Topic) -> None:
        observed = self._observed.pop(topic.name, None)
        if observed is None:
            return
        self._sent_status.pop(topic.name, None)
        if observed.name.is_job:
            job_id = observed.name.job_id
            topics = self._jobs.get(job_id, set())
            topics.discard(topic.name)
            if not topics:
                self._jobs.pop(job_id, None)
                self._job_attempts.pop(job_id, None)
                self._job_states.pop(job_id, None)
                self._job_status.pop(job_id, None)
                self._speeds.pop(job_id, None)
            self._tell_node(observed, False)
            return
        self._pools.pop(observed.prefix, None)
        if self._broker is not None:
            for topic_filter in observed.filters:
                self._broker.unsubscribe(topic_filter)

    # Publishing

    def publish_instance_update(self, node_id: str, instance: str, update: InstanceUpdateModel) -> None:
        """Sends an update to the observers of one instance; nothing when it has none. Call it on the event loop.

        Previews and frames are rate limited and coalesced; a status or a final sample or result is not.
        """
        topic = instance_topic(node_id, instance)
        if not self._channel.has_subscribers(topic):
            return
        data = update.model_dump(mode="json")
        if is_rated(update):
            limit = self._channel.frames_rate if update.kind == "simulation_frames" else self._channel.preview_rate
            self._channel.publish_rated(topic, update.kind, data, limit)
        else:
            self._channel.publish(topic, data)

    def publish_simulation_frames(self, node_id: str, job_id: str, attempt: int, frames: List[Dict[str, Any]]) -> None:
        """P5.10's entry point: frames of an observed run (gateway.serialization.serialize_monitored_frame), from the job's node.

        They go to every observed instance topic of the job's attempt, whatever node the topic
        names, as its status does (_publish_status): a browser may name another node than the
        lease holder, for example one that held an earlier lease. The holder's own topic gets
        them too, as before.
        """
        if not frames:
            return
        update = SimulationFrames(job_id=job_id, frames=frames)
        targets = {(node_id, job_instance(job_id, attempt))}
        for topic in self._jobs.get(job_id, ()):
            observed = self._observed.get(topic)
            if observed is not None and observed.name.attempt == attempt:
                targets.add((observed.node_id, observed.instance))
        for target_node, instance in sorted(targets):
            self.publish_instance_update(target_node, instance, update)

    def observes_job(self, job_id: str) -> bool:
        return job_id in self._jobs

    def job_progress(self, job_id: str, progress: JobProgress) -> None:
        """A job's progress report (JobActivity, through JobTopics): a status for its observed instance."""
        if job_id not in self._jobs:
            return
        self._publish_status(job_id, self._job_states.get(job_id, "running"), progress.message, progress.progress)

    def job_state(self, job: JobRecord) -> None:
        """A job's state as last read (JobTopics): a status for its observed instances when it changed."""
        if job.job_id not in self._jobs:
            return
        self._job_attempts[job.job_id] = job.attempt
        self._job_states[job.job_id] = job.state.value
        self._publish_status(job.job_id, job.state.value, job.error or "", None)

    def _publish_status(self, job_id: str, state: str, message: str, progress: Optional[float]) -> None:
        self._job_status[job_id] = (state, message, progress)
        current = self._job_attempts.get(job_id)
        speed = self.observed_speed(job_id)
        for topic in sorted(self._jobs.get(job_id, ())):
            observed = self._observed.get(topic)
            if observed is None:
                continue
            instance_state = state if current is None or observed.name.attempt == current else SUPERSEDED
            status = (instance_state, message, progress, speed)
            if self._sent_status.get(topic) == status:
                continue
            self._sent_status[topic] = status
            update = InstanceStatus(state=instance_state, message=message, progress=progress, observed_speed=speed)
            self.publish_instance_update(observed.node_id, observed.instance, update)

    # The broker

    def _ensure_broker(self) -> BrokerClient:
        if self._broker is None:
            self._loop = asyncio.get_running_loop()
            self._broker = self._broker_factory()
            self._broker.start(self._on_broker_message)
        return self._broker

    def _on_broker_message(self, topic: str, payload: bytes) -> None:
        """On the broker client's thread: hand the message to the event loop."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self.deliver, topic, payload)
        except RuntimeError:
            pass  # the loop closed meanwhile

    def deliver(self, topic: str, payload: bytes) -> None:
        """A message from the broker, on the event loop: translated and published when its pool is observed."""
        levels = topic.split("/")
        prefix = "/".join(levels[:4]) + "/"
        observed = self._pools.get(prefix)
        if observed is None:
            return
        try:
            message = json.loads(payload)
        except (TypeError, ValueError):
            return
        if not isinstance(message, dict):
            return
        update = translate_pool_message(topic[len(prefix) :], message)
        if update is not None:
            self.publish_instance_update(observed.node_id, observed.instance, update)

    def _tell_node(self, observed: _Observed, on: bool) -> None:
        if self.on_job_observation is None:
            return
        try:
            self.on_job_observation(observed.node_id, observed.name.job_id, observed.name.attempt, on)
        except Exception:
            logger.exception("Telling node %s to %s observing job %s failed", observed.node_id, "start" if on else "stop", observed.name.job_id)

    async def close(self) -> None:
        broker, self._broker = self._broker, None
        if broker is not None:
            await anyio.to_thread.run_sync(broker.stop)


def paho_broker(host: str, port: int) -> BrokerClientFactory:
    """The factory of the hub's real broker client."""
    return partial(PahoBrokerClient, host, port)
