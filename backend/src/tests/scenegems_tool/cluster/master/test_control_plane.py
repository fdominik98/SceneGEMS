"""The control plane end to end with scripted nodes: who gets which job, lost nodes, rejects, reconnects.

Each test runs on the in-memory stores and, with `-m postgres`, on a real database.
"""

import asyncio
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from scenegems_tool.cluster.fingerprints.job_images import SCENARIO_EXECUTION_IMAGE
from scenegems_tool.cluster.master.control_plane import InvalidPayload
from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobRequirements, JobState, JobSubmission, JobType
from scenegems_tool.cluster.protocol.messages import Cancel, Drain, LeaseOffer, LeaseRelease, LeaseRenewed, ProtocolError, ProtocolErrorCode, Welcome
from scenegems_tool.persistence.schema import JobEventKind, NodeStatus
from scenegems_tool.persistence.stores import AssuranceStores
from tests.scenegems_tool.cluster.master.conftest import EXPECTED, KINEMATIC, SCENE
from tests.scenegems_tool.cluster.payloads import valid_payload
from tests.scenegems_tool.cluster.stack_images import GAZEBO_IMAGE, SITL_IMAGE
from tests.scenegems_tool.persistence.stores.builders import make_resources

SITL = JobType.SIMULATION_ARDUPILOT_SIM
GAZEBO = JobType.SIMULATION_GAZEBO


def _submit(on_loop, plane, job_type=SCENE, **fields):
    fields.setdefault("payload", valid_payload(job_type))
    return on_loop(plane.submit, JobSubmission(job_type=job_type, **fields)).job


def _offers(node, count):
    return [node.expect(LeaseOffer) for _ in range(count)]


# Competing nodes and lost nodes


def test_two_nodes_compete_and_each_job_runs_once(make_node, plane, stores, on_loop, schedule):
    a, b = make_node("lab a", slots={SCENE: 2}), make_node("lab b", slots={SCENE: 2})
    a.connect()
    b.connect()
    jobs = [_submit(on_loop, plane, payload=valid_payload(SCENE, seed=index)) for index in range(6)]

    assert schedule() == 4  # two slots each
    offers = {a.node_id: _offers(a, 2), b.node_id: _offers(b, 2)}
    assert len({offer.job.job_id for batch in offers.values() for offer in batch}) == 4
    assert schedule() == 0  # every slot is taken

    for node in (a, b):
        for offer in offers[node.node_id]:
            node.accept(offer)
            node.succeed(offer)
    a.heartbeat()
    b.heartbeat()
    assert schedule() == 2
    rest = [(node, offer) for node in (a, b) for offer in _offers(node, 1)]
    for node, offer in rest:
        node.accept(offer)
        node.succeed(offer)
    a.heartbeat()
    b.heartbeat()
    on_loop(plane.leases.sweep_expired)

    finished = [stores.jobs.get(job.job_id) for job in jobs]
    assert all(job.state == JobState.SUCCEEDED and job.attempt == 1 for job in finished)
    assert sorted(job.lease_owner for job in finished) == sorted([a.node_id] * 3 + [b.node_id] * 3)
    for job in finished:
        assert [event.kind for event in stores.jobs.events(job.job_id)].count(JobEventKind.SUCCEEDED) == 1


def test_a_node_lost_mid_lease_has_its_job_finished_elsewhere_and_stored_once(make_node, plane, stores, on_loop, schedule, clock):
    lost, other = make_node("lab lost", slots={SCENE: 1}), make_node("lab other", slots={SCENE: 1})
    lost.connect()
    job = _submit(on_loop, plane)
    schedule()
    offer = lost.expect(LeaseOffer)
    lost.accept(offer)
    lost.close()  # the node dies while running the job: no renewals, no result
    other.connect()
    assert schedule() == 0  # the lease still holds

    for _ in range(6):  # 30 s pass; the other node keeps sending heartbeats
        clock.advance(5)
        other.heartbeat()
    on_loop(plane.registry.sweep_silent)
    expired = on_loop(plane.leases.sweep_expired)
    assert [lease.job.job_id for lease in expired] == [job.job_id]
    assert stores.nodes.get(lost.node_id).status == NodeStatus.OFFLINE
    schedule()
    second = other.expect(LeaseOffer)
    assert second.job.job_id == job.job_id and second.job.attempt == 2
    other.accept(second)
    other.succeed(second, {"done_by": other.node_id})

    # The lost node comes back with its stale lease and its result: it is told to stop, and nothing is stored twice
    lost.connect(running_lease_ids=[offer.lease_id])
    cancel = lost.expect(Cancel)
    assert cancel.lease_id == offer.lease_id
    lost.send(lost.result(offer, JobOutcome.SUCCEEDED, {"done_by": lost.node_id}))
    assert lost.expect(ProtocolError).code == ProtocolErrorCode.UNKNOWN_LEASE

    stored = stores.jobs.get(job.job_id)
    assert stored.state == JobState.SUCCEEDED and stored.result == {"done_by": other.node_id} and stored.failed_attempts == 1
    kinds = [event.kind for event in stores.jobs.events(job.job_id)]
    assert kinds == [JobEventKind.SUBMITTED, JobEventKind.LEASED, JobEventKind.ACCEPTED, JobEventKind.EXPIRED, JobEventKind.LEASED, JobEventKind.ACCEPTED, JobEventKind.SUCCEEDED]


def test_expiry_at_the_retry_limit_fails_the_job(make_node, plane, stores, on_loop, schedule, clock):
    node = make_node("lab 1", slots={SCENE: 1})
    node.connect()
    job = _submit(on_loop, plane, max_attempts=2)
    for attempt in (1, 2):
        schedule()
        offer = node.expect(LeaseOffer)
        assert offer.job.attempt == attempt
        node.accept(offer)
        clock.advance(31)
        node.heartbeat()
        on_loop(plane.leases.sweep_expired)
        assert node.expect(Cancel).lease_id == offer.lease_id
    stored = stores.jobs.get(job.job_id)
    assert stored.state == JobState.FAILED and "no attempts left" in stored.error
    assert schedule() == 0


def test_an_unaccepted_offer_of_a_disconnected_node_returns_to_the_queue_at_once(make_node, plane, stores, on_loop, schedule):
    gone, other = make_node("lab gone"), make_node("lab other")
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


def test_jobs_go_only_to_nodes_with_the_job_type_and_a_free_slot(make_node, plane, on_loop, schedule):
    scene_node, kinematic_node = make_node("scene", slots={SCENE: 1}), make_node("kinematic", slots={KINEMATIC: 1})
    scene_node.connect()
    kinematic_node.connect()
    kinematic_job = _submit(on_loop, plane, job_type=KINEMATIC)
    scene_jobs = [_submit(on_loop, plane) for _ in range(2)]
    assert schedule() == 2
    assert kinematic_node.expect(LeaseOffer).job.job_id == kinematic_job.job_id
    assert scene_node.expect(LeaseOffer).job.job_id == scene_jobs[0].job_id
    assert schedule() == 0


def test_labels_must_match(make_node, plane, on_loop, schedule):
    plain, gpu = make_node("plain", slots={SCENE: 2}), make_node("gpu", slots={SCENE: 2}, labels={"gpu": "yes"})
    plain.connect()
    gpu.connect()
    job = _submit(on_loop, plane, requirements=JobRequirements(labels={"gpu": "yes"}))
    assert schedule() == 1
    assert gpu.expect(LeaseOffer).job.job_id == job.job_id


def test_a_gazebo_job_goes_to_a_gazebo_node_with_the_gazebo_image(make_node, plane, stores, on_loop, schedule):
    without_gazebo = {image: fingerprint for image, fingerprint in EXPECTED.items() if image != GAZEBO_IMAGE}
    sitl_only = make_node("sitl only", slots={SITL: 2}, fingerprints=without_gazebo)
    sitl_only.connect()
    gazebo_job = _submit(on_loop, plane, job_type=GAZEBO, payload=valid_payload(GAZEBO))
    sim_job = _submit(on_loop, plane, job_type=SITL, payload=valid_payload(SITL))
    assert stores.jobs.get(gazebo_job.job_id).requirements.fingerprints == {SCENARIO_EXECUTION_IMAGE: "fp-execution", SITL_IMAGE: "fp-sitl", GAZEBO_IMAGE: "fp-gazebo"}
    assert stores.jobs.get(sim_job.job_id).requirements.fingerprints == {SCENARIO_EXECUTION_IMAGE: "fp-execution", SITL_IMAGE: "fp-sitl"}
    assert schedule() == 1
    assert sitl_only.expect(LeaseOffer).job.job_id == sim_job.job_id
    # a Gazebo node without the Gazebo image is out of date and gets nothing
    gazebo_without_image = make_node("gazebo without its image", slots={GAZEBO: 1}, fingerprints=without_gazebo)
    gazebo_without_image.connect()
    assert schedule() == 0
    with_gazebo = make_node("with gazebo", slots={GAZEBO: 1})
    with_gazebo.connect()
    assert schedule() == 1
    assert with_gazebo.expect(LeaseOffer).job.job_id == gazebo_job.job_id


def test_an_out_of_date_node_gets_no_jobs_and_is_reported(make_node, plane, stores, on_loop, schedule):
    stale = dict(EXPECTED, **{SCENARIO_EXECUTION_IMAGE: "fp-older"})
    # The node offers scene generation, whose image matches, and kinematic simulation, whose image does not
    outdated = make_node("outdated", slots={SCENE: 2, KINEMATIC: 1}, fingerprints=stale)
    outdated.connect()
    _submit(on_loop, plane)
    assert schedule() == 0
    session = plane.registry.session(outdated.node_id)
    assert [(mismatch.image, mismatch.required, mismatch.actual) for mismatch in session.out_of_date] == [(SCENARIO_EXECUTION_IMAGE, "fp-execution", "fp-older")]
    current = make_node("current", slots={SCENE: 1})
    current.connect()
    assert schedule() == 1
    current.expect(LeaseOffer)


def test_a_node_without_a_required_image_is_out_of_date(make_node, plane, on_loop, schedule):
    missing = make_node("missing", slots={SCENE: 1}, fingerprints={})
    missing.connect()
    _submit(on_loop, plane)
    assert schedule() == 0
    assert plane.registry.session(missing.node_id).out_of_date[0].missing


def test_the_resource_guard_holds_offers_until_the_node_has_room(make_node, plane, on_loop, schedule):
    node = make_node("busy", slots={SCENE: 2}, resources=make_resources(free_memory_mb=100))
    node.connect()
    _submit(on_loop, plane)
    assert schedule() == 0
    node.heartbeat(free_memory_mb=8000, load_average=3.0)
    assert schedule() == 0
    node.heartbeat(free_memory_mb=8000, load_average=0.5)
    assert schedule() == 1
    node.expect(LeaseOffer)


def test_a_job_minimum_above_the_nodes_free_memory_waits(make_node, plane, on_loop, schedule):
    node = make_node("small", slots={SCENE: 2}, resources=make_resources(free_memory_mb=2000))
    node.connect()
    _submit(on_loop, plane, requirements=JobRequirements(min_memory_mb=4000))
    assert schedule() == 0


def test_higher_priority_first(make_node, plane, on_loop, schedule):
    node = make_node("lab 1", slots={SCENE: 1})
    node.connect()
    _submit(on_loop, plane)
    urgent = _submit(on_loop, plane, priority=5)
    schedule()
    assert node.expect(LeaseOffer).job.job_id == urgent.job_id


def test_offers_spread_round_robin_over_the_nodes(make_node, plane, on_loop, schedule):
    nodes = [make_node(f"lab {index}", slots={SCENE: 4}) for index in range(3)]
    for node in nodes:
        node.connect()
    for _ in range(3):
        _submit(on_loop, plane)
    assert schedule() == 3
    for node in nodes:
        node.expect(LeaseOffer)


def test_a_draining_node_gets_no_new_jobs_until_resumed(make_node, plane, stores, on_loop, schedule):
    node = make_node("lab 1")
    node.connect()
    on_loop(plane.drain, node.node_id, "maintenance")
    assert node.expect(Drain).reason == "maintenance"
    _submit(on_loop, plane)
    node.heartbeat()  # a heartbeat does not end a drain
    assert schedule() == 0
    assert stores.nodes.get(node.node_id).status == NodeStatus.DRAINING
    on_loop(plane.resume, node.node_id)
    assert schedule() == 1
    node.expect(LeaseOffer)


# Rejects


def test_a_rejected_job_is_held_back_from_that_node_only(make_node, plane, stores, on_loop, schedule, clock):
    picky, other = make_node("picky", slots={SCENE: 1}), make_node("other", slots={SCENE: 1})
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


def test_a_released_job_returns_without_using_an_attempt(make_node, plane, stores, on_loop, schedule):
    node = make_node("lab 1", slots={SCENE: 1})
    node.connect()
    job = _submit(on_loop, plane)
    schedule()
    offer = node.expect(LeaseOffer)
    node.accept(offer)
    node.send(LeaseRelease(lease_id=offer.lease_id, reason="draining"))
    node.heartbeat()
    assert stores.jobs.get(job.job_id).state == JobState.QUEUED and stores.jobs.get(job.job_id).failed_attempts == 0
    assert schedule() == 1


def test_a_retryable_failure_runs_again_and_a_permanent_one_fails(make_node, plane, stores, on_loop, schedule, clock):
    node = make_node("lab 1", slots={SCENE: 1})
    node.connect()
    job = _submit(on_loop, plane)
    schedule()
    offer = node.expect(LeaseOffer)
    node.accept(offer)
    node.send(node.result(offer, JobOutcome.FAILED, error="docker hiccup", retryable=True))
    node.heartbeat()
    assert schedule() == 0  # in its retry backoff
    clock.advance(stores.jobs.retry_backoff_base_s)
    node.heartbeat()
    assert schedule() == 1
    second = node.expect(LeaseOffer)
    node.accept(second)
    node.send(node.result(second, JobOutcome.FAILED, error="invalid payload"))
    node.heartbeat()
    stored = stores.jobs.get(job.job_id)
    assert stored.state == JobState.FAILED and stored.error == "invalid payload" and stored.attempt == 2


# Reconnects


def test_a_reconnect_reconciles_the_reported_leases(make_node, client, plane, stores, on_loop, schedule, clock):
    from tests.scenegems_tool.cluster.master.fake_node import FakeNode

    node = make_node("lab 1", slots={SCENE: 4})
    node.connect()
    jobs = [_submit(on_loop, plane, payload=valid_payload(SCENE, seed=index)) for index in range(4)]
    schedule()
    kept, unconfirmed, lost, forgotten = _offers(node, 4)
    node.accept(kept)
    node.accept(lost)

    # The node's network flaps and it reconnects before the master notices the old socket is dead. It still
    # runs `kept` and had accepted `unconfirmed` (that accept never arrived); its daemon restarted `lost`
    # away, and `forgotten` was never accepted. It also names a lease nobody knows.
    clock.advance(5)
    again = FakeNode(client, node.hello_frame)
    again.connect(running_lease_ids=[kept.lease_id, unconfirmed.lease_id, "no-such-lease"])
    frames = [again.receive() for _ in range(3)]
    renewed = {frame.lease_id: frame for frame in frames if isinstance(frame, LeaseRenewed)}
    assert set(renewed) == {kept.lease_id, unconfirmed.lease_id}
    assert all(frame.expires_at == clock.now + timedelta(seconds=30) for frame in renewed.values())
    assert [(frame.lease_id, frame.job_id) for frame in frames if isinstance(frame, Cancel)] == [("no-such-lease", "")]
    assert node.expect_close() == 4000

    states = {job.job_id: stores.jobs.get(job.job_id) for job in jobs}
    assert states[kept.job.job_id].state == JobState.RUNNING
    assert states[unconfirmed.job.job_id].state == JobState.RUNNING
    assert states[lost.job.job_id].state == JobState.QUEUED and states[lost.job.job_id].failed_attempts == 1
    assert states[forgotten.job.job_id].state == JobState.QUEUED and states[forgotten.job.job_id].failed_attempts == 0
    assert again.renew(unconfirmed.lease_id).lease_id == unconfirmed.lease_id
    again.close()


def test_a_newer_connection_replaces_the_older_one(make_node, client, plane, stores, on_loop, schedule):
    from tests.scenegems_tool.cluster.master.fake_node import FakeNode

    node = make_node("lab 1", slots={SCENE: 1})
    node.connect()
    job = _submit(on_loop, plane)
    schedule()
    offer = node.expect(LeaseOffer)
    node.accept(offer)

    second = FakeNode(client, node.hello_frame)
    assert isinstance(second.connect(running_lease_ids=[offer.lease_id]), Welcome)
    assert second.expect(LeaseRenewed).lease_id == offer.lease_id
    assert node.expect_close() == 4000
    assert plane.registry.session(node.node_id).socket is not None and len(plane.registry.connected()) == 1
    second.succeed(offer)
    second.heartbeat()
    assert stores.jobs.get(job.job_id).state == JobState.SUCCEEDED
    second.close()


def test_cancelling_a_running_job_tells_its_node(make_node, plane, stores, on_loop, schedule):
    node = make_node("lab 1", slots={SCENE: 1})
    node.connect()
    job = _submit(on_loop, plane)
    schedule()
    offer = node.expect(LeaseOffer)
    node.accept(offer)
    outcome = on_loop(plane.cancel, job.job_id, "not needed")
    assert outcome.cancelled
    cancel = node.expect(Cancel)
    assert (cancel.lease_id, cancel.job_id, cancel.reason) == (offer.lease_id, job.job_id, "not needed")
    assert stores.jobs.get(job.job_id).state == JobState.CANCELLED


def test_the_scheduler_runs_by_itself_when_timers_are_on(make_node, plane, on_loop):
    on_loop(plane.start)  # the scheduler loop, woken by the submission
    try:
        node = make_node("lab 1")
        node.connect()
        job = _submit(on_loop, plane)
        assert node.expect(LeaseOffer).job.job_id == job.job_id
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
    with pytest.raises(InvalidPayload):  # each ArduPilot job type runs its own layer only
        _submit(on_loop, plane, job_type=SITL, payload=valid_payload(SITL, simulation_layer="gazebo"))
    assert stores.jobs.list_jobs() == []


def test_a_referenced_input_gets_a_structural_check_only(plane, stores, on_loop):
    reference = {"sha256": "ab" * 32, "size_bytes": 1024, "kind": "trajectories"}
    job = _submit(on_loop, plane, job_type=KINEMATIC, payload={"trajectories": reference, "monitor": "live"})
    assert stores.jobs.get(job.job_id).payload["trajectories"] == reference
    with pytest.raises(InvalidPayload):
        _submit(on_loop, plane, job_type=KINEMATIC, payload={"trajectories": {**reference, "sha256": "AB" * 32}})


def test_the_master_imports_no_job_type_module_until_a_submission():
    script = "import sys, scenegems_tool.cluster.master.server; print(sorted(m for m in ('numpy', 'concrete_level', 'scenegems_tool.cluster.node.jobs.job_types') if m in sys.modules))"
    source = Path(__file__).resolve().parents[4]
    output = subprocess.run([sys.executable, "-c", script], cwd=source.parent, env={**os.environ, "PYTHONPATH": str(source)}, capture_output=True, text=True, check=True).stdout
    assert output.strip() == "[]"


# Campaigns


def test_the_pipeline_engine_sees_the_connected_nodes(make_node, plane):
    node = make_node("lab a", slots={SCENE: 1})
    assert plane.node_availability() == []
    node.connect()
    (available,) = plane.node_availability()
    assert available.record.node_id == node.node_id and not available.out_of_date


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
