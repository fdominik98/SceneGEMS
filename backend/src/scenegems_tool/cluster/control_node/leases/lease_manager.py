"""The lease manager: what happens to a lease after its offer, until it ends.

The worker node accepts, renews, rejects or releases a lease and reports its result; the job
store decides atomically whether each step still applies (a lease is dead at its expiry
instant), and this module answers the worker node:

    accept, renew      LeaseRenewed with the new expiry, or Cancel when the lease is gone
    reject             the job is held back from this worker node for a while (reject_backoff)
    result             stored once; no answer, a second report changes nothing
    expiry sweep       expired leases are requeued (or failed after max_attempts) and their
                       worker node, when connected, gets Cancel so it stops the job
    reconnect          the Hello's running leases are reconciled with the store

A frame about a lease the session does not hold is answered with Cancel (lease frames) or
ProtocolError (results): a worker node can only act on its own leases. Every step that may change
a job's state is reported to JobActivity.changed, which the live channel listens to.
"""

import logging
from functools import partial
from typing import Callable, List

import anyio

from scenegems_tool.cluster.control_node.job_activity import JobActivity
from scenegems_tool.cluster.control_node.registry.lease_reconciliation import reconcile_leases
from scenegems_tool.cluster.control_node.registry.worker_node_registry import WorkerNodeRegistry
from scenegems_tool.cluster.control_node.registry.worker_node_session import WorkerNodeSession
from scenegems_tool.cluster.control_node.scheduling.reject_backoff import RejectBackoff
from scenegems_tool.cluster.control_node.timing import ControlTiming
from scenegems_tool.cluster.protocol.jobs import JobOutcome
from scenegems_tool.cluster.protocol.messages import Cancel, JobResult, JobStatus, LeaseAccept, LeaseReject, LeaseRelease, LeaseRenew, LeaseRenewed, LogLines, ProtocolError, ProtocolErrorCode
from scenegems_tool.cluster.protocol.model_base import ProtocolFrame
from scenegems_tool.persistence.stores import ExpiredLease, IdempotencyKeyMismatch, JobStore, Lease, ResultStatus, UnknownJob

logger = logging.getLogger(__name__)

NOT_HELD = "the lease is not held by this worker node"
NOT_CURRENT = "the lease is no longer current (expired, cancelled or given to another worker node)"


class LeaseManager:
    def __init__(self, job_store: JobStore, registry: WorkerNodeRegistry, backoff: RejectBackoff, activity: JobActivity, timing: ControlTiming, on_change: Callable[[], None]):
        self._jobs = job_store
        self._registry = registry
        self._backoff = backoff
        self._activity = activity
        self._timing = timing
        self._on_change = on_change  # wakes the scheduler

    async def _store(self, function, *arguments, **keywords):
        return await anyio.to_thread.run_sync(partial(function, *arguments, **keywords))

    # Frames from the worker node

    async def accept(self, session: WorkerNodeSession, frame: LeaseAccept) -> None:
        if not session.owns(frame.lease_id):
            await self._cancel(session, frame.lease_id, NOT_HELD)
            return
        lease = await self._store(self._jobs.accept, frame.lease_id, self._timing.lease_timeout_s)
        await self._confirm(session, frame.lease_id, lease)
        if lease is not None:
            self._activity.changed(lease.job.job_id)

    async def renew(self, session: WorkerNodeSession, frame: LeaseRenew) -> None:
        if not session.owns(frame.lease_id):
            await self._cancel(session, frame.lease_id, NOT_HELD)
            return
        lease = await self._store(self._jobs.renew, frame.lease_id, self._timing.lease_timeout_s)
        await self._confirm(session, frame.lease_id, lease)

    async def reject(self, session: WorkerNodeSession, frame: LeaseReject) -> None:
        if not session.owns(frame.lease_id):
            return
        job_id = session.job_of(frame.lease_id)
        session.forget(frame.lease_id)
        if await self._store(self._jobs.reject, frame.lease_id, frame.reason) is not None:
            until = self._backoff.rejected(session.worker_node_id, job_id)
            logger.info("Worker node %s rejected job %s (%s); not offered to it again before %s", session.worker_node_id, job_id, frame.reason, until.isoformat(timespec="seconds"))
        self._activity.changed(job_id)
        self._on_change()

    async def release(self, session: WorkerNodeSession, frame: LeaseRelease) -> None:
        if not session.owns(frame.lease_id):
            return
        job_id = session.job_of(frame.lease_id)
        session.forget(frame.lease_id)
        await self._store(self._jobs.release, frame.lease_id, frame.reason)
        self._activity.changed(job_id)
        self._on_change()

    async def result(self, session: WorkerNodeSession, frame: JobResult) -> None:
        if not session.owns(frame.lease_id, frame.job_id):
            await session.send(ProtocolError(code=ProtocolErrorCode.UNKNOWN_LEASE, message=f"Result for lease {frame.lease_id} ignored: {NOT_HELD}"))
            return
        try:
            report = await self._store(self._jobs.report_result, frame)
        except UnknownJob:
            await session.send(ProtocolError(code=ProtocolErrorCode.UNKNOWN_LEASE, message=f"Result for unknown job {frame.job_id} ignored"))
            return
        except IdempotencyKeyMismatch as error:
            await session.send(ProtocolError(code=ProtocolErrorCode.MALFORMED_FRAME, message=f"Result ignored: {error}"))
            return
        session.forget(frame.lease_id)
        if report.status == ResultStatus.STALE:
            logger.info("Late result of job %s from worker node %s ignored: %s", frame.job_id, session.worker_node_id, NOT_CURRENT)
        if report.job.state.is_terminal:
            self._backoff.job_ended(frame.job_id)
        self._activity.changed(frame.job_id)
        self._on_change()

    async def status(self, session: WorkerNodeSession, frame: JobStatus) -> None:
        if session.owns(frame.lease_id, frame.job_id):
            self._activity.status(frame)

    async def logs(self, session: WorkerNodeSession, frame: LogLines) -> None:
        if session.owns(frame.lease_id, frame.job_id):
            self._activity.logs(frame)

    # Connection events

    async def reconcile(self, session: WorkerNodeSession, reported_lease_ids: List[str]) -> List[ProtocolFrame]:
        """After the worker node's Hello: its reported running leases against the store's (lease_reconciliation.py).

        Returns the frames for the worker node (LeaseRenewed for kept leases, Cancel for the others),
        which the control plane sends right after Welcome.
        """
        active = await self._store(self._jobs.active_leases, session.worker_node_id)
        plan = reconcile_leases(reported_lease_ids, active)
        frames: List[ProtocolFrame] = []
        for lease, step in [(lease, self._jobs.renew) for lease in plan.keep] + [(lease, self._jobs.accept) for lease in plan.accept]:
            current = await self._store(step, lease.lease_id, self._timing.lease_timeout_s)
            if current is None:  # expired since the store listed it
                frames.append(Cancel(lease_id=lease.lease_id, job_id=lease.job.job_id, reason=NOT_CURRENT))
            else:
                session.holds(current)
                frames.append(LeaseRenewed(lease_id=current.lease_id, expires_at=current.expires_at))
            self._activity.changed(lease.job.job_id)
        for lease in plan.withdraw:
            await self._store(self._jobs.reject, lease.lease_id, "offer lost when the worker node reconnected")
            self._activity.changed(lease.job.job_id)
        for lease in plan.fail:
            await self._store(self._jobs.report_result, _lost_job(lease))
            self._activity.changed(lease.job.job_id)
        frames.extend(Cancel(lease_id=lease_id, job_id="", reason=NOT_CURRENT) for lease_id in plan.cancel)
        if plan.withdraw or plan.fail:
            logger.info("Worker node %s reconnected: %d offers withdrawn, %d jobs it no longer runs requeued", session.worker_node_id, len(plan.withdraw), len(plan.fail))
            self._on_change()
        return frames

    async def withdraw_offers(self, session: WorkerNodeSession) -> None:
        """The worker node's connection closed: its unaccepted offers return to the queue without using an attempt.

        Accepted leases stay: the worker node may reconnect and go on; otherwise they expire.
        """
        pending = sorted(session.pending_offers)
        for lease_id in pending:
            job_id = session.job_of(lease_id)
            session.forget(lease_id)
            await self._store(self._jobs.reject, lease_id, "the worker node disconnected before accepting")
            self._activity.changed(job_id)
        if pending:
            self._on_change()

    # Timers

    async def sweep_expired(self) -> List[ExpiredLease]:
        """Requeues (or fails) every expired lease and tells a connected owner to stop the job."""
        expired = await self._store(self._jobs.expire_leases)
        for lease in expired:
            logger.warning("Lease %s of job %s on worker node %s expired; job now %s", lease.lease_id, lease.job.job_id, lease.worker_node_id, lease.job.state.value)
            if lease.job.state.is_terminal:
                self._backoff.job_ended(lease.job.job_id)
            self._activity.changed(lease.job.job_id)
            session = self._registry.session(lease.worker_node_id)
            if session is not None and session.owns(lease.lease_id):
                await self._cancel(session, lease.lease_id, "the lease expired")
        if expired:
            self._on_change()
        return expired

    # Answers

    async def _confirm(self, session: WorkerNodeSession, lease_id: str, lease) -> None:
        if lease is None:
            await self._cancel(session, lease_id, NOT_CURRENT)
            return
        session.holds(lease)
        await session.send(LeaseRenewed(lease_id=lease_id, expires_at=lease.expires_at))

    async def _cancel(self, session: WorkerNodeSession, lease_id: str, reason: str) -> None:
        job_id = session.job_of(lease_id)
        session.forget(lease_id)
        await session.send(Cancel(lease_id=lease_id, job_id=job_id, reason=reason))


def _lost_job(lease: Lease) -> JobResult:
    """The failed attempt the control node reports for a running job its worker node no longer has."""
    return JobResult(
        lease_id=lease.lease_id,
        job_id=lease.job.job_id,
        idempotency_key=lease.job.idempotency_key,
        outcome=JobOutcome.FAILED,
        error="the worker node reconnected without this job",
        retryable=True,
    )
