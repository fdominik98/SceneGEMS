"""Concurrent claimers, sweepers and submitters against one database, in threads.

Every thread calls the store through its own sessions and connections, as the control node's
workers will; a barrier starts them together so their transactions overlap.
"""

import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List

import pytest
from sqlalchemy import func, select

from scenegems_tool.cluster.protocol.jobs import JobState, JobType
from scenegems_tool.persistence.database import transaction
from scenegems_tool.persistence.schema import JobEventKind, JobEventRow
from tests.scenegems_tool.persistence.stores.builders import make_hello, make_submission

pytestmark = pytest.mark.postgres

SCENE = JobType.SCENE_GENERATION
LEASE_S = 30.0


def _run_together(workers: int, work: Callable[[int], List]) -> List:
    barrier = threading.Barrier(workers)

    def start(index: int) -> List:
        barrier.wait()
        return work(index)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return [item for items in pool.map(start, range(workers)) for item in items]


def _count_events(session_factory, kind: JobEventKind) -> int:
    with transaction(session_factory) as session:
        return session.execute(select(func.count()).select_from(JobEventRow).where(JobEventRow.kind == kind)).scalar_one()


def test_concurrent_claimers_never_share_a_job(job_store, worker_node_store, session_factory):
    job_count, worker_node_count, workers = 300, 8, 24
    for index in range(worker_node_count):
        worker_node_store.register(make_hello(f"worker node-{index}", slots={SCENE: job_count}))
    for index in range(job_count):
        job_store.submit(make_submission(priority=index % 3))

    def claim_until_empty(worker: int) -> List:
        worker_node_id = f"worker node-{worker % worker_node_count}"
        leases = []
        while (lease := job_store.claim_next(worker_node_id, LEASE_S)) is not None:
            leases.append(lease)
        return leases

    leases = _run_together(workers, claim_until_empty)
    claimed = Counter(lease.job.job_id for lease in leases)
    assert len(leases) == job_count
    assert max(claimed.values()) == 1
    assert len({lease.lease_id for lease in leases}) == job_count
    assert job_store.list_jobs(JobState.QUEUED) == []
    assert _count_events(session_factory, JobEventKind.LEASED) == job_count
    # every job was leased once, to the worker node its lease names
    stored = {job.job_id: job for job in job_store.list_jobs(limit=job_count)}
    assert all(stored[lease.job.job_id].lease_owner == lease.worker_node_id and stored[lease.job.job_id].attempt == 1 for lease in leases)


def test_concurrent_claimers_for_one_worker_node_respect_its_slots(job_store, worker_node_store):
    workers, slots = 16, 3
    worker_node_store.register(make_hello("worker-node-a", slots={SCENE: slots}))
    for _ in range(workers):
        job_store.submit(make_submission())

    leases = _run_together(workers, lambda worker: [lease for lease in [job_store.claim_next("worker-node-a", LEASE_S)] if lease is not None])
    assert len(leases) == slots
    assert len(job_store.active_leases("worker-node-a")) == slots


def test_concurrent_sweepers_expire_each_lease_once(job_store, worker_node_store, clock):
    job_count, workers = 120, 8
    worker_node_store.register(make_hello("worker-node-a", slots={SCENE: job_count}))
    for _ in range(job_count):
        job_store.submit(make_submission(max_attempts=3))
        job_store.claim_next("worker-node-a", LEASE_S)
    clock.advance(LEASE_S)

    expired = _run_together(workers, lambda worker: job_store.expire_leases(limit=7) + job_store.expire_leases())
    assert len(expired) == job_count
    assert len({item.job.job_id for item in expired}) == job_count
    jobs = job_store.list_jobs(limit=job_count)
    assert all(job.state == JobState.QUEUED and job.failed_attempts == 1 for job in jobs)


def test_concurrent_submissions_with_one_key_create_one_job(job_store):
    workers = 16
    outcomes = _run_together(workers, lambda worker: [job_store.submit(make_submission(idempotency_key="campaign-1/scene-1", payload={"worker": worker}))])
    assert sum(outcome.created for outcome in outcomes) == 1
    assert len({outcome.job.job_id for outcome in outcomes}) == 1
    assert len(job_store.list_jobs()) == 1
