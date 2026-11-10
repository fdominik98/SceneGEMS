"""The control plane end to end with scripted worker nodes: who gets which job, lost worker nodes, rejects, reconnects.

Each test runs on the in-memory stores and, with `-m postgres`, on a real database.
"""

import asyncio
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from scenegems_tool.cluster.control_node.control_plane import InvalidPayload
from scenegems_tool.cluster.fingerprints.comparison import by_repository
from scenegems_tool.cluster.fingerprints.components import SCENARIO_EXECUTION_IMAGE
from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobRequirements, JobState, JobSubmission, JobType
from scenegems_tool.cluster.protocol.messages import Cancel, Drain, LeaseOffer, LeaseRelease, LeaseRenewed, ProtocolError, ProtocolErrorCode, Welcome
from scenegems_tool.persistence.schema import JobEventKind, WorkerNodeStatus
from scenegems_tool.persistence.stores import AssuranceStores
from tests.scenegems_tool.cluster.control_node.conftest import EXPECTED, KINEMATIC, SCENE
from tests.scenegems_tool.cluster.payloads import ardupilot_payload, valid_payload
from tests.scenegems_tool.cluster.stack_images import GAZEBO_IMAGE, SITL_IMAGE
from tests.scenegems_tool.persistence.stores.builders import make_resources
from utils.image_names import image_repository

SIMULATION = JobType.SIMULATION
KINEMATIC_WORKER_NODE = ("asv_software/replay", "control_layer/none", "simulation_layer/kinematic", "scene_generation")
SITL_WORKER_NODE = ("asv_software/replay", "control_layer/ardupilot", "simulation_layer/ardupilot_sim")
GAZEBO_WORKER_NODE = ("asv_software/replay", "control_layer/ardupilot", "simulation_layer/gazebo")


def _submit(on_loop, plane, job_type=SCENE, **fields):
    fields.setdefault("payload", valid_payload(job_type))
    return on_loop(plane.submit, JobSubmission(job_type=job_type, **fields)).job


def _offers(worker_node, count):
    return [worker_node.expect(LeaseOffer) for _ in range(count)]


# Competing worker nodes and lost worker nodes


def test_two_worker_nodes_compete_and_each_job_runs_once(make_worker_node, plane, stores, on_loop, schedule):
    a, b = make_worker_node("lab a", slots={SCENE: 2}), make_worker_node("lab b", slots={SCENE: 2})
    a.connect()
    b.connect()
    jobs = [_submit(on_loop, plane, payload=valid_payload(SCENE, seed=index)) for index in range(6)]

    assert schedule() == 4  # two slots each
    offers = {a.worker_node_id: _offers(a, 2), b.worker_node_id: _offers(b, 2)}
    assert len({offer.job.job_id for batch in offers.values() for offer in batch}) == 4
    assert schedule() == 0  # every slot is taken

    for worker_node in (a, b):
        for offer in offers[worker_node.worker_node_id]:
            worker_node.accept(offer)
            worker_node.succeed(offer)
    a.heartbeat()
    b.heartbeat()
    assert schedule() == 2
    rest = [(worker_node, offer) for worker_node in (a, b) for offer in _offers(worker_node, 1)]
    for worker_node, offer in rest:
        worker_node.accept(offer)
        worker_node.succeed(offer)
    a.heartbeat()
    b.heartbeat()
    on_loop(plane.leases.sweep_expired)

    finished = [stores.jobs.get(job.job_id) for job in jobs]
    assert all(job.state == JobState.SUCCEEDED and job.attempt == 1 for job in finished)
    assert sorted(job.lease_owner for job in finished) == sorted([a.worker_node_id] * 3 + [b.worker_node_id] * 3)
    for job in finished:
        assert [event.kind for event in stores.jobs.events(job.job_id)].count(JobEventKind.SUCCEEDED) == 1


def test_a_worker_node_lost_mid_lease_has_its_job_finished_elsewhere_and_stored_once(make_worker_node, plane, stores, on_loop, schedule, clock):
    lost, other = make_worker_node("lab lost", slots={SCENE: 1}), make_worker_node("lab other", slots={SCENE: 1})
    lost.connect()
    job = _submit(on_loop, plane)
    schedule()
    offer = lost.expect(LeaseOffer)
    lost.accept(offer)
    lost.close()  # the worker node dies while running the job: no renewals, no result
    other.connect()
    assert schedule() == 0  # the lease still holds

    for _ in range(6):  # 30 s pass; the other worker node keeps sending heartbeats
        clock.advance(5)
        other.heartbeat()
    on_loop(plane.registry.sweep_silent)
    expired = on_loop(plane.leases.sweep_expired)
    assert [lease.job.job_id for lease in expired] == [job.job_id]
    assert stores.worker_nodes.get(lost.worker_node_id).status == WorkerNodeStatus.OFFLINE
    schedule()
    second = other.expect(LeaseOffer)
    assert second.job.job_id == job.job_id and second.job.attempt == 2
    other.accept(second)
    other.succeed(second, {"done_by": other.worker_node_id})

    # The lost worker node comes back with its stale lease and its result: it is told to stop, and nothing is stored twice
    lost.connect(running_lease_ids=[offer.lease_id])
    cancel = lost.expect(Cancel)
    assert cancel.lease_id == offer.lease_id
    lost.send(lost.result(offer, JobOutcome.SUCCEEDED, {"done_by": lost.worker_node_id}))
    assert lost.expect(ProtocolError).code == ProtocolErrorCode.UNKNOWN_LEASE

    stored = stores.jobs.get(job.job_id)
    assert stored.state == JobState.SUCCEEDED and stored.result == {"done_by": other.worker_node_id} and stored.failed_attempts == 1
    kinds = [event.kind for event in stores.jobs.events(job.job_id)]
    assert kinds == [JobEventKind.SUBMITTED, JobEventKind.LEASED, JobEventKind.ACCEPTED, JobEventKind.EXPIRED, JobEventKind.LEASED, JobEventKind.ACCEPTED, JobEventKind.SUCCEEDED]


def test_expiry_at_the_retry_limit_fails_the_job(make_worker_node, plane, stores, on_loop, schedule, clock):
    worker_node = make_worker_node("lab 1", slots={SCENE: 1})
    worker_node.connect()
    job = _submit(on_loop, plane, max_attempts=2)
    for attempt in (1, 2):
        schedule()
        offer = worker_node.expect(LeaseOffer)
        assert offer.job.attempt == attempt
        worker_node.accept(offer)
        clock.advance(31)
        worker_node.heartbeat()
        on_loop(plane.leases.sweep_expired)
        assert worker_node.expect(Cancel).lease_id == offer.lease_id
    stored = stores.jobs.get(job.job_id)
    assert stored.state == JobState.FAILED and "no attempts left" in stored.error
    assert schedule() == 0


def test_an_unaccepted_offer_of_a_disconnected_worker_node_returns_to_the_queue_at_once(make_worker_node, plane, stores, on_loop, schedule):
    gone, other = make_worker_node("lab gone"), make_worker_node("lab other")
    gone.connect()
    job = _submit(on_loop, plane)
    schedule()
    gone.expect(LeaseOffer)
    gone.close()
    other.connect()
    other.heartbeat()
    schedule()
    offer = other.expect(LeaseOffer)
    assert offer.job.job_id == job.job_id
    stored = stores.jobs.get(job.job_id)
    assert stored.failed_attempts == 0 and stored.attempt == 2


# Matching


def test_jobs_go_only_to_worker_nodes_with_the_job_type_and_a_free_slot(make_worker_node, plane, on_loop, schedule):
    scene_worker_node, kinematic_worker_node = make_worker_node("scene", slots={SCENE: 1}), make_worker_node("kinematic", slots={KINEMATIC: 1})
    scene_worker_node.connect()
    kinematic_worker_node.connect()
    kinematic_job = _submit(on_loop, plane, job_type=KINEMATIC)
    scene_jobs = [_submit(on_loop, plane) for _ in range(2)]
    assert schedule() == 2
    assert kinematic_worker_node.expect(LeaseOffer).job.job_id == kinematic_job.job_id
    assert scene_worker_node.expect(LeaseOffer).job.job_id == scene_jobs[0].job_id
    assert schedule() == 0


def test_labels_must_match(make_worker_node, plane, on_loop, schedule):
    plain, gpu = make_worker_node("plain", slots={SCENE: 2}), make_worker_node("gpu", slots={SCENE: 2}, labels={"gpu": "yes"})
    plain.connect()
    gpu.connect()
    job = _submit(on_loop, plane, requirements=JobRequirements(labels={"gpu": "yes"}))
    assert schedule() == 1
    assert gpu.expect(LeaseOffer).job.job_id == job.job_id


def test_a_submission_needs_the_components_of_its_payload_and_their_images(plane, stores, on_loop):
    gazebo_job = _submit(on_loop, plane, job_type=SIMULATION, payload=ardupilot_payload("gazebo"))
    sitl_job = _submit(on_loop, plane, job_type=SIMULATION, payload=ardupilot_payload("ardupilot_sim"))
    usv_job = _submit(on_loop, plane, job_type=SIMULATION, payload=valid_payload(SIMULATION, mode="usv_navigation"))
    scene_job = _submit(on_loop, plane, requirements=JobRequirements(components=["gpu"]))
    assert stores.jobs.get(gazebo_job.job_id).requirements.components == list(GAZEBO_WORKER_NODE)
    assert stores.jobs.get(gazebo_job.job_id).requirements.fingerprints == by_repository({SCENARIO_EXECUTION_IMAGE: "fp-execution", SITL_IMAGE: "fp-sitl", GAZEBO_IMAGE: "fp-gazebo"})
    assert stores.jobs.get(sitl_job.job_id).requirements.fingerprints == by_repository({SCENARIO_EXECUTION_IMAGE: "fp-execution", SITL_IMAGE: "fp-sitl"})
    assert stores.jobs.get(usv_job.job_id).requirements.components == ["asv_software/replay", "asv_software/usv_navigation", "control_layer/none", "simulation_layer/kinematic"]
    assert stores.jobs.get(scene_job.job_id).requirements.components == ["scene_generation"], "the control node sets the components from the payload"


def test_a_job_goes_to_a_worker_node_with_its_components(make_worker_node, plane, on_loop, schedule):
    kinematic = make_worker_node("kinematic", slots={SIMULATION: 2, SCENE: 1}, components=KINEMATIC_WORKER_NODE)
    sitl = make_worker_node("sitl", slots={SIMULATION: 2}, components=SITL_WORKER_NODE)
    kinematic.connect()
    sitl.connect()
    gazebo_job = _submit(on_loop, plane, job_type=SIMULATION, payload=ardupilot_payload("gazebo"))
    sitl_job = _submit(on_loop, plane, job_type=SIMULATION, payload=ardupilot_payload("ardupilot_sim"))
    kinematic_job = _submit(on_loop, plane, job_type=SIMULATION, payload=valid_payload(SIMULATION))
    _submit(on_loop, plane, job_type=SIMULATION, payload=valid_payload(SIMULATION, mode="usv_navigation"))
    assert schedule() == 2, "neither worker node has the Gazebo layer or USV Navigation"
    assert kinematic.expect(LeaseOffer).job.job_id == kinematic_job.job_id
    assert sitl.expect(LeaseOffer).job.job_id == sitl_job.job_id
    gazebo = make_worker_node("gazebo", slots={SIMULATION: 1}, components=GAZEBO_WORKER_NODE)
    gazebo.connect()
    assert schedule() == 1
    assert gazebo.expect(LeaseOffer).job.job_id == gazebo_job.job_id


def test_a_stale_component_is_unusable_while_the_others_work(make_worker_node, plane, stores, on_loop, schedule):
    without_gazebo = {image: fingerprint for image, fingerprint in EXPECTED.items() if image != GAZEBO_IMAGE}
    worker_node = make_worker_node("sitl and gazebo", slots={SIMULATION: 2}, components=SITL_WORKER_NODE + ("simulation_layer/gazebo",), fingerprints=without_gazebo)
    worker_node.connect()
    gazebo_job = _submit(on_loop, plane, job_type=SIMULATION, payload=ardupilot_payload("gazebo"))
    sitl_job = _submit(on_loop, plane, job_type=SIMULATION, payload=ardupilot_payload("ardupilot_sim"))
    assert schedule() == 1
    assert worker_node.expect(LeaseOffer).job.job_id == sitl_job.job_id
    session = plane.registry.session(worker_node.worker_node_id)
    assert session.stale_components == {"simulation_layer/gazebo"} and [mismatch.image for mismatch in session.out_of_date] == [image_repository(GAZEBO_IMAGE)]
    assert stores.jobs.get(gazebo_job.job_id).state == JobState.QUEUED


def test_an_out_of_date_component_gets_no_jobs_and_is_reported(make_worker_node, plane, stores, on_loop, schedule):
    stale = dict(EXPECTED, **{SCENARIO_EXECUTION_IMAGE: "fp-older"})
    # The worker node offers scene generation, whose image matches, and kinematic simulation, whose runner image does not
    outdated = make_worker_node("outdated", slots={SCENE: 2, KINEMATIC: 1}, fingerprints=stale, components=KINEMATIC_WORKER_NODE)
    outdated.connect()
    simulation = _submit(on_loop, plane, job_type=KINEMATIC)
    scene = _submit(on_loop, plane)
    assert schedule() == 1
    assert outdated.expect(LeaseOffer).job.job_id == scene.job_id, "the scene generation component is up to date"
    session = plane.registry.session(outdated.worker_node_id)
    assert [(mismatch.image, mismatch.required, mismatch.actual) for mismatch in session.out_of_date] == [(image_repository(SCENARIO_EXECUTION_IMAGE), "fp-execution", "fp-older")]
    assert "simulation_layer/kinematic" in session.stale_components and "scene_generation" not in session.stale_components
    current = make_worker_node("current", slots={KINEMATIC: 1}, components=KINEMATIC_WORKER_NODE)
    current.connect()
    assert schedule() == 1
    assert current.expect(LeaseOffer).job.job_id == simulation.job_id


def test_a_worker_node_whose_every_component_is_stale_is_out_of_date(make_worker_node, plane, on_loop, schedule):
    from scenegems_tool.cluster.control_node.scheduling.worker_node_eligibility import Ineligibility, ResourceGuard, ineligibility

    worker_node = make_worker_node("stale", slots={SCENE: 1}, components=("scene_generation",), fingerprints={})
    worker_node.connect()
    _submit(on_loop, plane)
    assert schedule() == 0
    session = plane.registry.session(worker_node.worker_node_id)
    assert session.usable_components == frozenset()
    assert ineligibility(session.record, session.usable_components, True, ResourceGuard()) == Ineligibility.OUT_OF_DATE


def test_a_worker_node_without_a_required_image_is_out_of_date(make_worker_node, plane, on_loop, schedule):
    missing = make_worker_node("missing", slots={SCENE: 1}, fingerprints={})
    missing.connect()
    _submit(on_loop, plane)
    assert schedule() == 0
    assert plane.registry.session(missing.worker_node_id).out_of_date[0].missing


def test_the_resource_guard_holds_offers_until_the_worker_node_has_room(make_worker_node, plane, on_loop, schedule):
    worker_node = make_worker_node("busy", slots={SCENE: 2}, resources=make_resources(free_memory_mb=100))
    worker_node.connect()
    _submit(on_loop, plane)
    assert schedule() == 0
    worker_node.heartbeat(free_memory_mb=8000, load_average=3.0)
    assert schedule() == 0
    worker_node.heartbeat(free_memory_mb=8000, load_average=0.5)
    assert schedule() == 1
    worker_node.expect(LeaseOffer)


def test_a_job_minimum_above_the_worker_nodes_free_memory_waits(make_worker_node, plane, on_loop, schedule):
    worker_node = make_worker_node("small", slots={SCENE: 2}, resources=make_resources(free_memory_mb=2000))
    worker_node.connect()
    _submit(on_loop, plane, requirements=JobRequirements(min_memory_mb=4000))
    assert schedule() == 0


def test_higher_priority_first(make_worker_node, plane, on_loop, schedule):
    worker_node = make_worker_node("lab 1", slots={SCENE: 1})
    worker_node.connect()
    _submit(on_loop, plane)
    urgent = _submit(on_loop, plane, priority=5)
    schedule()
    assert worker_node.expect(LeaseOffer).job.job_id == urgent.job_id


def test_offers_spread_round_robin_over_the_worker_nodes(make_worker_node, plane, on_loop, schedule):
    worker_nodes = [make_worker_node(f"lab {index}", slots={SCENE: 4}) for index in range(3)]
    for worker_node in worker_nodes:
        worker_node.connect()
    for _ in range(3):
        _submit(on_loop, plane)
    assert schedule() == 3
    for worker_node in worker_nodes:
        worker_node.expect(LeaseOffer)


def test_a_draining_worker_node_gets_no_new_jobs_until_resumed(make_worker_node, plane, stores, on_loop, schedule):
    worker_node = make_worker_node("lab 1")
    worker_node.connect()
    on_loop(plane.drain, worker_node.worker_node_id, "maintenance")
    assert worker_node.expect(Drain).reason == "maintenance"
    _submit(on_loop, plane)
    worker_node.heartbeat()  # a heartbeat does not end a drain
    assert schedule() == 0
    assert stores.worker_nodes.get(worker_node.worker_node_id).status == WorkerNodeStatus.DRAINING
    on_loop(plane.resume, worker_node.worker_node_id)
    assert schedule() == 1
    worker_node.expect(LeaseOffer)


# Rejects


def test_a_rejected_job_is_held_back_from_that_worker_node_only(make_worker_node, plane, stores, on_loop, schedule, clock):
    picky, other = make_worker_node("picky", slots={SCENE: 1}), make_worker_node("other", slots={SCENE: 1})
    picky.connect()
    job = _submit(on_loop, plane)
    schedule()
    offer = picky.expect(LeaseOffer)
    picky.reject(offer, "not now")
    picky.heartbeat()
    assert schedule() == 0  # held back from picky, and nobody else is connected
    assert stores.jobs.get(job.job_id).failed_attempts == 0

    clock.advance(31)
    assert schedule() == 1  # after the first hold of 30 s
    second = picky.expect(LeaseOffer)
    picky.reject(second, "still not")
    picky.heartbeat()
    clock.advance(31)
    assert schedule() == 0  # the second hold is 60 s
    other.connect()
    assert schedule() == 1
    assert other.expect(LeaseOffer).job.job_id == job.job_id


def test_a_restarted_control_node_keeps_its_reject_holds(make_worker_node, plane, stores, on_loop, schedule):
    picky = make_worker_node("picky", slots={SCENE: 1})
    picky.connect()
    job = _submit(on_loop, plane)
    schedule()
    picky.reject(picky.expect(LeaseOffer), "not now")
    picky.sync()
    assert plane.backoff.held_jobs(picky.worker_node_id) == [job.job_id]
    plane.backoff._holds.clear()  # what a new control node process starts with
    on_loop(plane._restore_reject_holds)  # what ControlPlane.start does first
    assert plane.backoff.held_jobs(picky.worker_node_id) == [job.job_id]
    picky.heartbeat()
    assert schedule() == 0  # still held back from picky


def test_a_released_job_returns_without_using_an_attempt(make_worker_node, plane, stores, on_loop, schedule):
    worker_node = make_worker_node("lab 1", slots={SCENE: 1})
    worker_node.connect()
    job = _submit(on_loop, plane)
    schedule()
    offer = worker_node.expect(LeaseOffer)
    worker_node.accept(offer)
    worker_node.send(LeaseRelease(lease_id=offer.lease_id, reason="draining"))
    worker_node.heartbeat()
    assert stores.jobs.get(job.job_id).state == JobState.QUEUED and stores.jobs.get(job.job_id).failed_attempts == 0
    assert schedule() == 1


def test_a_retryable_failure_runs_again_and_a_permanent_one_fails(make_worker_node, plane, stores, on_loop, schedule, clock):
    worker_node = make_worker_node("lab 1", slots={SCENE: 1})
    worker_node.connect()
    job = _submit(on_loop, plane)
    schedule()
    offer = worker_node.expect(LeaseOffer)
    worker_node.accept(offer)
    worker_node.send(worker_node.result(offer, JobOutcome.FAILED, error="docker hiccup", retryable=True))
    worker_node.heartbeat()
    assert schedule() == 0  # in its retry backoff
    clock.advance(stores.jobs.retry_backoff_base_s)
    worker_node.heartbeat()
    assert schedule() == 1
    second = worker_node.expect(LeaseOffer)
    worker_node.accept(second)
    worker_node.send(worker_node.result(second, JobOutcome.FAILED, error="invalid payload"))
    worker_node.heartbeat()
    stored = stores.jobs.get(job.job_id)
    assert stored.state == JobState.FAILED and stored.error == "invalid payload" and stored.attempt == 2


# Reconnects


def test_a_reconnect_reconciles_the_reported_leases(make_worker_node, client, plane, stores, on_loop, schedule, clock):
    from tests.scenegems_tool.cluster.control_node.fake_worker_node import FakeWorkerNode

    worker_node = make_worker_node("lab 1", slots={SCENE: 4})
    worker_node.connect()
    jobs = [_submit(on_loop, plane, payload=valid_payload(SCENE, seed=index)) for index in range(4)]
    schedule()
    kept, unconfirmed, lost, forgotten = _offers(worker_node, 4)
    worker_node.accept(kept)
    worker_node.accept(lost)

    # The worker node's network flaps and it reconnects before the control node notices the old socket is dead. It still
    # runs `kept` and had accepted `unconfirmed` (that accept never arrived); its daemon restarted `lost`
    # away, and `forgotten` was never accepted. It also names a lease nobody knows.
    clock.advance(5)
    again = FakeWorkerNode(client, worker_node.hello_frame)
    again.connect(running_lease_ids=[kept.lease_id, unconfirmed.lease_id, "no-such-lease"])
    frames = [again.receive() for _ in range(3)]
    renewed = {frame.lease_id: frame for frame in frames if isinstance(frame, LeaseRenewed)}
    assert set(renewed) == {kept.lease_id, unconfirmed.lease_id}
    assert all(frame.expires_at == clock.now + timedelta(seconds=30) for frame in renewed.values())
    assert [(frame.lease_id, frame.job_id) for frame in frames if isinstance(frame, Cancel)] == [("no-such-lease", "")]
    assert worker_node.expect_close() == 4000

    states = {job.job_id: stores.jobs.get(job.job_id) for job in jobs}
    assert states[kept.job.job_id].state == JobState.RUNNING
    assert states[unconfirmed.job.job_id].state == JobState.RUNNING
    assert states[lost.job.job_id].state == JobState.QUEUED and states[lost.job.job_id].failed_attempts == 1
    assert states[forgotten.job.job_id].state == JobState.QUEUED and states[forgotten.job.job_id].failed_attempts == 0
    assert again.renew(unconfirmed.lease_id).lease_id == unconfirmed.lease_id
    again.close()


def test_a_newer_connection_replaces_the_older_one(make_worker_node, client, plane, stores, on_loop, schedule):
    from tests.scenegems_tool.cluster.control_node.fake_worker_node import FakeWorkerNode

    worker_node = make_worker_node("lab 1", slots={SCENE: 1})
    worker_node.connect()
    job = _submit(on_loop, plane)
    schedule()
    offer = worker_node.expect(LeaseOffer)
    worker_node.accept(offer)

    second = FakeWorkerNode(client, worker_node.hello_frame)
    assert isinstance(second.connect(running_lease_ids=[offer.lease_id]), Welcome)
    assert second.expect(LeaseRenewed).lease_id == offer.lease_id
    assert worker_node.expect_close() == 4000
    assert plane.registry.session(worker_node.worker_node_id).socket is not None and len(plane.registry.connected()) == 1
    second.succeed(offer)
    second.heartbeat()
    assert stores.jobs.get(job.job_id).state == JobState.SUCCEEDED
    second.close()


def test_cancelling_a_running_job_tells_its_worker_node(make_worker_node, plane, stores, on_loop, schedule):
    worker_node = make_worker_node("lab 1", slots={SCENE: 1})
    worker_node.connect()
    job = _submit(on_loop, plane)
    schedule()
    offer = worker_node.expect(LeaseOffer)
    worker_node.accept(offer)
    outcome = on_loop(plane.cancel, job.job_id, "not needed")
    assert outcome.cancelled
    cancel = worker_node.expect(Cancel)
    assert (cancel.lease_id, cancel.job_id, cancel.reason) == (offer.lease_id, job.job_id, "not needed")
    assert stores.jobs.get(job.job_id).state == JobState.CANCELLED


def test_the_scheduler_runs_by_itself_when_timers_are_on(make_worker_node, plane, on_loop):
    on_loop(plane.start)  # the scheduler loop, woken by the submission
    try:
        worker_node = make_worker_node("lab 1")
        worker_node.connect()
        job = _submit(on_loop, plane)
        assert worker_node.expect(LeaseOffer).job.job_id == job.job_id
    finally:
        on_loop(plane.stop)


# Payload validation at submission


def test_a_payload_that_does_not_match_its_job_type_is_refused_before_it_is_stored(plane, stores, on_loop):
    with pytest.raises(InvalidPayload) as refusal:
        _submit(on_loop, plane, payload={"scene": 1})
    assert refusal.value.job_type == SCENE
    assert {error["loc"][0] for error in refusal.value.errors} >= {"functional_scenario_content", "scene"}
    with pytest.raises(InvalidPayload):
        _submit(on_loop, plane, job_type=KINEMATIC, payload=valid_payload(KINEMATIC, monitor="post_hoc"))
    with pytest.raises(InvalidPayload):  # the runner picks the payload model
        _submit(on_loop, plane, job_type=SIMULATION, payload=ardupilot_payload("gazebo", runner="kinematic"))
    with pytest.raises(InvalidPayload) as refusal:
        _submit(on_loop, plane, job_type=SIMULATION, payload={"trajectories": valid_payload(SIMULATION)["trajectories"]})
    assert "runner" in str(refusal.value)
    assert stores.jobs.list_jobs() == []


def test_a_referenced_input_gets_a_structural_check_only(plane, stores, on_loop):
    reference = {"sha256": "ab" * 32, "size_bytes": 1024, "kind": "trajectories"}
    job = _submit(on_loop, plane, job_type=KINEMATIC, payload={"runner": "kinematic", "trajectories": reference, "monitor": "live"})
    assert stores.jobs.get(job.job_id).payload["trajectories"] == reference
    with pytest.raises(InvalidPayload):
        _submit(on_loop, plane, job_type=KINEMATIC, payload={"runner": "kinematic", "trajectories": {**reference, "sha256": "AB" * 32}})


def test_the_control_node_imports_no_job_type_module_until_a_submission():
    script = "import sys, scenegems_tool.cluster.control_node.server; print(sorted(m for m in ('numpy', 'concrete_level', 'scenegems_tool.cluster.worker_node.jobs.job_types') if m in sys.modules))"
    source = Path(__file__).resolve().parents[4]
    output = subprocess.run([sys.executable, "-c", script], cwd=source.parent, env={**os.environ, "PYTHONPATH": str(source)}, capture_output=True, text=True, check=True).stdout
    assert output.strip() == "[]"


# Campaigns


def test_the_pipeline_engine_sees_the_connected_worker_nodes(make_worker_node, plane):
    worker_node = make_worker_node("lab a", slots={SCENE: 1})
    assert plane.worker_node_availability() == []
    worker_node.connect()
    (available,) = plane.worker_node_availability()
    assert available.record.worker_node_id == worker_node.worker_node_id and available.stale_components == frozenset()


def test_an_attached_pipeline_engine_submits_through_the_control_plane(plane):
    from sqlalchemy.orm import sessionmaker

    stores = AssuranceStores.create(sessionmaker())
    engine = plane.attach_pipeline(stores)
    assert plane.pipeline is engine and engine.stores is stores and engine.jobs is plane.jobs
    assert engine.settings.stall_after_s == plane.timing.campaign_stall_after_s
    assert engine._submit == plane.submit and engine._cancel == plane.cancel


def test_the_pipeline_engine_runs_as_a_timer_of_the_control_plane(plane):
    intervals = []

    class Engine:
        async def run(self, interval_s):
            intervals.append(interval_s)
            await asyncio.Event().wait()

    async def start_and_stop():
        plane.pipeline = Engine()
        await plane.start(timers=True)
        await asyncio.sleep(0)
        await plane.stop()

    asyncio.run(start_and_stop())
    assert intervals == [plane.timing.pipeline_tick_interval_s]
