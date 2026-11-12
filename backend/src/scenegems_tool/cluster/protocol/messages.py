"""Frames on the worker node's control WebSocket, one model per message type.

The worker node opens the WebSocket (outbound only) and sends Hello first; the control node answers
Welcome or ProtocolError. After that:

    control node to worker node: LeaseOffer, LeaseRenewed, Drain, Cancel, Observe, StartJob, ProtocolError
    worker node to control node: Heartbeat, LeaseAccept, LeaseReject, LeaseRenew, LeaseRelease,
                    JobStatus, JobResult, LogLines, ObservationFrames

A lease is the control node's time-limited grant of one job to one worker node. The worker node renews it
while the job runs; a lease that is not renewed expires and the job returns to the queue.

Observation (live simulations): while a browser observes a running simulation, the control node
sends its worker node Observe with active true and the chosen speed, and the worker node relays the run's
frames in ObservationFrames batches, at most about 10 a second. Observe with active false
ends it; the worker node sends nothing for a job nobody observes.
"""

from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import AwareDatetime, Field

from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolFrame, ProtocolModel
from scenegems_tool.cluster.protocol.worker_node_description import SlotOffer, SlotUsage, WorkerNodeResources

DEFAULT_OBSERVED_SPEED = 10.0  # an observed run's pace as a multiple of real time, unless the observer chooses one
MAX_OBSERVED_SPEED = 1000.0
MAX_OBSERVATION_FRAMES = 200  # frames per ObservationFrames batch
MAX_OBSERVATION_BATCH_BYTES = 8 * 1024 * 1024  # the worker node keeps a batch's frames below this, far under the link's 64 MiB

# Keys and values of JobStatus.detail
STATUS_PHASE = "phase"  # where an attended simulation is
PHASE_PREPARING = "preparing"  # its stack is coming up
PHASE_READY_TO_START = "ready_to_start"  # it waits for the operator's Start (StartJob)
PHASE_RUNNING = "running"
STATUS_GROUND_CONTROL = "ground_control"  # agent id to the port on the worker node's host a ground control station connects to
# With a real vessel, before the Start: agent id to what its agent reports (connected, position, armable, at_start); the run is ready when all are true
STATUS_VESSELS = "vessels"

# Worker node to control node


class Hello(ProtocolFrame):
    type: Literal["hello"] = "hello"
    worker_node_id: str
    worker_node_name: str
    software_revision: str  # git commit of the checkout the worker node runs
    machine: Optional[str] = None  # the machine the worker node runs on, as the deployment tool names it
    slots: List[SlotOffer]  # how many jobs of each type the worker node runs at once
    components: List[str]  # what it runs them with (cluster/fingerprints/components.py), images installed
    labels: Dict[str, str] = Field(default_factory=dict)
    resources: WorkerNodeResources
    fingerprints: Dict[str, str] = Field(default_factory=dict)  # image name to build fingerprint
    running_lease_ids: List[str] = Field(default_factory=list)  # leases still running after a reconnect


class Heartbeat(ProtocolFrame):
    type: Literal["heartbeat"] = "heartbeat"
    resources: WorkerNodeResources
    slots_in_use: SlotUsage = Field(default_factory=dict)
    running_lease_ids: List[str] = Field(default_factory=list)


class LeaseAccept(ProtocolFrame):
    type: Literal["lease_accept"] = "lease_accept"
    lease_id: str


class LeaseReject(ProtocolFrame):
    type: Literal["lease_reject"] = "lease_reject"
    lease_id: str
    reason: str


class LeaseRenew(ProtocolFrame):
    type: Literal["lease_renew"] = "lease_renew"
    lease_id: str


class LeaseRelease(ProtocolFrame):
    """The worker node gives a job back without a result, for example while draining."""

    type: Literal["lease_release"] = "lease_release"
    lease_id: str
    reason: str


class JobStatus(ProtocolFrame):
    type: Literal["job_status"] = "job_status"
    lease_id: str
    job_id: str
    progress: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    message: str = ""
    # What the job says beyond its message: the phase of an attended simulation, the ports its stack published (job_container_io.py)
    detail: Optional[Dict[str, Any]] = None


class JobResult(ProtocolFrame):
    type: Literal["job_result"] = "job_result"
    lease_id: str
    job_id: str
    idempotency_key: str
    outcome: JobOutcome
    result: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    retryable: bool = False  # a failure the control node may retry on another attempt


class LogStream(str, Enum):
    STDOUT = "stdout"
    STDERR = "stderr"
    DAEMON = "daemon"  # the worker node daemon's own lines about the job


class LogLine(ProtocolModel):
    timestamp: AwareDatetime
    stream: LogStream
    source: str  # container or component that wrote the line
    text: str


class LogLines(ProtocolFrame):
    type: Literal["log_lines"] = "log_lines"
    lease_id: str
    job_id: str
    lines: List[LogLine]


class ObservationFrames(ProtocolFrame):
    """Frames of an observed run, in the workbench's frame wire format (gateway.serialization.serialize_frame and serialize_monitored_frame)."""

    type: Literal["observation_frames"] = "observation_frames"
    lease_id: str
    job_id: str
    attempt: int = Field(ge=1)
    seq: int = Field(ge=1)  # the batch's number for the job attempt on its worker node, from 1, in order
    frames: List[Dict[str, Any]] = Field(min_length=1, max_length=MAX_OBSERVATION_FRAMES)


# Control node to worker node


class Welcome(ProtocolFrame):
    type: Literal["welcome"] = "welcome"
    control_node_id: str
    # The worker node's number in the cluster, the same on every connection: it names the worker node's pooled services on MQTT
    instance_number: int = Field(ge=1)
    heartbeat_interval_s: float = Field(gt=0.0)
    lease_timeout_s: float = Field(gt=0.0)


class LeaseOffer(ProtocolFrame):
    type: Literal["lease_offer"] = "lease_offer"
    lease_id: str
    job: JobSpec
    expires_at: AwareDatetime  # accept and renew before this instant or the job is requeued


class LeaseRenewed(ProtocolFrame):
    type: Literal["lease_renewed"] = "lease_renewed"
    lease_id: str
    expires_at: AwareDatetime


class Drain(ProtocolFrame):
    """Stop accepting leases, finish the running ones."""

    type: Literal["drain"] = "drain"
    reason: str


class Cancel(ProtocolFrame):
    type: Literal["cancel"] = "cancel"
    lease_id: str
    job_id: str
    reason: str


class Observe(ProtocolFrame):
    """Start (active) or stop relaying the frames of a running job's attempt; a repeated Observe changes the speed."""

    type: Literal["observe"] = "observe"
    job_id: str
    attempt: int = Field(ge=1)
    active: bool
    speed: float = Field(default=DEFAULT_OBSERVED_SPEED, gt=0.0, le=MAX_OBSERVED_SPEED)  # multiple of real time


class StartJob(ProtocolFrame):
    """The operator's Start of an attended simulation that waits for it; a job that does not wait ignores it."""

    type: Literal["start_job"] = "start_job"
    job_id: str
    attempt: int = Field(ge=1)


class ProtocolErrorCode(str, Enum):
    VERSION_MISMATCH = "version_mismatch"
    MALFORMED_FRAME = "malformed_frame"
    UNAUTHORIZED = "unauthorized"
    UNKNOWN_LEASE = "unknown_lease"


class ProtocolError(ProtocolFrame):
    """Sent before the sender closes the connection, or as an answer to one bad frame."""

    type: Literal["protocol_error"] = "protocol_error"
    code: ProtocolErrorCode
    message: str


WorkerNodeMessage = Annotated[
    Union[Hello, Heartbeat, LeaseAccept, LeaseReject, LeaseRenew, LeaseRelease, JobStatus, JobResult, LogLines, ObservationFrames],
    Field(discriminator="type"),
]
ControlNodeMessage = Annotated[
    Union[Welcome, LeaseOffer, LeaseRenewed, Drain, Cancel, Observe, StartJob, ProtocolError],
    Field(discriminator="type"),
]
