"""The lease manager with a recording sender and a hand-driven clock; jobs are scripted (conftest.ScriptedJobs)."""

import threading
from typing import List

import pytest

from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobType
from scenegems_tool.cluster.protocol.messages import (
    Cancel,
    Drain,
    JobResult,
    JobStatus,
    LeaseAccept,
    LeaseReject,
    LeaseRelease,
    LeaseRenew,
    LeaseRenewed,
    LogLines,
    ObservationFrames,
    Observe,
    Welcome,
)
from scenegems_tool.cluster.worker_node.daemon.leases.lease import LeasePhase
from scenegems_tool.cluster.worker_node.daemon.leases.lease_manager import LeaseManager
from scenegems_tool.cluster.worker_node.daemon.leases.slot_table import SlotTable
from scenegems_tool.cluster.worker_node.job_observation import JobObservations
from tests.scenegems_tool.cluster.worker_node.daemon.conftest import make_job, make_offer, wait_for

KINEMATIC = JobType.SIMULATION


class RecordingSender:
    def __init__(self) -> None:
        self.frames: List = []
        self.connected = True
        self._lock = threading.Lock()

    def send(self, frame) -> bool:
        if not self.connected:
            return False
        with self._lock:
            self.frames.append(frame)
        return True

    def of(self, kind) -> List:
        with self._lock:
            return [frame for frame in self.frames if isinstance(frame, kind)]


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeWorkerNode:
    worker_node_id = "n1"
    components = frozenset({"asv_software/replay", "control_layer/none", "simulation_layer/kinematic"})

    def __init__(self, clock) -> None:
        self.observations = JobObservations(clock)

    def lacks(self, job):
        return [component for component in job.requirements.components if component not in self.components]


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def sender():
    return RecordingSender()


@pytest.fixture
def manager(sender, clock, jobs):
    manager = LeaseManager(SlotTable({KINEMATIC: 2}), FakeWorkerNode(clock), sender, run=jobs, clock=clock)
    manager.set_lease_timeout(9.0)
    yield manager
    manager.shutdown("test over", timeout_s=5.0)


def accept(manager, sender, jobs, lease_id: str):
    manager.on_offer(make_offer(lease_id, make_job(f"job-{lease_id}")))
    assert sender.of(LeaseAccept)[-1].lease_id == lease_id
    assert jobs.wait_started() == f"job-{lease_id}"


def test_an_accepted_lease_runs_and_reports_its_result(manager, sender, jobs):
    accept(manager, sender, jobs, "a")
    assert manager.running_lease_ids() == ["a"] and manager.slots_in_use() == {KINEMATIC: 1}
    jobs.finish("job-a", {"value": 1})
    wait_for(lambda: sender.of(JobResult))
    [result] = sender.of(JobResult)
    assert result.outcome == JobOutcome.SUCCEEDED and result.result == {"value": 1} and result.idempotency_key == "job-a/key"
    wait_for(lambda: not manager.busy)
    assert manager.slots_in_use() == {} and manager.running_lease_ids() == []
    kinds = [type(frame) for frame in sender.frames]
    assert kinds.index(JobStatus) < kinds.index(JobResult) and kinds.index(LogLines) < kinds.index(JobResult)


def test_offers_beyond_the_slots_and_unknown_types_are_rejected(manager, sender, jobs):
    accept(manager, sender, jobs, "a")
    accept(manager, sender, jobs, "b")
    manager.on_offer(make_offer("c"))
    manager.on_offer(make_offer("t", make_job("job-t", job_type=JobType.TRAJECTORY_GENERATION)))
    reasons = {frame.lease_id: frame.reason for frame in sender.of(LeaseReject)}
    assert reasons == {"c": "all 2 simulation slots are in use", "t": "this worker node offers no trajectory_generation slots"}
    assert jobs.most_running == 2


def test_an_offer_needing_a_component_the_worker_node_lacks_is_rejected(manager, sender, jobs):
    from scenegems_tool.cluster.protocol.jobs import JobRequirements

    gazebo = make_job("job-g").model_copy(update={"requirements": JobRequirements(components=["asv_software/replay", "control_layer/ardupilot", "simulation_layer/gazebo"])})
    manager.on_offer(make_offer("g", gazebo))
    (reject,) = sender.of(LeaseReject)
    assert reject.reason == "this worker node does not offer the components control_layer/ardupilot, simulation_layer/gazebo"
    assert manager.slots_in_use() == {}


def test_a_repeated_offer_of_a_held_lease_is_accepted_again_without_a_second_run(manager, sender, jobs):
    accept(manager, sender, jobs, "a")
    manager.on_offer(make_offer("a", make_job("job-a")))
    assert [frame.lease_id for frame in sender.of(LeaseAccept)] == ["a", "a"]
    assert jobs.started.empty() and manager.slots_in_use() == {KINEMATIC: 1}


def test_an_accept_that_cannot_be_sent_runs_nothing(manager, sender, jobs):
    sender.connected = False
    manager.on_offer(make_offer("a"))
    assert not manager.busy and manager.slots_in_use() == {}
    assert jobs.started.empty()


def test_renewals_are_sent_every_third_of_the_timeout(manager, sender, jobs, clock):
    accept(manager, sender, jobs, "a")
    clock.now += 2.9
    manager.tick()
    assert not sender.of(LeaseRenew)
    clock.now += 0.1
    manager.tick()
    manager.tick()
    assert [frame.lease_id for frame in sender.of(LeaseRenew)] == ["a"]
    clock.now += 3.0
    manager.tick()
    assert len(sender.of(LeaseRenew)) == 2


def test_confirmed_renewals_keep_the_lease_and_missing_ones_lose_it(manager, sender, jobs, clock):
    accept(manager, sender, jobs, "a")
    for _ in range(5):
        clock.now += 3.0
        manager.tick()
        manager.handle(LeaseRenewed(lease_id="a", expires_at=make_offer("x").expires_at))
    assert manager.lease("a").phase == LeasePhase.RUNNING
    clock.now += 9.1
    manager.tick()
    wait_for(lambda: jobs.cancelled == ["job-a"])
    wait_for(lambda: not manager.busy)
    assert not sender.of(JobResult) and manager.slots_in_use() == {}


def test_renewals_wait_while_disconnected_and_go_out_on_reconnect(manager, sender, jobs, clock):
    accept(manager, sender, jobs, "a")
    sender.connected = False
    clock.now += 4.0
    manager.tick()
    sender.connected = True
    manager.tick()
    assert len(sender.of(LeaseRenew)) == 1


def test_a_result_ready_while_disconnected_is_sent_by_the_ticker(manager, sender, jobs):
    accept(manager, sender, jobs, "a")
    sender.connected = False
    jobs.finish("job-a")
    wait_for(lambda: manager.lease("a").phase == LeasePhase.FINISHED)
    assert manager.running_lease_ids() == ["a"]  # still held: the next Hello names it
    assert manager.slots_in_use() == {}  # its containers are gone
    sender.connected = True
    manager.tick()
    assert len(sender.of(JobResult)) == 1
    assert not manager.busy


def test_cancel_stops_the_job_without_a_result(manager, sender, jobs):
    accept(manager, sender, jobs, "a")
    manager.handle(Cancel(lease_id="a", job_id="job-a", reason="campaign stopped"))
    wait_for(lambda: not manager.busy)
    assert jobs.cancelled == ["job-a"] and not sender.of(JobResult)
    manager.handle(Cancel(lease_id="unknown", job_id="x", reason="late"))  # ignored


def test_drain_rejects_new_leases_and_running_ones_finish(manager, sender, jobs):
    accept(manager, sender, jobs, "a")
    manager.handle(Drain(reason="update"))
    manager.on_offer(make_offer("b"))
    assert sender.of(LeaseReject)[-1].reason == "the worker node is draining (update)"
    jobs.finish("job-a")
    wait_for(lambda: sender.of(JobResult))


def test_shutdown_releases_running_leases_and_sends_finished_results(manager, sender, jobs):
    accept(manager, sender, jobs, "a")
    accept(manager, sender, jobs, "b")
    sender.connected = False
    jobs.finish("job-b")
    wait_for(lambda: manager.lease("b").phase == LeasePhase.FINISHED)
    sender.connected = True
    manager.shutdown("worker node stopping", timeout_s=5.0)
    assert [(frame.lease_id, frame.reason) for frame in sender.of(LeaseRelease)] == [("a", "worker node stopping")]
    assert [frame.lease_id for frame in sender.of(JobResult)] == ["b"]
    manager.on_offer(make_offer("c"))
    assert sender.of(LeaseReject)[-1].reason == "the worker node is shutting down"


def test_non_lease_messages_are_left_to_the_daemon(manager):
    assert not manager.handle(Welcome(control_node_id="m", heartbeat_interval_s=1.0, lease_timeout_s=3.0))


# Observation: the control node's Observe, the run's frames (added here as the job stack's log follower adds them) and the relay


def frames(count: int, start: int = 0):
    return [({"timestamp": index}, 100) for index in range(start, start + count)]


def test_observe_switches_the_jobs_observation_and_its_frames_go_out_in_bounded_batches(manager, sender, jobs, clock):
    accept(manager, sender, jobs, "a")
    observation = manager.worker_node.observations.get("job-a", 1)
    observation.add_frames(frames(3))  # not observed: dropped
    assert manager.relay_observations() == 0

    assert manager.handle(Observe(job_id="job-a", attempt=1, active=True, speed=20.0))
    assert observation.control.active and observation.control.speed == 20.0
    observation.add_frames(frames(250))
    assert manager.relay_observations() == 1
    assert manager.relay_observations() == 0  # at most one batch per 0.1 s
    clock.now += 0.1
    assert manager.relay_observations() == 1
    first, second = sender.of(ObservationFrames)
    assert (first.lease_id, first.job_id, first.attempt, first.seq, len(first.frames)) == ("a", "job-a", 1, 1, 200)
    assert (second.seq, [frame["timestamp"] for frame in second.frames]) == (2, list(range(200, 250)))

    manager.handle(Observe(job_id="job-a", attempt=1, active=False))
    observation.add_frames(frames(5))
    clock.now += 1.0
    assert manager.relay_observations() == 0 and len(sender.of(ObservationFrames)) == 2
    jobs.finish("job-a")


def test_an_observe_for_another_attempt_or_job_is_ignored(manager, sender, jobs):
    accept(manager, sender, jobs, "a")
    manager.on_observe(Observe(job_id="job-a", attempt=2, active=True))
    manager.on_observe(Observe(job_id="job-x", attempt=1, active=True))
    assert not manager.worker_node.observations.get("job-a", 1).active and manager.worker_node.observations.get("job-a", 2) is None
    jobs.finish("job-a")


def test_frames_wait_while_the_control_node_is_unreachable(manager, sender, jobs, clock):
    accept(manager, sender, jobs, "a")
    manager.on_observe(Observe(job_id="job-a", attempt=1, active=True))
    sender.connected = False
    manager.worker_node.observations.get("job-a", 1).add_frames(frames(4))
    assert manager.relay_observations() == 0
    sender.connected = True
    clock.now += 0.1
    assert manager.relay_observations() == 1 and len(sender.of(ObservationFrames)[0].frames) == 4
    jobs.finish("job-a")


def test_a_finished_job_sends_its_last_frames_and_closes_its_observation(manager, sender, jobs):
    accept(manager, sender, jobs, "a")
    manager.on_observe(Observe(job_id="job-a", attempt=1, active=True))
    observation = manager.worker_node.observations.get("job-a", 1)
    observation.add_frames(frames(3))
    assert manager.relay_observations() == 1
    observation.add_frames(frames(2, start=3))  # within the interval: they go with the job's end
    jobs.finish("job-a")
    wait_for(lambda: sender.of(JobResult))
    assert [len(batch.frames) for batch in sender.of(ObservationFrames)] == [3, 2]
    assert observation.closed and manager.worker_node.observations.get("job-a", 1) is None


def test_a_cancelled_job_closes_its_observation_without_sending(manager, sender, jobs):
    accept(manager, sender, jobs, "a")
    manager.on_observe(Observe(job_id="job-a", attempt=1, active=True))
    manager.worker_node.observations.get("job-a", 1).add_frames(frames(3))
    manager.handle(Cancel(lease_id="a", job_id="job-a", reason="operator"))
    wait_for(lambda: not manager.busy)
    assert sender.of(ObservationFrames) == [] and len(manager.worker_node.observations) == 0
