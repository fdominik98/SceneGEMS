"""What a worker node can take, and the query that finds the next queued job for it.

A job takes a slot of its own type, and one of every subsystem it runs a task in beside it: a simulation that
is judged while it runs requires the monitoring component and takes a monitoring slot
(cluster/fingerprints/components.py SHARED_SLOT_COMPONENTS). slot_usage counts both; a queued job that needs
such a slot is skipped while the worker node has none free.

The worker node's facts (free slots per job type, components, labels, fingerprints, resources) are read under
a lock on the worker node row, so concurrent claims for one worker node never exceed its slots. The job
itself is picked in SQL with SELECT ... FOR UPDATE SKIP LOCKED: concurrent claims for
different worker nodes skip the rows another claim holds instead of waiting for it, and no job is
claimed twice. Only jobs whose available_at has passed are taken, so a job in its retry
backoff or held by a paused campaign waits in the queue without blocking the ones behind it.
"""

from datetime import datetime
from typing import Collection, Dict, List, Mapping, Optional

from sqlalchemy import Select, not_, or_, select

from scenegems_tool.cluster.fingerprints.components import SHARED_SLOT_COMPONENTS
from scenegems_tool.cluster.protocol.jobs import JobState, JobType
from scenegems_tool.persistence.schema import JobRow


def free_job_types(slots: Mapping[JobType, int], active_leases: Mapping[JobType, int], only: Optional[Collection[JobType]] = None) -> List[JobType]:
    """Job types the worker node offers and has a free slot for, optionally limited to `only`."""
    return [job_type for job_type, count in slots.items() if active_leases.get(job_type, 0) < count and (only is None or job_type in only)]


def slot_usage(active_leases: Mapping[JobType, int], sharing_leases: Mapping[str, int]) -> Dict[JobType, int]:
    """The slots in use per job type: the active jobs of the type, and the active jobs of other types that require the component whose slots they share (sharing_leases, by component)."""
    usage = dict(active_leases)
    for component, slot_type in SHARED_SLOT_COMPONENTS.items():
        if sharing_leases.get(component, 0):
            usage[slot_type] = usage.get(slot_type, 0) + sharing_leases[component]
    return usage


def full_shared_components(slots: Mapping[JobType, int], usage: Mapping[JobType, int]) -> List[str]:
    """The components whose shared slots are all in use (or that the worker node offers no slots for): a job that requires one cannot start now."""
    return [component for component, slot_type in SHARED_SLOT_COMPONENTS.items() if usage.get(slot_type, 0) >= slots.get(slot_type, 0)]


def next_queued_job_query(
    job_types: Collection[JobType],
    labels: Dict[str, str],
    fingerprints: Dict[str, str],
    free_memory_mb: int,
    cpus: float,
    exclude_job_ids: Collection[str] = (),
    *,
    now: datetime,
    worker_node_id: str,
    components: Collection[str] = (),
    without_components: Collection[str] = (),
) -> Select:
    """The highest-priority, oldest queued job a worker node with these facts may run, locked.

    A job matches when its type is among job_types, its required labels, components and fingerprints
    are contained in the worker node's (JSONB containment; components are the worker node's usable ones), its memory and CPU minimums fit the
    worker node's free memory and CPUs, its allowed worker nodes are empty or name worker_node_id, it is available
    by now, and it is not among exclude_job_ids (jobs the scheduler holds back from this worker node,
    for example after the worker node rejected them). without_components are the components whose shared slots
    are all in use (full_shared_components): a job that requires one of them waits.
    """
    conditions = [
        JobRow.state == JobState.QUEUED,
        JobRow.available_at <= now,
        JobRow.job_type.in_(list(job_types)),
        JobRow.required_labels.contained_by(labels),
        JobRow.required_components.contained_by(list(components)),
        JobRow.required_fingerprints.contained_by(fingerprints),
        JobRow.min_memory_mb <= free_memory_mb,
        JobRow.min_cpus <= cpus,
        or_(JobRow.allowed_worker_nodes == [], JobRow.allowed_worker_nodes.contains([worker_node_id])),
    ]
    if exclude_job_ids:
        conditions.append(JobRow.id.notin_(list(exclude_job_ids)))
    for component in without_components:
        conditions.append(not_(JobRow.required_components.contains([component])))
    return select(JobRow).where(*conditions).order_by(JobRow.priority.desc(), JobRow.submitted_at, JobRow.seq).limit(1).with_for_update(skip_locked=True)
