"""Whether a connected worker node may receive offers now, and why not.

The job store's claim matches each job against the worker node's slots, usable components, labels,
fingerprints and its last reported free memory and CPUs. The checks here are about the worker node as a
whole: it must be online, have a component that is up to date, and not be short of memory or overloaded. Free memory and load
come from the last heartbeat, so jobs offered since then are not counted yet; the guard
keeps a margin for them, and a worker node that cannot take a job rejects it (no attempt used).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Collection, Optional

from scenegems_tool.persistence.schema import WorkerNodeStatus
from scenegems_tool.persistence.stores import WorkerNodeRecord


@dataclass(frozen=True)
class ResourceGuard:
    min_free_memory_mb: int = 512  # below this a worker node gets no new offers, whatever a job's own minimum says
    max_load_average: float = 1.5  # one-minute load per CPU above which a worker node gets no new offers


class Ineligibility(str, Enum):
    NOT_ONLINE = "not online"  # draining or offline
    FINGERPRINTS_UNKNOWN = "the control node's expected fingerprints are not available"
    OUT_OF_DATE = "out of date"  # every component's images differ from the release
    LOW_MEMORY = "low on free memory"
    OVERLOADED = "overloaded"


def ineligibility(worker_node: WorkerNodeRecord, usable_components: Collection[str], fingerprints_known: bool, guard: ResourceGuard) -> Optional[Ineligibility]:
    """None when the worker node may receive offers, else the first reason it may not; usable_components are its components that are up to date."""
    if worker_node.status != WorkerNodeStatus.ONLINE:
        return Ineligibility.NOT_ONLINE
    if not fingerprints_known:
        return Ineligibility.FINGERPRINTS_UNKNOWN
    if worker_node.components and not usable_components:
        return Ineligibility.OUT_OF_DATE
    if worker_node.resources.free_memory_mb < guard.min_free_memory_mb:
        return Ineligibility.LOW_MEMORY
    if worker_node.resources.load_average > guard.max_load_average:
        return Ineligibility.OVERLOADED
    return None
