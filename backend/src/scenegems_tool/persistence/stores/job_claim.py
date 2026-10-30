"""What a node can take, and the query that finds the next queued job for it.

The node's facts (free slots per job type, components, labels, fingerprints, resources) are read under
a lock on the node row, so concurrent claims for one node never exceed its slots. The job
itself is picked in SQL with SELECT ... FOR UPDATE SKIP LOCKED: concurrent claims for
different nodes skip the rows another claim holds instead of waiting for it, and no job is
claimed twice. Only jobs whose available_at has passed are taken, so a job in its retry
backoff or held by a paused campaign waits in the queue without blocking the ones behind it.
"""

from datetime import datetime
from typing import Collection, Dict, List, Mapping, Optional

from sqlalchemy import Select, or_, select

from scenegems_tool.cluster.protocol.jobs import JobState, JobType
from scenegems_tool.persistence.schema import JobRow


def free_job_types(slots: Mapping[JobType, int], active_leases: Mapping[JobType, int], only: Optional[Collection[JobType]] = None) -> List[JobType]:
    """Job types the node offers and has a free slot for, optionally limited to `only`."""
    return [job_type for job_type, count in slots.items() if active_leases.get(job_type, 0) < count and (only is None or job_type in only)]


def next_queued_job_query(
    job_types: Collection[JobType],
    labels: Dict[str, str],
    fingerprints: Dict[str, str],
    free_memory_mb: int,
    cpus: float,
    exclude_job_ids: Collection[str] = (),
    *,
    now: datetime,
    node_id: str,
    components: Collection[str] = (),
) -> Select:
    """The highest-priority, oldest queued job a node with these facts may run, locked.

    A job matches when its type is among job_types, its required labels, components and fingerprints
    are contained in the node's (JSONB containment; components are the node's usable ones), its memory and CPU minimums fit the
    node's free memory and CPUs, its allowed nodes are empty or name node_id, it is available
    by now, and it is not among exclude_job_ids (jobs the scheduler holds back from this node,
    for example after the node rejected them).
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
        or_(JobRow.allowed_nodes == [], JobRow.allowed_nodes.contains([node_id])),
    ]
    if exclude_job_ids:
        conditions.append(JobRow.id.notin_(list(exclude_job_ids)))
    return select(JobRow).where(*conditions).order_by(JobRow.priority.desc(), JobRow.submitted_at, JobRow.seq).limit(1).with_for_update(skip_locked=True)
