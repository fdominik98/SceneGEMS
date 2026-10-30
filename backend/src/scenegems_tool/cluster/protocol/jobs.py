"""Jobs as master and node see them: types, states, requirements and the leased job.

A job is one unit of work that runs in one subsystem container on one node. The payload
is opaque here: each job type's module (cluster/node/jobs/) defines its payload model, which
the master checks at submission and the node again, with resolved artifacts, before it runs.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import Field

from scenegems_tool.cluster.protocol.model_base import ProtocolModel


class JobType(str, Enum):
    SCENE_GENERATION = "scene_generation"
    TRAJECTORY_GENERATION = "trajectory_generation"
    SIMULATION_KINEMATIC = "simulation.kinematic"  # replay or USV Navigation closed loop, in process
    SIMULATION_ARDUPILOT_SIM = "simulation.ardupilot_sim"  # replay over the lockstep MAVLink adapter on SITL's own physics, one stack per job
    SIMULATION_GAZEBO = "simulation.gazebo"  # the same against a Gazebo world
    MONITORING_POST_HOC = "monitoring.post_hoc"
    CALIBRATION_DEVIATION = "calibration.deviation"  # deviation between repeats of one case on one stack


class JobState(str, Enum):
    QUEUED = "queued"  # waiting for a matching node with a free slot
    LEASED = "leased"  # offered to a node, not yet accepted
    RUNNING = "running"  # accepted, the node runs it
    SUCCEEDED = "succeeded"
    FAILED = "failed"  # failed on its last allowed attempt
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED)


class JobOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobRequirements(ProtocolModel):
    """What a node must offer to receive the job; the job type itself is matched separately."""

    labels: Dict[str, str] = Field(default_factory=dict)  # every pair must be among the node's labels
    fingerprints: Dict[str, str] = Field(default_factory=dict)  # image name to required build fingerprint
    min_memory_mb: int = Field(default=0, ge=0)
    min_cpus: float = Field(default=0.0, ge=0.0)


class JobSubmission(ProtocolModel):
    """A request to run a job, sent to the master's job API."""

    job_type: JobType
    payload: Dict[str, Any] = Field(default_factory=dict)
    requirements: JobRequirements = Field(default_factory=JobRequirements)
    priority: int = 0  # higher runs first
    max_attempts: int = Field(default=3, ge=1)
    idempotency_key: Optional[str] = None  # a second submission with the same key returns the first job
    # Node ids that may run the job, empty for any node. The master matches it; offers do not carry it
    allowed_nodes: List[str] = Field(default_factory=list)


class JobSpec(ProtocolModel):
    """The job as offered to a node in a lease."""

    job_id: str
    job_type: JobType
    payload: Dict[str, Any] = Field(default_factory=dict)
    requirements: JobRequirements = Field(default_factory=JobRequirements)
    attempt: int = Field(ge=1)
    idempotency_key: str  # the node passes it on, so a result reported twice is stored once
