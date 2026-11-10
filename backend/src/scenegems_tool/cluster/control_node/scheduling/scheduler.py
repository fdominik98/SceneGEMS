"""The scheduler: offers queued jobs to connected worker nodes that can run them.

Each round asks the job store for the next job each eligible worker node may take and sends it
as a LeaseOffer. The store's claim matches the job type against the worker node's free slots, and
the job's labels, fingerprints and memory and CPU minimums against the worker node, all under
locks, so two offers never share a job or exceed a worker node's slots. The scheduler adds what
concerns the worker node as a whole (worker_node_eligibility.py), holds back jobs the worker node rejected
(reject_backoff.py), and goes round robin over the worker nodes, one offer each per pass, so
scarce work spreads over the cluster instead of filling the first worker node.

It runs when something may have freed or added work (a submission, a worker node joining, a
lease ending), and at least every ControlTiming.schedule_interval_s.
"""

import asyncio
import logging
from functools import partial
from typing import List, Optional

import anyio

from scenegems_tool.cluster.control_node.job_activity import JobActivity
from scenegems_tool.cluster.control_node.registry.worker_node_registry import WorkerNodeRegistry
from scenegems_tool.cluster.control_node.registry.worker_node_session import WorkerNodeSession
from scenegems_tool.cluster.control_node.scheduling.fingerprint_policy import ExpectedFingerprints
from scenegems_tool.cluster.control_node.scheduling.reject_backoff import RejectBackoff
from scenegems_tool.cluster.control_node.scheduling.worker_node_eligibility import ResourceGuard, ineligibility
from scenegems_tool.cluster.control_node.timing import ControlTiming
from scenegems_tool.cluster.protocol.messages import LeaseOffer
from scenegems_tool.persistence.stores import JobStore, Lease, UnknownWorkerNode

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(
        self,
        job_store: JobStore,
        registry: WorkerNodeRegistry,
        expected: ExpectedFingerprints,
        backoff: RejectBackoff,
        timing: ControlTiming,
        guard: ResourceGuard,
        activity: Optional[JobActivity] = None,
    ):
        self._jobs = job_store
        self._activity = activity  # hears each offer, as the job is now leased
        self._registry = registry
        self._expected = expected
        self._backoff = backoff
        self._timing = timing
        self._guard = guard
        self._wake = asyncio.Event()
        self._turn = 0

    def wake(self) -> None:
        self._wake.set()

    async def run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), self._timing.schedule_interval_s)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            try:
                await self.run_once()
            except Exception:
                logger.exception("Scheduling pass failed; retrying on the next one")

    async def run_once(self) -> int:
        """One scheduling pass; returns the number of offers sent."""
        offers = 0
        candidates = self._eligible_sessions()
        while candidates:
            next_pass: List[WorkerNodeSession] = []
            for session in candidates:
                lease = await self._claim(session)
                if lease is not None and await self._offer(session, lease):
                    offers += 1
                    next_pass.append(session)
            candidates = next_pass
        return offers

    def _eligible_sessions(self) -> List[WorkerNodeSession]:
        expected = self._expected.current()
        eligible = []
        for session in self._registry.connected():
            self._registry.refresh_out_of_date(session, expected)
            if ineligibility(session.record, session.usable_components, expected is not None, self._guard) is None:
                eligible.append(session)
        if eligible:
            self._turn = (self._turn + 1) % len(eligible)
            eligible = eligible[self._turn :] + eligible[: self._turn]
        return eligible

    async def _claim(self, session: WorkerNodeSession) -> Optional[Lease]:
        if session.closed:
            return None
        claim = partial(
            self._jobs.claim_next, session.worker_node_id, self._timing.offer_timeout_s, exclude_job_ids=self._backoff.held_jobs(session.worker_node_id), components=session.usable_components
        )
        try:
            return await anyio.to_thread.run_sync(claim)
        except UnknownWorkerNode:
            return None

    async def _offer(self, session: WorkerNodeSession, lease: Lease) -> bool:
        session.offered(lease)  # before sending, so an immediate accept finds it
        if await session.send(LeaseOffer(lease_id=lease.lease_id, job=lease.job, expires_at=lease.expires_at)):
            if self._activity is not None:
                self._activity.changed(lease.job.job_id)
            return True
        session.forget(lease.lease_id)
        await anyio.to_thread.run_sync(self._jobs.reject, lease.lease_id, "the offer could not be delivered")
        return False
