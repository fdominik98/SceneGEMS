"""Pure rules of a job's life: when a lease is current, retries, and result idempotency.

A lease holds until its expiry instant. After that no accept, renew, release or result
succeeds for it, even before expire_leases has requeued the job, so the outcome never
depends on when the sweep runs.

A failed attempt is a lease that expired or reported a failure. Leases given back unused
(rejected or released) are not failed attempts, so draining a worker node does not use up a
job's retries.

A reported retryable failure puts the job back in the queue after an exponential backoff;
an expired lease requeues it at once, since its worker node is gone and another may take it.
"""

from datetime import datetime
from typing import Optional

from scenegems_tool.cluster.protocol.jobs import JobState
from scenegems_tool.persistence.stores.job_records import ResultStatus

ACTIVE_STATES = (JobState.LEASED, JobState.RUNNING)


def lease_is_current(state: JobState, job_lease_id: Optional[str], lease_expires_at: Optional[datetime], lease_id: str, now: datetime) -> bool:
    return state in ACTIVE_STATES and job_lease_id == lease_id and lease_expires_at is not None and now < lease_expires_at


def state_after_failed_attempt(failed_attempts: int, max_attempts: int, retryable: bool = True) -> JobState:
    """The state after a failed attempt, given the failed attempts including this one."""
    if retryable and failed_attempts < max_attempts:
        return JobState.QUEUED
    return JobState.FAILED


def retry_backoff_s(failed_attempts: int, base_s: float, cap_s: float) -> float:
    """Seconds a job waits after its failed_attempts-th failed attempt: base doubled per earlier failure, at most cap."""
    if failed_attempts < 1:
        raise ValueError(f"the backoff follows a failed attempt, got failed_attempts={failed_attempts}")
    # Doubling stops at the cap, so a long retry limit cannot overflow the float
    exponent = min(failed_attempts - 1, 64)
    return min(base_s * 2.0**exponent, cap_s)


def result_status(
    state: JobState,
    job_lease_id: Optional[str],
    lease_expires_at: Optional[datetime],
    attempt: int,
    result_attempt: Optional[int],
    lease_id: str,
    now: datetime,
) -> ResultStatus:
    """How to treat a result reported for lease_id.

    A lease identifies one attempt of one job, so a second report from the same lease is
    the same idempotency key and attempt and is recognized as a duplicate, also after a
    retryable failure requeued the job. Once a newer lease exists the old one is stale.
    """
    if job_lease_id == lease_id and result_attempt == attempt:
        return ResultStatus.DUPLICATE
    if lease_is_current(state, job_lease_id, lease_expires_at, lease_id, now):
        return ResultStatus.STORED
    return ResultStatus.STALE
