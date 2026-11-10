"""The producers of the live channel's topics, and the wiring of the channel into a control node.

    worker nodes             WorkerNodesTopic: WorkerNodeRegistry.on_change, then the worker node's view when it differs
                      from the last one sent (a heartbeat that changes nothing but the time sends nothing)
    job:<id>          JobTopics: JobActivity's listener (status, log lines, state changes reported
                      by the lease manager, the scheduler and the control plane)
    campaigns         CampaignListTopic: the list rows. PipelineEngine.on_change (through CampaignTopics) and the
                      campaign routes (create, control, delete) tell it which campaigns changed; it publishes
                      the row of each that differs from the last one sent, and the id of a deleted one
    campaign:<id>     CampaignTopics: PipelineEngine.on_change after each committed tick, then the
                      new events, the summary when it changed and the FECs that changed
    instance:...      ObservationHub (observation_hub.py)

Every hook first checks LiveChannel.has_subscribers and returns when nobody listens. What a
hook needs from the database is read by a CoalescingWorker: one task per producer, which reads
in worker threads in the order the keys were marked and merges marks that arrive meanwhile, so
the event loop never waits on Postgres and a burst of changes costs one read per key.
"""

import asyncio
import logging
from functools import partial
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Set

import anyio
from sqlalchemy import func, select

from scenegems_tool.cluster.control_node.api.campaign_views import campaign_detail_view, campaign_row_view, campaign_view, classes_view, event_view
from scenegems_tool.cluster.control_node.api.views import job_view, worker_node_view
from scenegems_tool.cluster.control_node.control_plane import ControlPlane
from scenegems_tool.cluster.control_node.job_activity import JobProgress
from scenegems_tool.cluster.control_node.live.live_channel import LiveChannel, LiveSettings, UnknownTopic
from scenegems_tool.cluster.control_node.live.observation_hub import BrokerClientFactory, ObservationHub
from scenegems_tool.cluster.protocol.live import (
    CAMPAIGNS_TOPIC,
    WORKER_NODES_TOPIC,
    CampaignChanged,
    CampaignDeleted,
    CampaignEventAdded,
    CampaignFecsChanged,
    CampaignRowChanged,
    JobChanged,
    JobLogsAdded,
    JobProgressView,
    JobStatusChanged,
    Topic,
    TopicKind,
    WorkerNodeChanged,
    WorkerNodeRemoved,
    campaign_topic,
    job_topic,
)
from scenegems_tool.cluster.protocol.messages import LogLine
from scenegems_tool.persistence.schema import CampaignEventRow
from scenegems_tool.persistence.stores import AssuranceStores

logger = logging.getLogger(__name__)

# Fields of a view that change without anything an observer cares about
_WORKER_NODE_NOISE = ("last_seen_at",)
_JOB_NOISE = ("progress", "lease_expires_at")


def _without(view: Dict[str, Any], keys: Iterable[str]) -> Dict[str, Any]:
    return {key: value for key, value in view.items() if key not in keys}


async def _run(function: Callable[..., Any], *arguments: Any) -> Any:
    return await anyio.to_thread.run_sync(partial(function, *arguments))


class CoalescingWorker:
    """Runs handle(keys) for marked keys, one call at a time; marks during a call are handled by the next."""

    def __init__(self, handle: Callable[[List[str]], Awaitable[None]], name: str):
        self._handle = handle
        self._name = name
        self._keys: Dict[str, None] = {}  # insertion ordered
        self._task: Optional[asyncio.Task] = None

    def mark(self, key: str) -> None:
        self._keys[key] = None
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run())

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    async def idle(self) -> None:
        """Waits until every marked key was handled (for tests)."""
        while self.busy:
            await asyncio.shield(self._task)

    async def _run(self) -> None:
        while self._keys:
            keys = list(self._keys)
            self._keys.clear()
            try:
                await self._handle(keys)
            except Exception:
                logger.exception("The live %s producer failed for %s", self._name, ", ".join(keys))

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)


class WorkerNodesTopic:
    """`worker_nodes`: every worker node's view, then a worker node's view whenever it changes."""

    def __init__(self, channel: LiveChannel, plane: ControlPlane):
        self._channel = channel
        self._plane = plane
        self._sent: Dict[str, Dict[str, Any]] = {}
        self.worker = CoalescingWorker(self._refresh, "worker_nodes")

    async def snapshot(self, topic: Topic) -> Any:
        records = await self._plane.registry.worker_nodes()
        return [worker_node_view(record, self._plane.registry.session(record.worker_node_id)) for record in records]

    def activate(self, topic: Topic) -> None:
        self._sent.clear()

    def deactivate(self, topic: Topic) -> None:
        self._sent.clear()

    def worker_node_changed(self, worker_node_id: str) -> None:
        if self._channel.has_subscribers(WORKER_NODES_TOPIC):
            self.worker.mark(worker_node_id)

    async def _refresh(self, worker_node_ids: List[str]) -> None:
        registry = self._plane.registry
        for worker_node_id in worker_node_ids:
            session = registry.session(worker_node_id)
            record = session.record if session is not None and not session.closed else await registry.worker_node(worker_node_id)
            if not self._channel.has_subscribers(WORKER_NODES_TOPIC):
                continue
            if record is None:
                self._sent.pop(worker_node_id, None)
                self._channel.publish(WORKER_NODES_TOPIC, WorkerNodeRemoved(removed=worker_node_id).model_dump())
                continue
            view = worker_node_view(record, registry.session(worker_node_id))
            key = _without(view, _WORKER_NODE_NOISE)
            if self._sent.get(worker_node_id) == key:
                continue
            self._sent[worker_node_id] = key
            self._channel.publish(WORKER_NODES_TOPIC, WorkerNodeChanged(worker_node=view).model_dump())


class JobTopics:
    """`job:<id>`: the job with its progress and recent log lines, then status, log lines and state changes.

    It is JobActivity's listener and passes status and state on to the observation hub, whose
    job instances show them too.
    """

    def __init__(self, channel: LiveChannel, plane: ControlPlane, hub: Optional[ObservationHub] = None):
        self._channel = channel
        self._plane = plane
        self._hub = hub
        self._sent: Dict[str, Dict[str, Any]] = {}
        self.worker = CoalescingWorker(self._refresh, "job")

    async def snapshot(self, topic: Topic) -> Any:
        job_id = topic.key
        # In memory first, before any await: updates queued after the subscription are newer than these
        progress = self._plane.activity.progress(job_id)
        lines = self._plane.activity.lines(job_id)
        job = await _run(self._plane.jobs.get, job_id)
        if job is None:
            raise UnknownTopic(f"no job {job_id}")
        return {**job_view(job, progress), "logs": [line.model_dump(mode="json") for line in lines]}

    def activate(self, topic: Topic) -> None:
        self._sent.pop(topic.key, None)

    def deactivate(self, topic: Topic) -> None:
        self._sent.pop(topic.key, None)

    # ActivityListener

    def job_status(self, job_id: str, progress: JobProgress) -> None:
        topic = job_topic(job_id)
        if self._channel.has_subscribers(topic):
            self._channel.publish(topic, JobStatusChanged(status=JobProgressView(progress=progress.progress, message=progress.message, at=progress.at)).model_dump())
        if self._hub is not None:
            self._hub.job_progress(job_id, progress)

    def job_logs(self, job_id: str, lines: List[LogLine]) -> None:
        topic = job_topic(job_id)
        if lines and self._channel.has_subscribers(topic):
            self._channel.publish(topic, JobLogsAdded(logs=[line.model_dump(mode="json") for line in lines]).model_dump())

    def job_changed(self, job_id: str) -> None:
        if self._channel.has_subscribers(job_topic(job_id)) or (self._hub is not None and self._hub.observes_job(job_id)):
            self.worker.mark(job_id)

    async def _refresh(self, job_ids: List[str]) -> None:
        for job_id in job_ids:
            job = await _run(self._plane.jobs.get, job_id)
            if job is None:
                continue
            if self._hub is not None:
                self._hub.job_state(job)
            topic = job_topic(job_id)
            if not self._channel.has_subscribers(topic):
                continue
            view = job_view(job, self._plane.activity.progress(job_id))
            key = _without(view, _JOB_NOISE)
            if self._sent.get(job_id) == key:
                continue
            self._sent[job_id] = key
            self._channel.publish(topic, JobChanged(job=view).model_dump())


class CampaignListTopic:
    """`campaigns`: nothing in the snapshot (the list is read with GET /cluster/campaigns), then a list row whenever a campaign is
    created or changes, and the id of a deleted one.

    Like the other topics it reads in a worker thread, after the engine's commit or the route's, and sends a row only when it differs
    from the last one sent, so an engine tick that changed nothing of a row sends nothing.
    """

    def __init__(self, channel: LiveChannel, stores: AssuranceStores):
        self._channel = channel
        self._stores = stores
        self._sent: Dict[str, Dict[str, Any]] = {}
        self._deleted: Set[str] = set()  # campaign ids are never reused, so a row read before a delete is dropped by id
        self.worker = CoalescingWorker(self._refresh, "campaigns")

    async def snapshot(self, topic: Topic) -> Any:
        return {}

    def activate(self, topic: Topic) -> None:
        self._sent.clear()
        self._deleted.clear()

    def deactivate(self, topic: Topic) -> None:
        self._sent.clear()
        self._deleted.clear()

    def campaigns_changed(self, campaign_ids: Set[str]) -> None:
        """A campaign was created or changed (the engine after a commit, a route)."""
        if self._channel.has_subscribers(CAMPAIGNS_TOPIC):
            for campaign_id in sorted(campaign_ids):
                self.worker.mark(campaign_id)

    def campaign_deleted(self, campaign_id: str) -> None:
        if self._channel.has_subscribers(CAMPAIGNS_TOPIC):
            self._sent.pop(campaign_id, None)
            self._deleted.add(campaign_id)
            self._channel.publish(CAMPAIGNS_TOPIC, CampaignDeleted(deleted=campaign_id).model_dump())

    async def _refresh(self, campaign_ids: List[str]) -> None:
        rows = await _run(self._read_rows, campaign_ids)
        if not self._channel.has_subscribers(CAMPAIGNS_TOPIC):
            return
        for row in rows:
            campaign_id = row["campaign_id"]
            if campaign_id in self._deleted or self._sent.get(campaign_id) == row:
                continue
            self._sent[campaign_id] = row
            self._channel.publish(CAMPAIGNS_TOPIC, CampaignRowChanged(campaign=row).model_dump())

    def _read_rows(self, campaign_ids: List[str]) -> List[Dict[str, Any]]:
        stores = self._stores
        with stores.transaction() as session:
            campaigns = [campaign for campaign in (stores.campaigns.get_campaign(campaign_id, session=session) for campaign_id in campaign_ids) if campaign is not None]
            ids = [campaign.campaign_id for campaign in campaigns]
            configs = stores.campaigns.current_configs(ids, session=session)
            totals = stores.campaigns.campaign_totals(ids, session=session)
        return [campaign_row_view(campaign, configs[campaign.campaign_id].config if campaign.campaign_id in configs else None, totals[campaign.campaign_id]) for campaign in campaigns]


class _Watch:
    """What the subscribers of one campaign have been sent: up to which event, the summary, each class."""

    def __init__(self) -> None:
        self.primer_taken = False  # the activating subscriber's snapshot primes it, not a later one that may finish first
        self.primed = False
        self.last_event_id = 0
        self.summary: Optional[Dict[str, Any]] = None
        self.classes: Dict[str, Dict[str, Any]] = {}


class CampaignTopics:
    """`campaign:<id>`: the campaign detail, then new events, summary changes and changed classes.

    The first subscriber's snapshot primes what was sent; the engine's notifications then make the
    worker read, in a worker thread, the events after the last one sent, the campaign and its
    classes, and publish what differs. A later subscriber's snapshot may be newer than what was
    sent, so its event updates may repeat events up to its snapshot's last_event_id.
    """

    def __init__(self, channel: LiveChannel, stores: AssuranceStores, listing: Optional[CampaignListTopic] = None):
        self._channel = channel
        self._stores = stores
        self._listing = listing  # told of the same changes, for the campaigns topic
        self._watches: Dict[str, _Watch] = {}
        self.worker = CoalescingWorker(self._refresh, "campaign")

    async def snapshot(self, topic: Topic) -> Any:
        campaign_id = topic.key
        watch = self._watches.get(campaign_id)
        primes = watch is not None and not watch.primer_taken
        if primes:
            watch.primer_taken = True
        campaign, classes, last_event_id, config = await _run(self._read_snapshot, campaign_id)
        if campaign is None:
            raise UnknownTopic(f"no campaign {campaign_id}")
        if primes and self._watches.get(campaign_id) is watch:
            watch.primed = True
            watch.last_event_id = last_event_id
            watch.summary = campaign_view(campaign)
            watch.classes = {entry["fec_id"]: entry for entry in classes}
            self.worker.mark(campaign_id)  # what changed between this read and the priming
        return {**campaign_detail_view(campaign, classes, config), "last_event_id": last_event_id}

    def _read_snapshot(self, campaign_id: str) -> tuple:
        stores = self._stores
        with stores.transaction() as session:
            campaign = stores.campaigns.get_campaign(campaign_id, session=session)
            if campaign is None:
                return None, [], 0, None
            config = stores.campaigns.current_configs([campaign_id], session=session)[campaign_id].config
            last_event_id = session.execute(select(func.max(CampaignEventRow.id)).where(CampaignEventRow.campaign_id == campaign_id)).scalar() or 0
            classes = classes_view(stores.cases.list_classes(campaign_id, session=session), stores.results.coverage(campaign_id, session=session))
            return campaign, classes, last_event_id, config

    def activate(self, topic: Topic) -> None:
        self._watches[topic.key] = _Watch()

    def deactivate(self, topic: Topic) -> None:
        self._watches.pop(topic.key, None)

    def campaigns_changed(self, campaign_ids: Set[str]) -> None:
        """The pipeline engine's notification after a committed transaction."""
        if self._listing is not None:
            self._listing.campaigns_changed(campaign_ids)
        for campaign_id in sorted(campaign_ids):
            if self._channel.has_subscribers(campaign_topic(campaign_id)):
                self.worker.mark(campaign_id)

    async def _refresh(self, campaign_ids: List[str]) -> None:
        for campaign_id in campaign_ids:
            watch = self._watches.get(campaign_id)
            if watch is None or not watch.primed:
                continue  # the snapshot that primes it marks the campaign again
            campaign, events, classes = await _run(self._read_changes, campaign_id, watch.last_event_id)
            if self._watches.get(campaign_id) is not watch or campaign is None:
                continue
            topic = campaign_topic(campaign_id)
            for event in events:
                self._channel.publish(topic, CampaignEventAdded(event=event_view(event)).model_dump())
                watch.last_event_id = event.event_id
            summary = campaign_view(campaign)
            if summary != watch.summary:
                watch.summary = summary
                self._channel.publish(topic, CampaignChanged(campaign=summary).model_dump())
            changed = [entry for entry in classes if watch.classes.get(entry["fec_id"]) != entry]
            if changed:
                watch.classes.update({entry["fec_id"]: entry for entry in changed})
                self._channel.publish(topic, CampaignFecsChanged(fecs=changed).model_dump())

    def _read_changes(self, campaign_id: str, after_event_id: int) -> tuple:
        stores = self._stores
        with stores.transaction() as session:
            campaign = stores.campaigns.get_campaign(campaign_id, session=session)
            if campaign is None:
                return None, [], []
            events = stores.campaigns.list_events(campaign_id, after_event_id, None, session=session)
            classes = classes_view(stores.cases.list_classes(campaign_id, session=session), stores.results.coverage(campaign_id, session=session))
            return campaign, events, classes


class LiveProducers:
    """The channel's producers of one control node, kept for shutdown and for tests."""

    def __init__(self, worker_nodes: WorkerNodesTopic, jobs: JobTopics, campaigns: Optional[CampaignTopics], hub: ObservationHub, campaign_list: Optional[CampaignListTopic] = None):
        self.worker_nodes = worker_nodes
        self.jobs = jobs
        self.campaigns = campaigns
        self.hub = hub
        self.campaign_list = campaign_list  # the campaigns topic; the campaign routes tell it of creates, controls and deletes

    async def idle(self) -> None:
        """Waits until every producer handled what it was told (for tests)."""
        for worker in self._workers():
            await worker.idle()

    async def close(self) -> None:
        for worker in self._workers():
            await worker.close()
        await self.hub.close()

    def _workers(self) -> List[CoalescingWorker]:
        workers = [self.worker_nodes.worker, self.jobs.worker]
        if self.campaigns is not None:
            workers.append(self.campaigns.worker)
        if self.campaign_list is not None:
            workers.append(self.campaign_list.worker)
        return workers


def create_live_channel(
    plane: ControlPlane,
    assurance: Optional[AssuranceStores] = None,
    broker: Optional[BrokerClientFactory] = None,
    settings: LiveSettings = LiveSettings(),
) -> LiveChannel:
    """A live channel on the control node's control plane: hooks into the registry, the job activity and the pipeline engine.

    Without assurance stores the campaign topics (campaigns and campaign:<id>) are not served; without a broker the observation
    hub serves job instances only. The producers are at channel.producers.
    """
    channel = LiveChannel(settings)
    hub = ObservationHub(channel, plane, broker)
    worker_nodes = WorkerNodesTopic(channel, plane)
    jobs = JobTopics(channel, plane, hub)
    campaign_list = CampaignListTopic(channel, assurance) if assurance is not None else None
    campaigns = CampaignTopics(channel, assurance, campaign_list) if assurance is not None else None
    channel.add_source(TopicKind.WORKER_NODES, worker_nodes)
    channel.add_source(TopicKind.JOB, jobs)
    channel.add_source(TopicKind.INSTANCE, hub)
    plane.registry.on_change = worker_nodes.worker_node_changed
    plane.activity.listener = jobs
    # Live simulations: the hub's observers drive the worker nodes' Observe frames, the worker nodes' frames come back to the hub
    hub.on_job_observation = plane.observations.observe
    hub.on_job_speed = plane.observations.speed_changed
    plane.observations.speed_of = hub.observed_speed
    plane.observations.frames_sink = hub.publish_simulation_frames
    if campaigns is not None:
        channel.add_source(TopicKind.CAMPAIGN, campaigns)
        channel.add_source(TopicKind.CAMPAIGNS, campaign_list)
        if plane.pipeline is not None:
            plane.pipeline.on_change = campaigns.campaigns_changed
    channel.producers = LiveProducers(worker_nodes, jobs, campaigns, hub, campaign_list)
    return channel
