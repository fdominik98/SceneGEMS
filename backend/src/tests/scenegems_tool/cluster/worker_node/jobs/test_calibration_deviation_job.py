"""calibration.deviation in process: exact repeats, a bounded deviation, and refusals."""

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
        return calibration_deviation_job.execute(make_job(JobType.CALIBRATION_DEVIATION, payload), _quiet)

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
