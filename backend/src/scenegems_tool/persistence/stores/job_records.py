"""Detached snapshots of jobs, leases and events, and the outcome of each job store primitive."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from scenegems_tool.cluster.protocol.jobs import JobRequirements, JobSpec, JobState, JobType
from scenegems_tool.persistence.schema import JobEventKind, JobEventRow, JobRow


def requirements_of(row: JobRow) -> JobRequirements:
    return JobRequirements(
        labels=dict(row.required_labels),
        components=list(row.required_components or ()),  # unset on a row that was never flushed
        fingerprints=dict(row.required_fingerprints),
        min_memory_mb=row.min_memory_mb,
        min_cpus=row.min_cpus,
    )


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    job_type: JobType
    payload: Dict[str, Any]
    requirements: JobRequirements
    priority: int
    max_attempts: int
    idempotency_key: str
    state: JobState
    attempt: int  # number of the latest lease, 0 before the first
    failed_attempts: int  # leases that failed or expired; the job fails when this reaches max_attempts
    lease_id: Optional[str]  # latest lease; active only while the state is leased or running
    lease_owner: Optional[str]
    lease_expires_at: Optional[datetime]  # set only while the lease is active
    submitted_at: datetime
    available_at: datetime  # not claimed before; HELD_UNTIL while held
    updated_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    result_attempt: Optional[int]
    result: Optional[Dict[str, Any]]
    error: Optional[str]
    allowed_nodes: Tuple[str, ...] = ()  # node ids that may claim the job, empty for any

    @classmethod
    def from_row(cls, row: JobRow) -> "JobRecord":
        return cls(
            job_id=row.id,
            job_type=row.job_type,
            payload=dict(row.payload),
            requirements=requirements_of(row),
            priority=row.priority,
            max_attempts=row.max_attempts,
            idempotency_key=row.idempotency_key,
            state=row.state,
            attempt=row.attempt,
            failed_attempts=row.failed_attempts,
            lease_id=row.lease_id,
            lease_owner=row.lease_owner,
            lease_expires_at=row.lease_expires_at,
            submitted_at=row.submitted_at,
            available_at=row.available_at,
            updated_at=row.updated_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
            result_attempt=row.result_attempt,
            result=None if row.result is None else dict(row.result),
            error=row.error,
            allowed_nodes=tuple(row.allowed_nodes or ()),  # unset on a row that was never flushed
        )


@dataclass(frozen=True)
class Lease:
    """An active lease: the job as offered to its node, and until when the lease holds."""

    lease_id: str
    node_id: str
    state: JobState  # leased (offered) or running (accepted)
    expires_at: datetime
    job: JobSpec

    @classmethod
    def from_row(cls, row: JobRow) -> "Lease":
        job = JobSpec(job_id=row.id, job_type=row.job_type, payload=dict(row.payload), requirements=requirements_of(row), attempt=row.attempt, idempotency_key=row.idempotency_key)
        return cls(lease_id=row.lease_id, node_id=row.lease_owner, state=row.state, expires_at=row.lease_expires_at, job=job)


@dataclass(frozen=True)
class SubmitOutcome:
    job: JobRecord
    created: bool  # False when a job with the same idempotency key already existed


class ResultStatus(str, Enum):
    STORED = "stored"  # the result of the current lease, now stored
    DUPLICATE = "duplicate"  # the same lease reported before; the stored result is unchanged
    STALE = "stale"  # the lease is no longer current (expired, released, cancelled, superseded); nothing stored


@dataclass(frozen=True)
class ResultReport:
    status: ResultStatus
    job: JobRecord


@dataclass(frozen=True)
class CancelOutcome:
    job: JobRecord
    cancelled: bool  # False when the job had already finished
    lease_id: Optional[str]  # the lease that was active, so the master can send Cancel to its node
    node_id: Optional[str]


@dataclass(frozen=True)
class ExpiredLease:
    lease_id: str
    node_id: str
    job: JobRecord  # queued for the next attempt, or failed when it had no attempts left


@dataclass(frozen=True)
class JobEventRecord:
    event_id: int
    job_id: str
    at: datetime
    kind: JobEventKind
    from_state: Optional[JobState]
    to_state: JobState
    attempt: int
    lease_id: Optional[str]
    node_id: Optional[str]
    detail: Dict[str, Any]

    @classmethod
    def from_row(cls, row: JobEventRow) -> "JobEventRecord":
        return cls(
            event_id=row.id,
            job_id=row.job_id,
            at=row.at,
            kind=row.kind,
            from_state=row.from_state,
            to_state=row.to_state,
            attempt=row.attempt,
            lease_id=row.lease_id,
            node_id=row.node_id,
            detail=dict(row.detail),
        )
