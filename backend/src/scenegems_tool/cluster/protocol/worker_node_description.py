"""What a worker node tells the control node about itself: slots per job type, components, labels, resources."""

from typing import Dict

from pydantic import Field

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.model_base import ProtocolModel


class SlotOffer(ProtocolModel):
    """One job type the worker node runs, with the number of jobs of that type it runs at once."""

    job_type: JobType
    slots: int = Field(ge=1)


class WorkerNodeResources(ProtocolModel):
    cpus: float = Field(ge=0.0)
    memory_mb: int = Field(ge=0)
    free_memory_mb: int = Field(ge=0)
    free_disk_mb: int = Field(ge=0)
    load_average: float = Field(default=0.0, ge=0.0)  # one-minute load per CPU, 0 where the host does not report it


SlotUsage = Dict[JobType, int]  # job type to the number of slots in use
