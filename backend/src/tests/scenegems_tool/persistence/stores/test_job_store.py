from datetime import timedelta

import pytest

from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobRequirements, JobState, JobType
from scenegems_tool.cluster.protocol.messages import JobResult
from scenegems_tool.persistence.schema import JobEventKind, WorkerNodeStatus
from scenegems_tool.persistence.stores import IdempotencyKeyMismatch, ResultStatus, UnknownJob, UnknownWorkerNode
from tests.scenegems_tool.persistence.stores.builders import START, make_hello, make_resources, make_submission

pytestmark = pytest.mark.postgres

SCENE = JobType.SCENE_GENERATION
TRAJECTORY = JobType.TRAJECTORY_GENERATION
KINEMATIC = JobType.SIMULATION
LEASE_S = 30.0


def _result(lease, outcome=JobOutcome.SUCCEEDED, result=None, error=None, retryable=False) -> JobResult:
    return JobResult(
        lease_id=lease.lease_id,
        job_id=lease.job.job_id,
        idempotency_key=lease.job.idempotency_key,
        outcome=outcome,
        result=result or {},
        error=error,
        retryable=retryable,
    )


def _event_kinds(job_store, job_id):
    return [event.kind for event in job_store.events(job_id)]


@pytest.fixture
def worker_node_a(worker_node_store):
    return worker_node_store.register(make_hello("worker-node-a", slots={SCENE: 2, KINEMATIC: 2}))


# Submission


def test_submit_queues_a_job(job_store):
    outcome = job_store.submit(make_submission(priority=3, payload={"seed": 7}))
    job = outcome.job
    assert outcome.created
    assert (job.state, job.attempt, job.failed_attempts, job.priority) == (JobState.QUEUED, 0, 0, 3)
    assert job.idempotency_key == job.job_id
    assert job.payload == {"seed": 7}
    assert job.submitted_at == START
    assert job_store.get(job.job_id) == job
    assert _event_kinds(job_store, job.job_id) == [JobEventKind.SUBMITTED]


def test_submission_with_a_known_key_returns_the_first_job(job_store, clock):
    first = job_store.submit(make_submission(idempotency_key="campaign-1/scene-1", payload={"seed": 1}))
    clock.advance(10)
    second = job_store.submit(make_submission(idempotency_key="campaign-1/scene-1", payload={"seed": 2}))
    assert not second.created
    assert second.job == first.job
    assert len(job_store.list_jobs()) == 1
    assert _event_kinds(job_store, first.job.job_id) == [JobEventKind.SUBMITTED]


def test_requirements_round_trip(job_store):
    requirements = JobRequirements(labels={"gpu": "yes"}, fingerprints={"scenegems-gazebo": "f9"}, min_memory_mb=4000, min_cpus=2.5)
    job = job_store.submit(make_submission(requirements=requirements)).job
    assert job_store.get(job.job_id).requirements == requirements


def test_allowed_worker_nodes_round_trip(job_store):
    assert job_store.submit(make_submission()).job.allowed_worker_nodes == ()
    job = job_store.submit(make_submission(allowed_worker_nodes=["worker-node-b", "worker-node-c"])).job
    assert job_store.get(job.job_id).allowed_worker_nodes == ("worker-node-b", "worker-node-c")


def test_unknown_job(job_store):
    assert job_store.get("missing") is None
    with pytest.raises(UnknownJob):
        job_store.cancel("missing", "test")


def test_list_jobs_by_state(job_store, worker_node_a):
    first = job_store.submit(make_submission()).job
    second = job_store.submit(make_submission()).job
    job_store.claim_next("worker-node-a", LEASE_S)
    assert [job.job_id for job in job_store.list_jobs()] == [first.job_id, second.job_id]
    assert [job.job_id for job in job_store.list_jobs(JobState.QUEUED)] == [second.job_id]


# Claim


def test_claim_leases_the_job_to_the_worker_node(job_store, worker_node_a, clock):
    job = job_store.submit(make_submission(payload={"seed": 3})).job
    lease = job_store.claim_next("worker-node-a", LEASE_S)
    assert (lease.worker_node_id, lease.state) == ("worker-node-a", JobState.LEASED)
    assert lease.expires_at == START + timedelta(seconds=LEASE_S)
    assert (lease.job.job_id, lease.job.attempt, lease.job.payload) == (job.job_id, 1, {"seed": 3})
    stored = job_store.get(job.job_id)
    assert (stored.state, stored.lease_id, stored.lease_owner) == (JobState.LEASED, lease.lease_id, "worker-node-a")
    leased_event = job_store.events(job.job_id)[-1]
    assert (leased_event.kind, leased_event.from_state, leased_event.to_state, leased_event.lease_id, leased_event.worker_node_id) == (
        JobEventKind.LEASED,
        JobState.QUEUED,
        JobState.LEASED,
        lease.lease_id,
        "worker-node-a",
    )


def test_claim_with_an_empty_queue(job_store, worker_node_a):
    assert job_store.claim_next("worker-node-a", LEASE_S) is None


def test_claim_for_an_unknown_worker_node(job_store):
    with pytest.raises(UnknownWorkerNode):
        job_store.claim_next("ghost", LEASE_S)


def test_claim_needs_a_positive_lease_duration(job_store, worker_node_a):
    with pytest.raises(ValueError):
        job_store.claim_next("worker-node-a", 0)


def test_claim_order_is_priority_then_submission(job_store, worker_node_store, clock):
    worker_node_store.register(make_hello("worker-node-a", slots={SCENE: 10}))
    old_low = job_store.submit(make_submission(priority=0)).job
    clock.advance(1)
    new_high = job_store.submit(make_submission(priority=5)).job
    clock.advance(1)
    newer_high = job_store.submit(make_submission(priority=5)).job
    # two more at the same instant and priority: submission order decides
    same_time_first = job_store.submit(make_submission(priority=0)).job
    same_time_second = job_store.submit(make_submission(priority=0)).job
    order = [job_store.claim_next("worker-node-a", LEASE_S).job.job_id for _ in range(5)]
    assert order == [new_high.job_id, newer_high.job_id, old_low.job_id, same_time_first.job_id, same_time_second.job_id]


def test_claim_matches_the_job_type(job_store, worker_node_store):
    worker_node_store.register(make_hello("worker-node-a", slots={SCENE: 1}))
    trajectory = job_store.submit(make_submission(job_type=TRAJECTORY)).job
    scene = job_store.submit(make_submission(job_type=SCENE)).job
    assert job_store.claim_next("worker-node-a", LEASE_S).job.job_id == scene.job_id
    assert job_store.get(trajectory.job_id).state == JobState.QUEUED


def test_claim_can_be_limited_to_job_types(job_store, worker_node_a):
    job_store.submit(make_submission(job_type=SCENE, priority=9))
    kinematic = job_store.submit(make_submission(job_type=KINEMATIC)).job
    assert job_store.claim_next("worker-node-a", LEASE_S, job_types=[KINEMATIC]).job.job_id == kinematic.job_id
    assert job_store.claim_next("worker-node-a", LEASE_S, job_types=[TRAJECTORY]) is None


def test_claim_skips_excluded_jobs(job_store, worker_node_a):
    first = job_store.submit(make_submission(priority=9)).job
    second = job_store.submit(make_submission()).job
    assert job_store.claim_next("worker-node-a", LEASE_S, exclude_job_ids=[first.job_id]).job.job_id == second.job_id
    assert job_store.claim_next("worker-node-a", LEASE_S, exclude_job_ids=[first.job_id]) is None
    assert job_store.claim_next("worker-node-a", LEASE_S).job.job_id == first.job_id


def test_claim_respects_slots_per_job_type(job_store, worker_node_store):
    worker_node_store.register(make_hello("worker-node-a", slots={SCENE: 2, KINEMATIC: 1}))
    for _ in range(3):
        job_store.submit(make_submission(job_type=SCENE))
    job_store.submit(make_submission(job_type=KINEMATIC))
    leases = [job_store.claim_next("worker-node-a", LEASE_S) for _ in range(4)]
    assert sorted(lease.job.job_type.value for lease in leases[:3]) == sorted([SCENE.value, SCENE.value, KINEMATIC.value])
    assert leases[3] is None
    # a finished job frees its slot
    scene_lease = next(lease for lease in leases[:3] if lease.job.job_type == SCENE)
    job_store.accept(scene_lease.lease_id, LEASE_S)
    job_store.report_result(_result(scene_lease))
    assert job_store.claim_next("worker-node-a", LEASE_S).job.job_type == SCENE


def test_claim_matches_labels(job_store, worker_node_store):
    worker_node_store.register(make_hello("plain", slots={SCENE: 5}))
    worker_node_store.register(make_hello("gpu", slots={SCENE: 5}, labels={"gpu": "yes", "site": "lab"}))
    job = job_store.submit(make_submission(requirements=JobRequirements(labels={"gpu": "yes"}))).job
    assert job_store.claim_next("plain", LEASE_S) is None
    assert job_store.claim_next("gpu", LEASE_S).job.job_id == job.job_id


def test_claim_matches_components(job_store, worker_node_store):
    gazebo = ["asv_system/replay", "control_layer/ardupilot", "simulation_layer/gazebo"]
    worker_node_store.register(make_hello("sitl", slots={SCENE: 5}, components=["asv_system/replay", "control_layer/ardupilot", "simulation_layer/ardupilot_sim"]))
    worker_node_store.register(make_hello("world", slots={SCENE: 5}, components=gazebo + ["scene_generation"]))
    job = job_store.submit(make_submission(requirements=JobRequirements(components=gazebo))).job
    assert job_store.get(job.job_id).requirements.components == gazebo
    assert job_store.claim_next("sitl", LEASE_S) is None
    assert job_store.claim_next("world", LEASE_S, components=["scene_generation"]) is None, "the scheduler passes the usable components only"
    lease = job_store.claim_next("world", LEASE_S)
    assert lease.job.job_id == job.job_id and lease.job.requirements.components == gazebo
    unrestricted = job_store.submit(make_submission()).job
    assert job_store.claim_next("sitl", LEASE_S).job.job_id == unrestricted.job_id, "a job of an earlier release needs no component"


def test_claim_matches_allowed_worker_nodes(job_store, worker_node_store):
    for worker_node_id in ("left-out", "chosen", "also-chosen"):
        worker_node_store.register(make_hello(worker_node_id, slots={SCENE: 5}))
    restricted = job_store.submit(make_submission(priority=5, allowed_worker_nodes=["chosen", "also-chosen"])).job
    anywhere = job_store.submit(make_submission(priority=1)).job
    assert job_store.claim_next("left-out", LEASE_S).job.job_id == anywhere.job_id
    assert job_store.claim_next("left-out", LEASE_S) is None
    lease = job_store.claim_next("also-chosen", LEASE_S)
    assert lease.job.job_id == restricted.job_id
    assert lease.job.requirements == JobRequirements()  # the offer does not carry the allowed worker nodes


def test_claim_matches_fingerprints(job_store, worker_node_store):
    worker_node_store.register(make_hello("outdated", slots={SCENE: 5}, fingerprints={"scenegems-scene-generation": "old"}))
    worker_node_store.register(make_hello("missing", slots={SCENE: 5}))
    worker_node_store.register(make_hello("current", slots={SCENE: 5}, fingerprints={"scenegems-scene-generation": "new", "other": "x"}))
    job = job_store.submit(make_submission(requirements=JobRequirements(fingerprints={"scenegems-scene-generation": "new"}))).job
    assert job_store.claim_next("outdated", LEASE_S) is None
    assert job_store.claim_next("missing", LEASE_S) is None
    assert job_store.claim_next("current", LEASE_S).job.job_id == job.job_id


def test_a_job_queued_before_release_tags_still_finds_a_worker_node_by_repository(job_store, worker_node_store):
    # Jobs stored before release tags name their images :latest; worker nodes now report repositories
    worker_node_store.register(make_hello("outdated", slots={SCENE: 5}, fingerprints={"scenegems-scene-generation": "old"}))
    worker_node_store.register(make_hello("current", slots={SCENE: 5}, fingerprints={"scenegems-scene-generation": "new"}))
    job = job_store.submit(make_submission(requirements=JobRequirements(fingerprints={"scenegems-scene-generation:latest": "new"}))).job
    assert job_store.claim_next("outdated", LEASE_S) is None
    assert job_store.claim_next("current", LEASE_S).job.job_id == job.job_id


def test_claim_matches_resources(job_store, worker_node_store):
    worker_node_store.register(make_hello("small", slots={SCENE: 5}, resources=make_resources(cpus=2.0, free_memory_mb=1000)))
    worker_node_store.register(make_hello("few-cpus", slots={SCENE: 5}, resources=make_resources(cpus=2.0, free_memory_mb=8000)))
    worker_node_store.register(make_hello("big", slots={SCENE: 5}, resources=make_resources(cpus=16.0, free_memory_mb=8000)))
    job = job_store.submit(make_submission(requirements=JobRequirements(min_memory_mb=4000, min_cpus=4.0))).job
    assert job_store.claim_next("small", LEASE_S) is None
    assert job_store.claim_next("few-cpus", LEASE_S) is None
    assert job_store.claim_next("big", LEASE_S).job.job_id == job.job_id


@pytest.mark.parametrize("status", [WorkerNodeStatus.DRAINING, WorkerNodeStatus.OFFLINE])
def test_claim_skips_worker_nodes_that_are_not_online(job_store, worker_node_store, worker_node_a, status):
    job_store.submit(make_submission())
    worker_node_store.set_status("worker-node-a", status)
    assert job_store.claim_next("worker-node-a", LEASE_S) is None


# Accept, renew, reject, release


def test_accept_starts_the_job(job_store, worker_node_a, clock):
    job_store.submit(make_submission())
    lease = job_store.claim_next("worker-node-a", LEASE_S)
    clock.advance(2)
    accepted = job_store.accept(lease.lease_id, 60)
    assert accepted.state == JobState.RUNNING
    assert accepted.expires_at == clock.now + timedelta(seconds=60)
    assert job_store.get(lease.job.job_id).started_at == clock.now
    clock.advance(1)
    assert job_store.accept(lease.lease_id, 60) == accepted  # accepting again changes nothing


def test_accept_after_the_offer_expired(job_store, worker_node_a, clock):
    job_store.submit(make_submission())
    lease = job_store.claim_next("worker-node-a", LEASE_S)
    clock.advance(LEASE_S)
    assert job_store.accept(lease.lease_id, 60) is None
    assert job_store.accept("unknown-lease", 60) is None


def test_renew_extends_a_running_lease(job_store, worker_node_a, clock):
    job_store.submit(make_submission())
    lease = job_store.claim_next("worker-node-a", LEASE_S)
    assert job_store.renew(lease.lease_id, LEASE_S) is None  # not accepted yet
    job_store.accept(lease.lease_id, LEASE_S)
    clock.advance(LEASE_S - 1)
    renewed = job_store.renew(lease.lease_id, LEASE_S)
    assert renewed.expires_at == clock.now + timedelta(seconds=LEASE_S)
    clock.advance(LEASE_S)
    assert job_store.renew(lease.lease_id, LEASE_S) is None  # expired, even before the sweep


def test_reject_requeues_without_a_failed_attempt(job_store, worker_node_a):
    job = job_store.submit(make_submission(max_attempts=1)).job
    lease = job_store.claim_next("worker-node-a", LEASE_S)
    rejected = job_store.reject(lease.lease_id, "no free slot")
    assert (rejected.state, rejected.attempt, rejected.failed_attempts) == (JobState.QUEUED, 1, 0)
    assert rejected.lease_expires_at is None
    next_lease = job_store.claim_next("worker-node-a", LEASE_S)
    assert (next_lease.job.job_id, next_lease.job.attempt) == (job.job_id, 2)
    assert next_lease.lease_id != lease.lease_id
    assert job_store.reject(lease.lease_id, "again") is None  # superseded
    rejected_event = job_store.events(job.job_id)[2]
    assert (rejected_event.kind, rejected_event.detail) == (JobEventKind.REJECTED, {"reason": "no free slot"})


def test_recent_rejections_are_those_of_unfinished_jobs(job_store, worker_node_a, clock):
    waiting = job_store.submit(make_submission()).job
    job_store.reject(job_store.claim_next("worker-node-a", LEASE_S).lease_id, "busy")
    first_reject = clock.now
    clock.advance(60)
    job_store.reject(job_store.claim_next("worker-node-a", LEASE_S).lease_id, "still busy")
    ended = job_store.submit(make_submission(idempotency_key="ended")).job
    job_store.reject(job_store.claim_next("worker-node-a", LEASE_S, exclude_job_ids=[waiting.job_id]).lease_id, "busy")
    job_store.cancel(ended.job_id, "not needed")
    assert [(event.job_id, event.worker_node_id, event.at) for event in job_store.recent_rejections(first_reject)] == [
        (waiting.job_id, "worker-node-a", first_reject),
        (waiting.job_id, "worker-node-a", clock.now),
    ]
    assert [event.at for event in job_store.recent_rejections(first_reject + timedelta(seconds=1))] == [clock.now]


def test_reject_needs_an_unaccepted_offer(job_store, worker_node_a):
    job_store.submit(make_submission())
    lease = job_store.claim_next("worker-node-a", LEASE_S)
    job_store.accept(lease.lease_id, LEASE_S)
    assert job_store.reject(lease.lease_id, "too late") is None


def test_release_requeues_a_running_job_without_a_failed_attempt(job_store, worker_node_a):
    job = job_store.submit(make_submission(max_attempts=1)).job
    lease = job_store.claim_next("worker-node-a", LEASE_S)
    job_store.accept(lease.lease_id, LEASE_S)
    released = job_store.release(lease.lease_id, "draining")
    assert (released.state, released.failed_attempts) == (JobState.QUEUED, 0)
    assert job_store.release(lease.lease_id, "again") is None
    assert _event_kinds(job_store, job.job_id) == [JobEventKind.SUBMITTED, JobEventKind.LEASED, JobEventKind.ACCEPTED, JobEventKind.RELEASED]


# Results


def test_success_is_stored(job_store, worker_node_a, clock):
    job = job_store.submit(make_submission()).job
    lease = job_store.claim_next("worker-node-a", LEASE_S)
    job_store.accept(lease.lease_id, LEASE_S)
    clock.advance(5)
    report = job_store.report_result(_result(lease, result={"scenes": 12}))
    assert report.status == ResultStatus.STORED
    finished = report.job
    assert (finished.state, finished.result, finished.result_attempt, finished.finished_at) == (JobState.SUCCEEDED, {"scenes": 12}, 1, clock.now)
    assert finished.lease_expires_at is None
    assert job_store.active_leases() == []
    assert _event_kinds(job_store, job.job_id) == [JobEventKind.SUBMITTED, JobEventKind.LEASED, JobEventKind.ACCEPTED, JobEventKind.SUCCEEDED]


def test_result_reported_twice_is_stored_once(job_store, worker_node_a, clock):
    job = job_store.submit(make_submission()).job
    lease = job_store.claim_next("worker-node-a", LEASE_S)
    job_store.accept(lease.lease_id, LEASE_S)
    first = job_store.report_result(_result(lease, result={"scenes": 12}))
    clock.advance(1)
    second = job_store.report_result(_result(lease, result={"scenes": 99}))
    assert second.status == ResultStatus.DUPLICATE
    assert second.job == first.job
    assert job_store.get(job.job_id).result == {"scenes": 12}
    assert _event_kinds(job_store, job.job_id).count(JobEventKind.SUCCEEDED) == 1


def test_result_of_an_unaccepted_offer_is_stored(job_store, worker_node_a):
    # a worker node may finish before its accept arrives; the lease is still current
    job_store.submit(make_submission())
    lease = job_store.claim_next("worker-node-a", LEASE_S)
    assert job_store.report_result(_result(lease)).status == ResultStatus.STORED


def test_result_after_the_lease_expired_is_stale(job_store, worker_node_a, clock):
    job = job_store.submit(make_submission()).job
    lease = job_store.claim_next("worker-node-a", LEASE_S)
    job_store.accept(lease.lease_id, LEASE_S)
    clock.advance(LEASE_S)
    report = job_store.report_result(_result(lease))
    assert report.status == ResultStatus.STALE
    assert report.job.state == JobState.RUNNING  # unchanged until the sweep
    assert job_store.get(job.job_id).result is None


def test_result_of_a_superseded_lease_is_stale(job_store, worker_node_a, clock):
    job_store.submit(make_submission())
    old_lease = job_store.claim_next("worker-node-a", LEASE_S)
    clock.advance(LEASE_S)
    job_store.expire_leases()
    new_lease = job_store.claim_next("worker-node-a", LEASE_S)
    assert job_store.report_result(_result(old_lease)).status == ResultStatus.STALE
    assert job_store.report_result(_result(new_lease)).status == ResultStatus.STORED
    assert job_store.get(new_lease.job.job_id).result_attempt == 2


def test_result_with_another_idempotency_key_is_refused(job_store, worker_node_a):
    job_store.submit(make_submission(idempotency_key="key-1"))
    lease = job_store.claim_next("worker-node-a", LEASE_S)
    report = _result(lease).model_copy(update={"idempotency_key": "key-2"})
    with pytest.raises(IdempotencyKeyMismatch):
        job_store.report_result(report)


def test_result_for_an_unknown_job(job_store, worker_node_a):
    job_store.submit(make_submission())
    lease = job_store.claim_next("worker-node-a", LEASE_S)
    with pytest.raises(UnknownJob):
        job_store.report_result(_result(lease).model_copy(update={"job_id": "missing"}))


def test_retryable_failures_requeue_until_the_retry_limit(job_store, worker_node_a, clock):
    job = job_store.submit(make_submission(max_attempts=2)).job
    first = job_store.claim_next("worker-node-a", LEASE_S)
    report = job_store.report_result(_result(first, JobOutcome.FAILED, error="simulator crashed", retryable=True))
    assert (report.status, report.job.state, report.job.failed_attempts, report.job.error) == (ResultStatus.STORED, JobState.QUEUED, 1, "simulator crashed")
    assert report.job.finished_at is None
    # the same failure reported again counts once
    assert job_store.report_result(_result(first, JobOutcome.FAILED, error="simulator crashed", retryable=True)).status == ResultStatus.DUPLICATE
    assert job_store.get(job.job_id).failed_attempts == 1
    assert job_store.claim_next("worker-node-a", LEASE_S) is None  # in its retry backoff
    clock.advance(job_store.retry_backoff_base_s)
    second = job_store.claim_next("worker-node-a", LEASE_S)
    assert second.job.attempt == 2
    final = job_store.report_result(_result(second, JobOutcome.FAILED, error="crashed again", retryable=True)).job
    assert (final.state, final.failed_attempts, final.error) == (JobState.FAILED, 2, "crashed again")
    assert job_store.claim_next("worker-node-a", LEASE_S) is None
    assert _event_kinds(job_store, job.job_id) == [
        JobEventKind.SUBMITTED,
        JobEventKind.LEASED,
        JobEventKind.ATTEMPT_FAILED,
        JobEventKind.LEASED,
        JobEventKind.FAILED,
    ]


def test_non_retryable_failure_fails_the_job(job_store, worker_node_a):
    job_store.submit(make_submission(max_attempts=3))
    lease = job_store.claim_next("worker-node-a", LEASE_S)
    job = job_store.report_result(_result(lease, JobOutcome.FAILED, error="invalid payload")).job
    assert (job.state, job.failed_attempts) == (JobState.FAILED, 1)


# Cancel


def test_cancel_a_queued_job(job_store):
    job = job_store.submit(make_submission()).job
    outcome = job_store.cancel(job.job_id, "operator")
    assert outcome.cancelled
    assert (outcome.job.state, outcome.lease_id, outcome.worker_node_id) == (JobState.CANCELLED, None, None)


def test_cancel_a_running_job_names_its_lease(job_store, worker_node_a):
    job = job_store.submit(make_submission()).job
    lease = job_store.claim_next("worker-node-a", LEASE_S)
    job_store.accept(lease.lease_id, LEASE_S)
    outcome = job_store.cancel(job.job_id, "operator")
    assert (outcome.cancelled, outcome.lease_id, outcome.worker_node_id) == (True, lease.lease_id, "worker-node-a")
    assert job_store.active_leases("worker-node-a") == []
    assert job_store.report_result(_result(lease)).status == ResultStatus.STALE
    assert job_store.get(job.job_id).state == JobState.CANCELLED


def test_cancel_a_finished_job_changes_nothing(job_store, worker_node_a):
    job = job_store.submit(make_submission()).job
    lease = job_store.claim_next("worker-node-a", LEASE_S)
    job_store.report_result(_result(lease))
    outcome = job_store.cancel(job.job_id, "operator")
    assert not outcome.cancelled
    assert outcome.job.state == JobState.SUCCEEDED


# Expiry


def test_expired_lease_requeues_with_the_next_attempt(job_store, worker_node_a, clock):
    job = job_store.submit(make_submission(max_attempts=3)).job
    lease = job_store.claim_next("worker-node-a", LEASE_S)
    job_store.accept(lease.lease_id, LEASE_S)
    clock.advance(LEASE_S - 1)
    assert job_store.expire_leases() == []
    clock.advance(1)
    (expired,) = job_store.expire_leases()
    assert (expired.lease_id, expired.worker_node_id) == (lease.lease_id, "worker-node-a")
    assert (expired.job.state, expired.job.failed_attempts, expired.job.lease_expires_at) == (JobState.QUEUED, 1, None)
    assert job_store.expire_leases() == []
    retry = job_store.claim_next("worker-node-a", LEASE_S)
    assert (retry.job.job_id, retry.job.attempt) == (job.job_id, 2)
    expired_event = job_store.events(job.job_id)[3]
    assert (expired_event.kind, expired_event.from_state, expired_event.to_state) == (JobEventKind.EXPIRED, JobState.RUNNING, JobState.QUEUED)


def test_unaccepted_offer_expires_too(job_store, worker_node_a, clock):
    job_store.submit(make_submission())
    job_store.claim_next("worker-node-a", LEASE_S)
    clock.advance(LEASE_S)
    (expired,) = job_store.expire_leases()
    assert expired.job.state == JobState.QUEUED


def test_expiry_fails_the_job_at_the_retry_limit(job_store, worker_node_a, clock):
    job = job_store.submit(make_submission(max_attempts=2)).job
    for attempt in (1, 2):
        lease = job_store.claim_next("worker-node-a", LEASE_S)
        assert lease.job.attempt == attempt
        clock.advance(LEASE_S)
        (expired,) = job_store.expire_leases()
    assert (expired.job.state, expired.job.failed_attempts, expired.job.finished_at) == (JobState.FAILED, 2, clock.now)
    assert expired.job.error == "lease expired on attempt 2, no attempts left"
    assert job_store.claim_next("worker-node-a", LEASE_S) is None
    assert job_store.get(job.job_id).state == JobState.FAILED


def test_released_leases_do_not_use_up_attempts(job_store, worker_node_a, clock):
    job = job_store.submit(make_submission(max_attempts=1)).job
    for _ in range(3):
        lease = job_store.claim_next("worker-node-a", LEASE_S)
        job_store.release(lease.lease_id, "draining")
    lease = job_store.claim_next("worker-node-a", LEASE_S)
    clock.advance(LEASE_S)
    (expired,) = job_store.expire_leases()
    assert (expired.job.attempt, expired.job.failed_attempts, expired.job.state) == (4, 1, JobState.FAILED)
    assert job_store.get(job.job_id).state == JobState.FAILED


def test_expire_leases_with_a_limit(job_store, worker_node_store, clock):
    worker_node_store.register(make_hello("worker-node-a", slots={SCENE: 5}))
    for _ in range(3):
        job_store.submit(make_submission())
        job_store.claim_next("worker-node-a", LEASE_S)
    clock.advance(LEASE_S)
    assert len(job_store.expire_leases(limit=2)) == 2
    assert len(job_store.expire_leases()) == 1


def test_active_leases_per_worker_node(job_store, worker_node_store):
    worker_node_store.register(make_hello("worker-node-a", slots={SCENE: 5}))
    worker_node_store.register(make_hello("worker-node-b", slots={SCENE: 5}))
    for _ in range(3):
        job_store.submit(make_submission())
    lease_a = job_store.claim_next("worker-node-a", LEASE_S)
    lease_b = job_store.claim_next("worker-node-b", LEASE_S)
    assert [lease.lease_id for lease in job_store.active_leases("worker-node-a")] == [lease_a.lease_id]
    assert {lease.lease_id for lease in job_store.active_leases()} == {lease_a.lease_id, lease_b.lease_id}
