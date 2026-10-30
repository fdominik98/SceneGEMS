"""The job queue and its leases, as atomic steps the master's scheduler and lease manager call.

A job moves queued, leased (offered to a node), running (accepted), and ends succeeded,
failed or cancelled. Expired, rejected and released leases return it to the queue; see
job_lifecycle for the rules. Every state change appends one job_event row in the same
transaction.

Availability: a queued job is claimed only once its available_at has passed. A reported
retryable failure sets it to now plus the backoff (retry_backoff_s with this store's base
and cap). hold_jobs moves the jobs of a set to HELD_UNTIL (a campaign's pause) and
release_held_jobs makes them available at once; a held job that is leased keeps running,
and stays held if it comes back to the queue.

Concurrency: the claim locks the node row (serializing claims per node, so slots hold) and
picks the job with FOR UPDATE SKIP LOCKED (so claims for different nodes never block each
other or take the same job). Every other step locks the job row it changes.
"""

from datetime import datetime, timedelta
from typing import Collection, List, Optional
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobState, JobSubmission, JobType
from scenegems_tool.cluster.protocol.messages import JobResult
from scenegems_tool.persistence.clock import Clock, utc_now
from scenegems_tool.persistence.database import transaction
from scenegems_tool.persistence.schema import HELD_UNTIL, JobEventKind, JobRow, NodeRow, NodeStatus
from scenegems_tool.persistence.stores.job_claim import free_job_types, next_queued_job_query
from scenegems_tool.persistence.stores.job_event_log import append_job_event, job_events
from scenegems_tool.persistence.stores.job_lifecycle import ACTIVE_STATES, lease_is_current, result_status, retry_backoff_s, state_after_failed_attempt
from scenegems_tool.persistence.stores.job_records import CancelOutcome, ExpiredLease, JobEventRecord, JobRecord, Lease, ResultReport, ResultStatus, SubmitOutcome
from scenegems_tool.persistence.stores.store_session import session_scope


class UnknownNode(LookupError):
    pass


class UnknownJob(LookupError):
    pass


class IdempotencyKeyMismatch(ValueError):
    pass


def _lease_expiry(now: datetime, lease_duration_s: float) -> datetime:
    if lease_duration_s <= 0:
        raise ValueError(f"lease duration must be positive, got {lease_duration_s} s")
    return now + timedelta(seconds=lease_duration_s)


DEFAULT_RETRY_BACKOFF_BASE_S = 5.0
DEFAULT_RETRY_BACKOFF_CAP_S = 300.0
UNFINISHED_STATES = (JobState.QUEUED,) + ACTIVE_STATES


class JobStore:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        clock: Clock = utc_now,
        retry_backoff_base_s: float = DEFAULT_RETRY_BACKOFF_BASE_S,
        retry_backoff_cap_s: float = DEFAULT_RETRY_BACKOFF_CAP_S,
    ):
        if retry_backoff_base_s < 0 or retry_backoff_cap_s < 0:
            raise ValueError(f"the retry backoff needs a base and a cap of at least 0 s, got {retry_backoff_base_s} and {retry_backoff_cap_s}")
        self._sessions = session_factory
        self._clock = clock
        self.retry_backoff_base_s = retry_backoff_base_s
        self.retry_backoff_cap_s = retry_backoff_cap_s

    # Submission and queries

    def submit(self, submission: JobSubmission) -> SubmitOutcome:
        """Queues a job. A second submission with the same idempotency key returns the first job.

        Without a key the job id becomes the key. Concurrent submissions with one key create
        one job: the insert skips on the key's unique constraint.
        """
        now = self._clock()
        job_id = str(uuid4())
        idempotency_key = submission.idempotency_key or job_id
        requirements = submission.requirements
        with transaction(self._sessions) as session:
            statement = (
                insert(JobRow)
                .values(
                    id=job_id,
                    job_type=submission.job_type,
                    payload=submission.payload,
                    required_labels=requirements.labels,
                    required_fingerprints=requirements.fingerprints,
                    required_components=list(requirements.components),
                    min_memory_mb=requirements.min_memory_mb,
                    min_cpus=requirements.min_cpus,
                    allowed_nodes=list(submission.allowed_nodes),
                    priority=submission.priority,
                    max_attempts=submission.max_attempts,
                    idempotency_key=idempotency_key,
                    state=JobState.QUEUED,
                    attempt=0,
                    failed_attempts=0,
                    submitted_at=now,
                    available_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(index_elements=[JobRow.idempotency_key])
                .returning(JobRow.id)
            )
            if session.execute(statement).scalar_one_or_none() is None:
                existing = session.execute(select(JobRow).where(JobRow.idempotency_key == idempotency_key)).scalar_one()
                return SubmitOutcome(job=JobRecord.from_row(existing), created=False)
            row = session.get(JobRow, job_id)
            append_job_event(session, row, JobEventKind.SUBMITTED, None, now, {"priority": submission.priority, "max_attempts": submission.max_attempts})
            return SubmitOutcome(job=JobRecord.from_row(row), created=True)

    def get(self, job_id: str) -> Optional[JobRecord]:
        with transaction(self._sessions) as session:
            row = session.get(JobRow, job_id)
            return None if row is None else JobRecord.from_row(row)

    def list_jobs(self, state: Optional[JobState] = None, limit: int = 100) -> List[JobRecord]:
        """Jobs in submission order, optionally only those in one state."""
        with transaction(self._sessions) as session:
            query = select(JobRow).order_by(JobRow.seq).limit(limit)
            if state is not None:
                query = query.where(JobRow.state == state)
            return [JobRecord.from_row(row) for row in session.execute(query).scalars()]

    def events(self, job_id: str) -> List[JobEventRecord]:
        with transaction(self._sessions) as session:
            return job_events(session, job_id)

    def active_leases(self, node_id: Optional[str] = None) -> List[Lease]:
        """Leases in state leased or running, of one node or of all; for reconciling after a reconnect."""
        with transaction(self._sessions) as session:
            query = select(JobRow).where(JobRow.state.in_(ACTIVE_STATES)).order_by(JobRow.seq)
            if node_id is not None:
                query = query.where(JobRow.lease_owner == node_id)
            return [Lease.from_row(row) for row in session.execute(query).scalars()]

    # Leases

    def claim_next(
        self,
        node_id: str,
        lease_duration_s: float,
        job_types: Optional[Collection[JobType]] = None,
        exclude_job_ids: Collection[str] = (),
        components: Optional[Collection[str]] = None,
    ) -> Optional[Lease]:
        """Leases the next matching queued job to the node, or returns None.

        Considers only online nodes and job types the node has a free slot for (slots minus
        its leased and running jobs of that type), optionally limited to job_types, and skips
        the jobs in exclude_job_ids and those not available yet. A job's components must be among
        components (the node's usable ones, which the scheduler passes) or, when None, among the
        node's stored components. The match on labels, components, fingerprints, resources and allowed nodes and the
        order (priority, then submission) are in next_queued_job_query. The lease starts as
        an offer that holds for lease_duration_s; the node accepts it with accept().
        """
        now = self._clock()
        expires_at = _lease_expiry(now, lease_duration_s)
        with transaction(self._sessions) as session:
            # key_share without read is FOR NO KEY UPDATE: it serializes claims and heartbeats
            # of this node, but not the foreign key checks of job rows that reference it
            node = session.execute(select(NodeRow).where(NodeRow.id == node_id).with_for_update(key_share=True)).scalar_one_or_none()
            if node is None:
                raise UnknownNode(node_id)
            if node.status != NodeStatus.ONLINE:
                return None
            active_counts = dict(session.execute(select(JobRow.job_type, func.count()).where(JobRow.lease_owner == node_id, JobRow.state.in_(ACTIVE_STATES)).group_by(JobRow.job_type)).all())
            job_types = free_job_types({capability.job_type: capability.slots for capability in node.capabilities}, active_counts, job_types)
            if not job_types:
                return None
            fingerprints = {fingerprint.image: fingerprint.fingerprint for fingerprint in node.fingerprints}
            offered = sorted(components) if components is not None else [component.component for component in node.components]
            query = next_queued_job_query(job_types, node.labels, fingerprints, node.free_memory_mb, node.cpus, exclude_job_ids, now=now, node_id=node_id, components=offered)
            row = session.execute(query).scalar_one_or_none()
            if row is None:
                return None
            row.state = JobState.LEASED
            row.attempt += 1
            row.lease_id = str(uuid4())
            row.lease_owner = node_id
            row.lease_expires_at = expires_at
            row.updated_at = now
            append_job_event(session, row, JobEventKind.LEASED, JobState.QUEUED, now, {"expires_at": expires_at.isoformat()})
            return Lease.from_row(row)

    def accept(self, lease_id: str, lease_duration_s: float) -> Optional[Lease]:
        """The node accepted the offer: the job runs and the lease holds lease_duration_s from now.

        Accepting a running lease again returns it unchanged. Returns None when the lease is
        not current (unknown, expired, ended).
        """
        now = self._clock()
        expires_at = _lease_expiry(now, lease_duration_s)
        with transaction(self._sessions) as session:
            row = self._lock_by_lease(session, lease_id)
            if row is None or not lease_is_current(row.state, row.lease_id, row.lease_expires_at, lease_id, now):
                return None
            if row.state == JobState.RUNNING:
                return Lease.from_row(row)
            row.state = JobState.RUNNING
            row.lease_expires_at = expires_at
            row.started_at = row.started_at or now
            row.updated_at = now
            append_job_event(session, row, JobEventKind.ACCEPTED, JobState.LEASED, now)
            return Lease.from_row(row)

    def renew(self, lease_id: str, lease_duration_s: float) -> Optional[Lease]:
        """Extends a running lease to lease_duration_s from now, or returns None when it is not current.

        Renewals are not recorded as job events.
        """
        now = self._clock()
        expires_at = _lease_expiry(now, lease_duration_s)
        with transaction(self._sessions) as session:
            row = self._lock_by_lease(session, lease_id)
            if row is None or row.state != JobState.RUNNING or not lease_is_current(row.state, row.lease_id, row.lease_expires_at, lease_id, now):
                return None
            row.lease_expires_at = expires_at
            row.updated_at = now
            return Lease.from_row(row)

    def reject(self, lease_id: str, reason: str) -> Optional[JobRecord]:
        """The node refused the offer: the job is queued again without a failed attempt."""
        return self._give_back(lease_id, reason, JobEventKind.REJECTED, (JobState.LEASED,))

    def release(self, lease_id: str, reason: str) -> Optional[JobRecord]:
        """The node gave the job back unfinished (for example while draining): queued again without a failed attempt."""
        return self._give_back(lease_id, reason, JobEventKind.RELEASED, ACTIVE_STATES)

    def report_result(self, report: JobResult) -> ResultReport:
        """Stores the result of the current lease once.

        A success ends the job. A failure counts as a failed attempt: retryable failures
        are queued again while attempts remain, available after the backoff (a held job stays
        held), others fail the job. A second report from
        the same lease returns DUPLICATE and changes nothing; a report from a lease that is
        no longer current returns STALE and changes nothing.
        """
        now = self._clock()
        with transaction(self._sessions) as session:
            row = session.execute(select(JobRow).where(JobRow.id == report.job_id).with_for_update()).scalar_one_or_none()
            if row is None:
                raise UnknownJob(report.job_id)
            if row.idempotency_key != report.idempotency_key:
                raise IdempotencyKeyMismatch(f"job {row.id} has idempotency key {row.idempotency_key!r}, the result carries {report.idempotency_key!r}")
            status = result_status(row.state, row.lease_id, row.lease_expires_at, row.attempt, row.result_attempt, report.lease_id, now)
            if status != ResultStatus.STORED:
                return ResultReport(status=status, job=JobRecord.from_row(row))
            from_state = row.state
            row.result_attempt = row.attempt
            row.result = report.result
            row.lease_expires_at = None
            row.updated_at = now
            if report.outcome == JobOutcome.SUCCEEDED:
                row.state = JobState.SUCCEEDED
                row.error = None
                kind = JobEventKind.SUCCEEDED
            else:
                row.failed_attempts += 1
                row.state = state_after_failed_attempt(row.failed_attempts, row.max_attempts, report.retryable)
                row.error = report.error
                kind = JobEventKind.ATTEMPT_FAILED if row.state == JobState.QUEUED else JobEventKind.FAILED
            detail = {"error": report.error, "retryable": report.retryable} if report.error else {}
            if row.state == JobState.QUEUED:
                row.available_at = self._available_after_failure(row, now)
                detail["available_at"] = row.available_at.isoformat()
            if row.state.is_terminal:
                row.finished_at = now
            append_job_event(session, row, kind, from_state, now, detail)
            return ResultReport(status=status, job=JobRecord.from_row(row))

    def cancel(self, job_id: str, reason: str) -> CancelOutcome:
        """Cancels a job that has not finished. When it had an active lease, the outcome names it."""
        now = self._clock()
        with transaction(self._sessions) as session:
            row = session.execute(select(JobRow).where(JobRow.id == job_id).with_for_update()).scalar_one_or_none()
            if row is None:
                raise UnknownJob(job_id)
            if row.state.is_terminal:
                return CancelOutcome(job=JobRecord.from_row(row), cancelled=False, lease_id=None, node_id=None)
            from_state = row.state
            was_active = from_state in ACTIVE_STATES
            row.state = JobState.CANCELLED
            row.lease_expires_at = None
            row.updated_at = now
            row.finished_at = now
            append_job_event(session, row, JobEventKind.CANCELLED, from_state, now, {"reason": reason})
            return CancelOutcome(job=JobRecord.from_row(row), cancelled=True, lease_id=row.lease_id if was_active else None, node_id=row.lease_owner if was_active else None)

    def expire_leases(self, limit: Optional[int] = None) -> List[ExpiredLease]:
        """Ends every lease whose expiry has passed; each counts as a failed attempt.

        The job is queued for its next attempt, or failed when it has no attempts left.
        Rows another transaction holds (a renewal in flight) are skipped and seen by the
        next call.
        """
        now = self._clock()
        expired: List[ExpiredLease] = []
        with transaction(self._sessions) as session:
            query = select(JobRow).where(JobRow.state.in_(ACTIVE_STATES), JobRow.lease_expires_at <= now).order_by(JobRow.lease_expires_at, JobRow.seq).limit(limit).with_for_update(skip_locked=True)
            for row in session.execute(query).scalars().all():
                from_state = row.state
                lease_expired_at = row.lease_expires_at
                row.failed_attempts += 1
                row.state = state_after_failed_attempt(row.failed_attempts, row.max_attempts)
                row.lease_expires_at = None
                row.updated_at = now
                if row.state == JobState.FAILED:
                    row.error = f"lease expired on attempt {row.attempt}, no attempts left"
                    row.finished_at = now
                append_job_event(session, row, JobEventKind.EXPIRED, from_state, now, {"lease_expired_at": lease_expired_at.isoformat()})
                expired.append(ExpiredLease(lease_id=row.lease_id, node_id=row.lease_owner, job=JobRecord.from_row(row)))
        return expired

    # Holds

    def hold_jobs(self, job_ids: Collection[str], *, session: Optional[Session] = None) -> List[str]:
        """Holds the unfinished jobs among job_ids: none of them is claimed until released.

        Queued jobs wait; leased and running ones go on and stay held if they come back to
        the queue. Returns the ids held by this call, sorted. With a session the change is
        part of the caller's transaction.
        """
        return self._set_availability(job_ids, HELD_UNTIL, JobRow.available_at < HELD_UNTIL, session)

    def release_held_jobs(self, job_ids: Collection[str], *, session: Optional[Session] = None) -> List[str]:
        """Makes the held jobs among job_ids available now; returns the ids released, sorted."""
        return self._set_availability(job_ids, self._clock(), JobRow.available_at >= HELD_UNTIL, session)

    # Helpers

    def _available_after_failure(self, row: JobRow, now: datetime) -> datetime:
        if row.available_at >= HELD_UNTIL:
            return row.available_at
        return now + timedelta(seconds=retry_backoff_s(row.failed_attempts, self.retry_backoff_base_s, self.retry_backoff_cap_s))

    def _set_availability(self, job_ids: Collection[str], available_at: datetime, condition, session: Optional[Session]) -> List[str]:
        job_ids = sorted(set(job_ids))
        if not job_ids:
            return []
        statement = (
            update(JobRow)
            .where(JobRow.id.in_(job_ids), JobRow.state.in_(UNFINISHED_STATES), condition)
            .values(available_at=available_at, updated_at=self._clock())
            .returning(JobRow.id)
            .execution_options(synchronize_session=False)
        )
        with session_scope(self._sessions, session) as scope:
            return sorted(scope.execute(statement).scalars())

    @staticmethod
    def _lock_by_lease(session: Session, lease_id: str) -> Optional[JobRow]:
        return session.execute(select(JobRow).where(JobRow.lease_id == lease_id).with_for_update()).scalar_one_or_none()

    def _give_back(self, lease_id: str, reason: str, kind: JobEventKind, allowed_states: Collection[JobState]) -> Optional[JobRecord]:
        now = self._clock()
        with transaction(self._sessions) as session:
            row = self._lock_by_lease(session, lease_id)
            if row is None or row.state not in allowed_states or not lease_is_current(row.state, row.lease_id, row.lease_expires_at, lease_id, now):
                return None
            from_state = row.state
            row.state = JobState.QUEUED
            row.lease_expires_at = None
            row.updated_at = now
            append_job_event(session, row, kind, from_state, now, {"reason": reason})
            return JobRecord.from_row(row)
