"""The live channel between the control node and a browser: messages and topics, version 1.

A WebSocket at LIVE_PATH on the control node's operator listener (cluster/control_node/live/), with JSON
text frames that each carry "version": 1. The browser client (frontend/src/domain/cluster/)
mirrors these models; design doc 5.3 ("Live channel contract") describes them in prose.

    client to server   subscribe {topic, options?}, configure {topic, options}, unsubscribe {topic}, ping
    server to client   subscribed {topic, snapshot}, update {topic, seq, data}, unsubscribed {topic},
                       error {message, topic?}, pong

Topics and what they carry:

    worker nodes                          snapshot: worker node views (as GET /cluster/worker-nodes)
                                   data: WorkerNodeChanged | WorkerNodeRemoved
    campaigns                      snapshot: {} (the list is read with GET /cluster/campaigns); data: CampaignRowChanged on a
                                   create and on every change of a campaign (state, totals), CampaignDeleted when one is deleted
    campaign:<campaign id>         snapshot: the campaign detail view (as GET /cluster/campaigns/<id>) with
                                   last_event_id; event updates may repeat events up to that id
                                   data: CampaignEventAdded | CampaignChanged | CampaignFecsChanged
    job:<job id>                   snapshot: the job view (as GET /cluster/jobs lists it, with progress) and
                                   logs, its recent log lines
                                   data: JobStatusChanged | JobLogsAdded | JobChanged
    instance:<worker node id>/<instance>  snapshot: InstanceSnapshot
                                   data: SceneSample | TrajectoryPreview | SimulationFrames | InstanceStatus

Options of a job instance topic (live simulations): subscribe may carry {"speed": <multiple of real
time>} and configure changes it while subscribed. The speed belongs to the job, not to one browser:
the latest request wins for every observer. A job instance's snapshot and its status updates carry
the current one as observed_speed (DEFAULT_OBSERVED_SPEED until somebody chooses), and a change
sends every observer of the job a status update.

seq counts a connection's updates of one subscription from 1; a new subscribe starts again
at 1 after its snapshot. Nothing is sent for a topic the connection did not subscribe to.
Previews and frames are rate limited per topic and may be coalesced (a newer preview
replaces an unsent one; unsent frames are joined); every other update is delivered, and a
connection too slow to take them is closed, so its client resubscribes and gets snapshots.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.messages import DEFAULT_OBSERVED_SPEED, MAX_OBSERVED_SPEED  # noqa: F401 (the default is part of this contract)
from scenegems_tool.cluster.protocol.routes import LIVE_PATH  # noqa: F401 (the channel's path, named here too)

LIVE_VERSION = 1

WORKER_NODES_TOPIC = "worker_nodes"
CAMPAIGNS_TOPIC = "campaigns"
CAMPAIGN_PREFIX = "campaign:"
JOB_PREFIX = "job:"
INSTANCE_PREFIX = "instance:"
JOB_INSTANCE_PREFIX = "job-"  # a job's instance id: job-<job id>-<attempt> (cluster/worker_node/worker_node_context.py)

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")  # campaign and job ids
_SCOPE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")  # worker node and instance ids (cluster/worker_node/instance_scope.py)


class LiveModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LiveMessage(LiveModel):
    version: Literal[1] = LIVE_VERSION


# Client to server


class TopicOptions(LiveModel):
    """Options of a job instance topic: speed, the observed run's pace as a multiple of real time."""

    speed: Optional[float] = Field(default=None, gt=0.0, le=MAX_OBSERVED_SPEED)


class Subscribe(LiveMessage):
    type: Literal["subscribe"] = "subscribe"
    topic: str
    options: Optional[TopicOptions] = None  # job instance topics only


class Configure(LiveMessage):
    """Changes the options of a subscribed job instance topic; the latest request wins for every observer of the job."""

    type: Literal["configure"] = "configure"
    topic: str
    options: TopicOptions


class Unsubscribe(LiveMessage):
    type: Literal["unsubscribe"] = "unsubscribe"
    topic: str


class Ping(LiveMessage):
    type: Literal["ping"] = "ping"


ClientMessage = Annotated[Union[Subscribe, Configure, Unsubscribe, Ping], Field(discriminator="type")]


# Server to client


class Subscribed(LiveMessage):
    type: Literal["subscribed"] = "subscribed"
    topic: str
    snapshot: Any


class Update(LiveMessage):
    type: Literal["update"] = "update"
    topic: str
    seq: int = Field(ge=1)
    data: Dict[str, Any]


class Unsubscribed(LiveMessage):
    type: Literal["unsubscribed"] = "unsubscribed"
    topic: str


class Error(LiveMessage):
    type: Literal["error"] = "error"
    message: str
    topic: Optional[str] = None


class Pong(LiveMessage):
    type: Literal["pong"] = "pong"


ServerMessage = Annotated[Union[Subscribed, Update, Unsubscribed, Error, Pong], Field(discriminator="type")]


# Update data: the `data` of an update, per topic


class WorkerNodeChanged(LiveModel):
    worker_node: Dict[str, Any]  # the worker node view, as GET /cluster/worker-nodes/<id>


class WorkerNodeRemoved(LiveModel):
    removed: str  # worker node id


class CampaignRowChanged(LiveModel):
    campaign: Dict[str, Any]  # the list row, as GET /cluster/campaigns lists it (summary, steps, input, made_from, totals)


class CampaignDeleted(LiveModel):
    deleted: str  # campaign id


class CampaignEventAdded(LiveModel):
    event: Dict[str, Any]  # an event view, as GET /cluster/campaigns/<id>/events


class CampaignChanged(LiveModel):
    campaign: Dict[str, Any]  # the summary view (states, times), as GET /cluster/campaigns lists it


class CampaignFecsChanged(LiveModel):
    fecs: List[Dict[str, Any]]  # the FEC views that changed, as GET /cluster/campaigns/<id>/fecs


class JobProgressView(LiveModel):
    progress: Optional[float] = None  # 0 to 1, when the job reports it
    message: str = ""
    at: datetime


class JobStatusChanged(LiveModel):
    status: JobProgressView


class JobLogsAdded(LiveModel):
    logs: List[Dict[str, Any]]  # log lines: timestamp, stream, source, text (cluster/protocol/messages.py LogLine)


class JobChanged(LiveModel):
    job: Dict[str, Any]  # the job view, as GET /cluster/jobs lists it, on a state change


class InstanceKind(str, Enum):
    DESIGN_SPACE_EXPLORATION = "design_space_exploration"
    SCENE_GENERATION = "scene_generation"
    TRAJECTORY_GENERATION = "trajectory_generation"
    SIMULATION = "simulation"
    MONITORING = "monitoring"


JOB_INSTANCE_KINDS: Dict[JobType, InstanceKind] = {
    JobType.DESIGN_SPACE_EXPLORATION: InstanceKind.DESIGN_SPACE_EXPLORATION,
    JobType.SCENE_GENERATION: InstanceKind.SCENE_GENERATION,
    JobType.TRAJECTORY_GENERATION: InstanceKind.TRAJECTORY_GENERATION,
    JobType.SIMULATION: InstanceKind.SIMULATION,
    JobType.CALIBRATION_DEVIATION: InstanceKind.SIMULATION,
    JobType.MONITORING_POST_HOC: InstanceKind.MONITORING,
}
POOL_INSTANCE_KINDS = (InstanceKind.SCENE_GENERATION, InstanceKind.TRAJECTORY_GENERATION)  # pooled subsystems: <subsystem>-<index>


class InstanceSnapshot(LiveModel):
    """The snapshot of instance:<worker node>/<instance>.

    state: the job's state for a job instance; the worker node's status (online, draining, offline) for a pool.
    """

    worker_node_id: str
    instance: str
    kind: InstanceKind
    state: str
    job_id: Optional[str] = None  # set for a job instance
    attempt: Optional[int] = None
    observed_speed: Optional[float] = None  # a job instance: the pace an observed run follows (simulations), a multiple of real time


class SceneSample(LiveModel):
    """A scene generation pool's sample: search progress, or the request's final scene."""

    kind: Literal["scene_sample"] = "scene_sample"
    request_id: str
    valid: bool
    final: bool = False  # the worker's last scene for the request; earlier ones are search progress
    scene: Optional[Dict[str, Any]] = None  # the scene as one frame of the workbench's wire format (gateway.serialization.serialize_frame)
    evaluation_data: Dict[str, Any] = Field(default_factory=dict)


class TrajectoryPreview(LiveModel):
    """A trajectory generation pool's search preview, or (final) the request's result."""

    kind: Literal["trajectory_preview"] = "trajectory_preview"
    request_id: str
    trajectories: Optional[Dict[str, Any]] = None  # trajectory data as the workbench's trajectoryData
    final: bool = False
    valid: Optional[bool] = None  # final only
    complete: Optional[bool] = None  # final only: false for the best partial path of a search
    error_message: Optional[str] = None


class SimulationFrames(LiveModel):
    """Frames of an observed simulation (produced by P5.10), in the workbench's frame wire format (gateway.serialization.serialize_monitored_frame)."""

    kind: Literal["simulation_frames"] = "simulation_frames"
    job_id: str
    frames: List[Dict[str, Any]]


class InstanceStatus(LiveModel):
    """A job instance's state (the job's), its latest progress message and the speed an observed run follows."""

    kind: Literal["status"] = "status"
    state: str
    message: str = ""
    progress: Optional[float] = None
    observed_speed: Optional[float] = None  # set for a job instance; a change of speed sends a status of its own


# Updates that may be rate limited and coalesced: previews and frames. A final sample or result is not a preview.
RATED_INSTANCE_KINDS = ("scene_sample", "trajectory_preview", "simulation_frames")


def is_rated(update: Union[SceneSample, TrajectoryPreview, SimulationFrames, InstanceStatus]) -> bool:
    return update.kind in RATED_INSTANCE_KINDS and not getattr(update, "final", False)


# Topics


class TopicKind(str, Enum):
    WORKER_NODES = "worker_nodes"
    CAMPAIGNS = "campaigns"
    CAMPAIGN = "campaign"
    JOB = "job"
    INSTANCE = "instance"


class InvalidTopic(ValueError):
    pass


@dataclass(frozen=True)
class Topic:
    """A parsed topic name."""

    kind: TopicKind
    key: str = ""  # the campaign or job id; for an instance, <worker node id>/<instance>
    worker_node_id: str = ""
    instance: str = ""

    @property
    def name(self) -> str:
        if self.kind == TopicKind.WORKER_NODES:
            return WORKER_NODES_TOPIC
        if self.kind == TopicKind.CAMPAIGNS:
            return CAMPAIGNS_TOPIC
        return f"{self.kind.value}:{self.key}"


@dataclass(frozen=True)
class InstanceName:
    """What an instance id says: a pool of a subsystem, or one attempt of a job."""

    kind: Optional[InstanceKind]  # None for a job instance until the job's type is known
    job_id: Optional[str] = None
    attempt: Optional[int] = None

    @property
    def is_job(self) -> bool:
        return self.job_id is not None


def campaigns_topic() -> str:
    return CAMPAIGNS_TOPIC


def campaign_topic(campaign_id: str) -> str:
    return f"{CAMPAIGN_PREFIX}{campaign_id}"


def job_topic(job_id: str) -> str:
    return f"{JOB_PREFIX}{job_id}"


def instance_topic(worker_node_id: str, instance: str) -> str:
    return f"{INSTANCE_PREFIX}{worker_node_id}/{instance}"


def job_instance(job_id: str, attempt: int) -> str:
    """The instance id of a job's attempt, as the worker node names its scope."""
    return f"{JOB_INSTANCE_PREFIX}{job_id.lower()}-{attempt}"


def parse_topic(text: str) -> Topic:
    """The topic a name stands for; InvalidTopic for anything else."""
    if text == WORKER_NODES_TOPIC:
        return Topic(TopicKind.WORKER_NODES)
    if text == CAMPAIGNS_TOPIC:
        return Topic(TopicKind.CAMPAIGNS)
    for prefix, kind in ((CAMPAIGN_PREFIX, TopicKind.CAMPAIGN), (JOB_PREFIX, TopicKind.JOB)):
        if text.startswith(prefix):
            key = text[len(prefix) :]
            if not _KEY_PATTERN.match(key):
                raise InvalidTopic(f"invalid {kind.value} id in topic {text!r}")
            return Topic(kind, key)
    if text.startswith(INSTANCE_PREFIX):
        worker_node_id, separator, instance = text[len(INSTANCE_PREFIX) :].partition("/")
        if not separator or not _SCOPE_ID_PATTERN.match(worker_node_id) or not _SCOPE_ID_PATTERN.match(instance):
            raise InvalidTopic(f"an instance topic is instance:<worker node id>/<instance>, got {text!r}")
        parse_instance(instance)
        return Topic(TopicKind.INSTANCE, f"{worker_node_id}/{instance}", worker_node_id, instance)
    raise InvalidTopic(f"unknown topic {text!r}: use worker nodes, campaigns, campaign:<id>, job:<id> or instance:<worker node id>/<instance>")


def parse_instance(instance: str) -> InstanceName:
    """job-<job id>-<attempt>, or <subsystem>-<index> of a pooled subsystem; InvalidTopic otherwise."""
    if instance.startswith(JOB_INSTANCE_PREFIX):
        job_id, separator, attempt = instance[len(JOB_INSTANCE_PREFIX) :].rpartition("-")
        if not separator or not job_id or not attempt.isdigit() or int(attempt) < 1:
            raise InvalidTopic(f"a job instance is job-<job id>-<attempt>, got {instance!r}")
        return InstanceName(kind=None, job_id=job_id, attempt=int(attempt))
    subsystem, separator, index = instance.rpartition("-")
    for kind in POOL_INSTANCE_KINDS:
        if separator and subsystem == kind.value and index.isdigit():
            return InstanceName(kind=kind)
    raise InvalidTopic(f"unknown instance {instance!r}: a pool is scene_generation-<index> or trajectory_generation-<index>, a job job-<job id>-<attempt>")


# Wire


class InvalidLiveMessage(ValueError):
    pass


_CLIENT_MESSAGES: TypeAdapter = TypeAdapter(ClientMessage)
_SERVER_MESSAGES: TypeAdapter = TypeAdapter(ServerMessage)


def decode_client_message(text: Union[str, bytes]) -> Union[Subscribe, Configure, Unsubscribe, Ping]:
    return _decode(text, _CLIENT_MESSAGES)


def decode_server_message(text: Union[str, bytes]) -> Union[Subscribed, Update, Unsubscribed, Error, Pong]:
    return _decode(text, _SERVER_MESSAGES)


def _decode(text: Union[str, bytes], adapter: TypeAdapter) -> Any:
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as error:
        raise InvalidLiveMessage(f"the message is not JSON: {error}") from error
    if not isinstance(data, dict):
        raise InvalidLiveMessage(f"a message is a JSON object, got {type(data).__name__}")
    if data.get("version") != LIVE_VERSION:
        raise InvalidLiveMessage(f"unsupported live channel version {data.get('version')!r}; this control node speaks {LIVE_VERSION}")
    try:
        return adapter.validate_python(data)
    except ValidationError as error:
        raise InvalidLiveMessage(f"invalid {data.get('type', 'untyped')!s} message: {error.errors(include_url=False, include_context=False, include_input=False)}") from error
