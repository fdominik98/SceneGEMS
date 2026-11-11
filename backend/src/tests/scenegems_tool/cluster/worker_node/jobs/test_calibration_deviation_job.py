"""calibration.deviation: the comparison in process (exact repeats, a bounded deviation, refusals) and the job as a request to the simulation subsystem."""

import pytest

from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.jobs import calibration_deviation_job


def _quiet(message, progress=None):
    pass


def _shifted(trajectories, vessel_id: int, dy: float):
    """The trajectories with one vessel moved sideways by dy meters in every scene."""
    builder = TrajectoryBuilder.from_trajectories(trajectories)
    scenes = []
    for scene in builder.scene_list:
        states = {actor: (scene[actor].modify_copy(y=scene[actor].y + dy) if actor.id == vessel_id else scene[actor]) for actor in scene.actors}
        scenes.append(states)
    shifted = TrajectoryBuilder(time_step=trajectories.time_step)
    for states in scenes:
        shifted.add_scene_as_dict(states)
    return shifted.build()


@pytest.fixture
def compare(make_job):
    def compare(*repeats, **fields):
        payload = {"trajectories": [repeat.to_dict() for repeat in repeats], "stack": {"stack": "replay/none/kinematic", "release": "abc"}, "reference": "head_on", **fields}
        return calibration_deviation_job.compare(calibration_deviation_job.CalibrationDeviationPayload.model_validate(payload), _quiet)

    return compare


def test_identical_repeats_are_exact(compare, head_on_trajectories):
    result = compare(head_on_trajectories, head_on_trajectories, head_on_trajectories)
    assert result["exact"] and result["repeats"] == 3
    assert len(set(result["trajectory_digests"])) == 1
    assert result["deviation_bound_m"] == 0.0
    assert set(result["per_vessel"]) == {"0", "1"} and result["per_vessel"]["0"]["max_m"] == 0.0
    assert result["samples_per_repeat"] == [121, 121, 121]
    assert result["per_vessel"]["0"]["compared_samples"] > 0
    assert result["stack"] == {"stack": "replay/none/kinematic", "release": "abc"} and result["reference"] == "head_on"


def test_a_drifting_repeat_bounds_the_deviation(compare, head_on_trajectories):
    result = compare(head_on_trajectories, _shifted(head_on_trajectories, 1, 2.5))
    assert not result["exact"]
    assert result["per_vessel"]["0"]["max_m"] == 0.0
    assert result["per_vessel"]["1"]["max_m"] == pytest.approx(2.5)
    assert result["deviation_bound_m"] == pytest.approx(2.5)


def test_repeats_of_different_vessels_are_refused(compare, head_on_trajectories):
    builder = TrajectoryBuilder.from_trajectories(head_on_trajectories)
    one_vessel = builder.remove_vessel(next(vessel for vessel in head_on_trajectories.initial_scene.vessels if vessel.id == 1)).build()
    with pytest.raises(JobFailed, match="same vessels"):
        compare(head_on_trajectories, one_vessel)


def test_the_digest_sees_every_bit(head_on_trajectories):
    assert calibration_deviation_job.trajectories_digest(head_on_trajectories) == calibration_deviation_job.trajectories_digest(head_on_trajectories)
    assert calibration_deviation_job.trajectories_digest(head_on_trajectories) != calibration_deviation_job.trajectories_digest(_shifted(head_on_trajectories, 0, 1e-9))


# The job on the simulation subsystem


class _Report:
    def __init__(self):
        self.statuses = []

    def status(self, message, progress=None):
        self.statuses.append((message, progress))


@pytest.fixture
def subsystem(monkeypatch, worker_node):
    """The worker node's simulation pool, in process: a comparison runs as soon as its request is in."""
    from scenegems_tool.messaging.mqtt_simulation_service import MqttSimulationService
    from tests.scenegems_tool.cluster.worker_node.jobs.in_process_subsystem import REQUEST, InProcessSubsystem

    made = InProcessSubsystem(MqttSimulationService, "simulation-subsystem-3").serve(monkeypatch, worker_node)
    made.hooks[REQUEST] = made.work
    return made


def test_the_job_is_one_compare_repeats_request_and_its_result_is_the_comparison(subsystem, worker_node, make_job, head_on_trajectories):
    from scenegems_tool.cluster.worker_node.subsystem import Subsystem

    payload = {"trajectories": [head_on_trajectories.to_dict(), _shifted(head_on_trajectories, 1, 2.5).to_dict()], "reference": "head_on", "stack": {"release": "abc"}}
    report = _Report()
    result = calibration_deviation_job.run(make_job(JobType.CALIBRATION_DEVIATION, payload), worker_node, report)
    assert subsystem.asked == [Subsystem.SIMULATION], "the comparison is a task of the simulation subsystem"
    [(params, seed)] = subsystem.requests()
    assert params == {"payload": payload} and seed >= 0
    assert not result["exact"] and result["deviation_bound_m"] == pytest.approx(2.5) and result["stack"] == {"release": "abc"}
    assert result == calibration_deviation_job.compare(calibration_deviation_job.CalibrationDeviationPayload.model_validate(payload), _quiet), "as the comparison in process"
    assert [status for status in report.statuses if not status[0].startswith("waiting")] == [("comparing 2 repeats of head_on", None), ("comparison finished", 1.0)]
    assert subsystem.states("job-1-1") == ["received", "queued", "running", "finished"] and subsystem.cancels() == []


def test_repeats_that_cannot_be_compared_fail_the_job_for_good(subsystem, worker_node, make_job, head_on_trajectories):
    builder = TrajectoryBuilder.from_trajectories(head_on_trajectories)
    one_vessel = builder.remove_vessel(next(vessel for vessel in head_on_trajectories.initial_scene.vessels if vessel.id == 1)).build()
    job = make_job(JobType.CALIBRATION_DEVIATION, {"trajectories": [head_on_trajectories.to_dict(), one_vessel.to_dict()], "reference": "head_on"})
    with pytest.raises(JobFailed, match="same vessels") as failure:
        calibration_deviation_job.run(job, worker_node, _Report())
    assert not failure.value.retryable and subsystem.states("job-1-1")[-1] == "finished"


def test_the_job_keeps_its_time_limit_and_an_answer_without_a_comparison_fails_the_attempt(worker_node, make_job, head_on_trajectories, monkeypatch):
    from scenegems_tool.cluster.worker_node.jobs.pool_client import PoolReply

    calls = {}

    def run_pool_request(job, worker_node_, report, cancel, **request):
        calls.update(request)
        return PoolReply("job-1-1", 1, {"result": None, "error": None})

    monkeypatch.setattr(calibration_deviation_job, "run_pool_request", run_pool_request)
    job = make_job(JobType.CALIBRATION_DEVIATION, {"trajectories": [head_on_trajectories.to_dict()] * 2, "reference": "head_on", "timeout_s": 90})
    with pytest.raises(JobFailed, match="without a comparison") as failure:
        calibration_deviation_job.run(job, worker_node, _Report())
    assert failure.value.retryable and (calls["task_name"], calls["timeout_s"], calls["streams"]) == ("compare-repeats", 90.0, ("simulation_result",))
