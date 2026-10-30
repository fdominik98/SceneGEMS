"""Frames on the node's control WebSocket, one model per message type.

The node opens the WebSocket (outbound only) and sends Hello first; the master answers
Welcome or ProtocolError. After that:

    master to node: LeaseOffer, LeaseRenewed, Drain, Cancel, Observe, ProtocolError
    node to master: Heartbeat, LeaseAccept, LeaseReject, LeaseRenew, LeaseRelease,
                    JobStatus, JobResult, LogLines, ObservationFrames

A lease is the master's time-limited grant of one job to one node. The node renews it
while the job runs; a lease that is not renewed expires and the job returns to the queue.

Observation (live simulations): while a browser observes a running simulation, the master
sends its node Observe with active true and the chosen speed, and the node relays the run's
frames in ObservationFrames batches, at most about 10 a second. Observe with active false
ends it; the node sends nothing for a job nobody observes.
"""

from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import AwareDatetime, Field

from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolFrame, ProtocolModel
from scenegems_tool.cluster.protocol.node_description import NodeResources, SlotOffer, SlotUsage

DEFAULT_OBSERVED_SPEED = 10.0  # an observed run's pace as a multiple of real time, unless the observer chooses one
MAX_OBSERVED_SPEED = 1000.0
MAX_OBSERVATION_FRAMES = 200  # frames per ObservationFrames batch
MAX_OBSERVATION_BATCH_BYTES = 8 * 1024 * 1024  # the node keeps a batch's frames below this, far under the link's 64 MiB

# Node to master


class Hello(ProtocolFrame):
    type: Literal["hello"] = "hello"
    node_id: str
    node_name: str
    software_revision: str  # git commit of the checkout the node runs
    machine: Optional[str] = None  # the machine the node runs on, as the deployment tool names it
    slots: List[SlotOffer]  # how many jobs of each type the node runs at once
    components: List[str]  # what it runs them with (cluster/fingerprints/components.py), images installed
    labels: Dict[str, str] = Field(default_factory=dict)
    resources: NodeResources
    fingerprints: Dict[str, str] = Field(default_factory=dict)  # image name to build fingerprint
    running_lease_ids: List[str] = Field(default_factory=list)  # leases still running after a reconnect


class Heartbeat(ProtocolFrame):
    type: Literal["heartbeat"] = "heartbeat"
    resources: NodeResources
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
    """The node gives a job back without a result, for example while draining."""

    type: Literal["lease_release"] = "lease_release"
    lease_id: str
    reason: str


class JobStatus(ProtocolFrame):
    type: Literal["job_status"] = "job_status"
    lease_id: str
    job_id: str
    progress: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    message: str = ""


class JobResult(ProtocolFrame):
    type: Literal["job_result"] = "job_result"
    lease_id: str
    job_id: str
    idempotency_key: str
    outcome: JobOutcome
    result: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    retryable: bool = False  # a failure the master may retry on another attempt


class LogStream(str, Enum):
    STDOUT = "stdout"
    STDERR = "stderr"
    DAEMON = "daemon"  # the node daemon's own lines about the job


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
    seq: int = Field(ge=1)  # the batch's number for the job attempt on its node, from 1, in order
    frames: List[Dict[str, Any]] = Field(min_length=1, max_length=MAX_OBSERVATION_FRAMES)


# Master to node


class Welcome(ProtocolFrame):
    type: Literal["welcome"] = "welcome"
    master_id: str
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


NodeMessage = Annotated[
    Union[Hello, Heartbeat, LeaseAccept, LeaseReject, LeaseRenew, LeaseRelease, JobStatus, JobResult, LogLines, ObservationFrames],
    Field(discriminator="type"),
]
MasterMessage = Annotated[
    Union[Welcome, LeaseOffer, LeaseRenewed, Drain, Cancel, Observe, ProtocolError],
    Field(discriminator="type"),
]
