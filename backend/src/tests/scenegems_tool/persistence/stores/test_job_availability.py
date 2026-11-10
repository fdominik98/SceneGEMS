"""Job availability: retry backoff, the claim's available_at filter, and holds.

Each test runs on the in-memory job store the control node's tests use (default run) and on
Postgres (`-m postgres`), so the two stay consistent.
"""

from datetime import timedelta

import pytest

from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobState, JobType
from scenegems_tool.cluster.protocol.messages import JobResult
from scenegems_tool.persistence.database import transaction
from scenegems_tool.persistence.schema import HELD_UNTIL, JobEventKind
from scenegems_tool.persistence.stores import JobStore, WorkerNodeStore
from tests.scenegems_tool.cluster.control_node.fake_stores import InMemoryJobStore, InMemoryWorkerNodeStore
from tests.scenegems_tool.persistence.stores.builders import START, make_hello, make_submission

SCENE = JobType.SCENE_GENERATION
LEASE_S = 30.0
BASE_S, CAP_S = 5.0, 40.0


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.postgres)])
def job_stores(request, clock):
    if request.param == "memory":
        worker_nodes = InMemoryWorkerNodeStore(clock)
        jobs = InMemoryJobStore(worker_nodes, clock, retry_backoff_base_s=BASE_S, retry_backoff_cap_s=CAP_S)
    else:
        session_factory = request.getfixturevalue("session_factory")
        worker_nodes = WorkerNodeStore(session_factory, clock)
        jobs = JobStore(session_factory, clock, retry_backoff_base_s=BASE_S, retry_backoff_cap_s=CAP_S)
    worker_nodes.register(make_hello("worker-node-a", slots={SCENE: 4}))
    return worker_nodes, jobs


@pytest.fixture
def jobs(job_stores):
    return job_stores[1]


def _failure(lease, retryable=True) -> JobResult:
    return JobResult(lease_id=lease.lease_id, job_id=lease.job.job_id, idempotency_key=lease.job.idempotency_key, outcome=JobOutcome.FAILED, result={}, error="crashed", retryable=retryable)


def _claim(jobs):
    return jobs.claim_next("worker-node-a", LEASE_S)


def test_a_submitted_job_is_available_at_once(jobs):
    job = jobs.submit(make_submission()).job
    assert job.available_at == START
    assert _claim(jobs).job.job_id == job.job_id


def test_retryable_failures_back_off_exponentially_up_to_the_cap(jobs, clock):
    job = jobs.submit(make_submission(max_attempts=10)).job
    waits = []
    for _ in range(5):
        lease = _claim(jobs)
        assert lease is not None and lease.job.job_id == job.job_id
        failed = jobs.report_result(_failure(lease)).job
        assert failed.state == JobState.QUEUED
        wait = (failed.available_at - clock.now).total_seconds()
        waits.append(wait)
        # not claimed a moment before the backoff ends, claimed when it ends
        clock.advance(wait - 0.001)
        assert _claim(jobs) is None
        clock.advance(0.001)
    assert waits == [5.0, 10.0, 20.0, 40.0, 40.0]


@pytest.mark.postgres
def test_the_backoff_is_in_the_failure_event(job_store, worker_node_store):
    worker_node_store.register(make_hello("worker-node-a", slots={SCENE: 1}))
    job_store.submit(make_submission())
    failed = job_store.report_result(_failure(_claim(job_store))).job
    event = job_store.events(failed.job_id)[-1]
    assert event.kind == JobEventKind.ATTEMPT_FAILED
    assert event.detail["available_at"] == (START + timedelta(seconds=job_store.retry_backoff_base_s)).isoformat()


def test_a_job_in_backoff_does_not_block_the_jobs_behind_it(jobs, clock):
    first = jobs.submit(make_submission(priority=5)).job
    jobs.report_result(_failure(_claim(jobs)))
    second = jobs.submit(make_submission(priority=0)).job
    assert _claim(jobs).job.job_id == second.job_id
    clock.advance(BASE_S)
    assert _claim(jobs).job.job_id == first.job_id


def test_a_permanent_failure_and_an_expiry_need_no_backoff(jobs, clock):
    permanent = jobs.submit(make_submission()).job
    assert jobs.report_result(_failure(_claim(jobs), retryable=False)).job.state == JobState.FAILED
    expiring = jobs.submit(make_submission()).job
    assert _claim(jobs).job.job_id == expiring.job_id
    clock.advance(LEASE_S)
    (expired,) = jobs.expire_leases()
    assert expired.job.state == JobState.QUEUED and expired.job.available_at <= clock.now
    assert _claim(jobs).job.job_id == expiring.job_id
    assert jobs.get(permanent.job_id).available_at == START


def test_hold_and_release_queued_jobs(jobs, clock):
    held = [jobs.submit(make_submission(idempotency_key=f"held-{index}")).job.job_id for index in range(3)]
    free = jobs.submit(make_submission(idempotency_key="free")).job.job_id
    assert jobs.hold_jobs(held + ["unknown-job"]) == sorted(held)
    assert all(jobs.get(job_id).available_at == HELD_UNTIL for job_id in held)
    assert jobs.hold_jobs(held) == []  # already held
    assert _claim(jobs).job.job_id == free
    clock.advance(10_000)
    assert _claim(jobs) is None
    assert jobs.release_held_jobs(held) == sorted(held)
    assert all(jobs.get(job_id).available_at == clock.now for job_id in held)
    assert jobs.release_held_jobs(held) == []
    assert sorted(_claim(jobs).job.job_id for _ in range(3)) == sorted(held)


def test_a_held_running_job_runs_on_and_stays_held_after_a_retryable_failure(jobs, clock):
    job = jobs.submit(make_submission()).job
    lease = _claim(jobs)
    jobs.accept(lease.lease_id, LEASE_S)
    assert jobs.hold_jobs([job.job_id]) == [job.job_id]
    assert jobs.renew(lease.lease_id, LEASE_S) is not None
    failed = jobs.report_result(_failure(lease)).job
    assert (failed.state, failed.available_at) == (JobState.QUEUED, HELD_UNTIL)
    clock.advance(BASE_S)
    assert _claim(jobs) is None
    jobs.release_held_jobs([job.job_id])
    assert _claim(jobs).job.job_id == job.job_id


def test_a_held_leased_job_stays_held_when_its_lease_expires(jobs, clock):
    job = jobs.submit(make_submission()).job
    _claim(jobs)
    jobs.hold_jobs([job.job_id])
    clock.advance(LEASE_S)
    (expired,) = jobs.expire_leases()
    assert expired.job.available_at == HELD_UNTIL
    assert _claim(jobs) is None


def test_finished_jobs_are_neither_held_nor_released(jobs):
    job = jobs.submit(make_submission()).job
    jobs.cancel(job.job_id, "test")
    assert jobs.hold_jobs([job.job_id]) == []
    assert jobs.get(job.job_id).available_at == START


@pytest.mark.postgres
def test_a_hold_in_the_callers_transaction_rolls_back_with_it(session_factory, clock):
    jobs = JobStore(session_factory, clock)
    job = jobs.submit(make_submission()).job

    class Rollback(Exception):
        pass

    with pytest.raises(Rollback):
        with transaction(session_factory) as session:
            assert jobs.hold_jobs([job.job_id], session=session) == [job.job_id]
            raise Rollback()
    assert jobs.get(job.job_id).available_at == START
    with transaction(session_factory) as session:
        jobs.hold_jobs([job.job_id], session=session)
    assert jobs.get(job.job_id).available_at == HELD_UNTIL


def test_the_backoff_needs_non_negative_settings():
    with pytest.raises(ValueError):
        JobStore(None, retry_backoff_base_s=-1.0)
    with pytest.raises(ValueError):
        JobStore(None, retry_backoff_cap_s=-1.0)
