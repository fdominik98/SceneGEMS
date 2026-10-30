"""The runner container's entry point, run in process against a job folder on disk."""

import json
import math

import numpy as np
import pytest

from scenegems_tool.cluster.node.jobs.in_container import job_container_main
from scenegems_tool.cluster.node.jobs.in_container.job_container_main import json_safe
from scenegems_tool.cluster.node.jobs.in_container.run_observation import ContainerObservation
from scenegems_tool.cluster.node.jobs.monitoring_post_hoc_job import execute as execute_post_hoc
from scenegems_tool.cluster.node.jobs.simulation_job import execute as execute_kinematic
from scenegems_tool.cluster.node.launchers.per_job.job_container_io import OBSERVE_DOCUMENT, ObservationControl, parse_frame_line
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import run_kinematic_closed_loop, run_kinematic_replay


@pytest.fixture
def job_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(job_container_main, "JOB_FOLDER", str(tmp_path))
    return tmp_path


def write_job(folder, job) -> None:
    (folder / "job.json").write_text(json.dumps({"job": job.model_dump(mode="json")}), encoding="utf-8")


def read_outcome(folder) -> dict:
    return json.loads((folder / "result.json").read_text(encoding="utf-8"))


def test_json_safe_converts_numpy_enums_tuples_and_non_finite_floats():
    assert json_safe({"a": np.float64(1.5), "b": (1, np.int64(2)), "c": np.array([1.0, 2.0]), "d": JobType.SCENE_GENERATION, "e": math.inf, 3: np.bool_(True)}) == {
        "a": 1.5,
        "b": [1, 2],
        "c": [1.0, 2.0],
        "d": "scene_generation",
        "e": None,
        "3": True,
    }


def test_kinematic_replay_matches_the_in_process_run(make_job, head_on_trajectories):
    job = make_job(JobType.SIMULATION, {"runner": "kinematic", "trajectories": head_on_trajectories.to_dict(), "seed": 4})
    statuses = []
    result = execute_kinematic(job, lambda message, progress=None: statuses.append(message))
    direct = run_kinematic_replay(head_on_trajectories)
    assert result["state_digest"] == direct.state_digest()
    assert result["steps"] == 120
    assert result["run_record"]["run_seed"] == 4
    assert len(result["trajectories"]["scene_list"]) == 121
    assert statuses[0] == "running the kinematic replay run"


def test_kinematic_closed_loop_matches_the_in_process_run(make_job, head_on_trajectories):
    job = make_job(JobType.SIMULATION, {"runner": "kinematic", "mode": "usv_navigation", "trajectories": head_on_trajectories.to_dict(), "include_trajectories": False})
    result = execute_kinematic(job, lambda message, progress=None: None)
    assert result["state_digest"] == run_kinematic_closed_loop(head_on_trajectories).state_digest()
    assert "trajectories" not in result
    assert result["run_record"]["usv_navigation"]["vessel"] == 0


def test_post_hoc_monitoring_summarizes_the_verdicts(make_job, head_on_trajectories):
    job = make_job(JobType.MONITORING_POST_HOC, {"trajectories": head_on_trajectories.to_dict(), "include_frames": True})
    result = execute_post_hoc(job, lambda message, progress=None: None)
    assert (result["scenes"], result["monitored_scenes"], result["time_step"]) == (121, 121, 1)
    assert len(result["frames"]) == 121
    # The vessels keep their reciprocal courses, so the give-way rule fails once the monitor expects action.
    assert not result["passed"]
    assert all(set(item) == {"relation", "rule", "first_failed_at"} for item in result["failed_rules"])
    assert [item["first_failed_at"] for item in result["failed_rules"]] == sorted(item["first_failed_at"] for item in result["failed_rules"])
    assert json_safe(result) == json.loads(json.dumps(json_safe(result)))


def test_main_writes_the_result_document(job_folder, make_job, head_on_trajectories, capsys):
    write_job(job_folder, make_job(JobType.SIMULATION, {"runner": "kinematic", "trajectories": head_on_trajectories.to_dict(), "include_trajectories": False}))
    assert job_container_main.main() == 0
    outcome = read_outcome(job_folder)
    assert outcome["result"]["state_digest"] == run_kinematic_replay(head_on_trajectories).state_digest()
    assert capsys.readouterr().out.startswith("scenegems-status ")


def test_main_writes_an_error_document_when_the_job_fails(job_folder, make_job, head_on_trajectories):
    write_job(job_folder, make_job(JobType.SIMULATION, {"runner": "kinematic", "mode": "usv_navigation", "trajectories": head_on_trajectories.to_dict(), "own_ship_id": 99}))
    assert job_container_main.main() == 1
    outcome = read_outcome(job_folder)
    assert "No vessel with id 99" in outcome["error"]
    assert outcome["retryable"] is False
    assert "result" not in outcome


def test_an_observed_simulation_writes_frame_lines_and_the_same_result(job_folder, make_job, head_on_trajectories, capsys, monkeypatch):
    monkeypatch.setattr(job_container_main, "ContainerObservation", lambda folder: ContainerObservation(folder, sleep=lambda seconds: None))
    write_job(job_folder, make_job(JobType.SIMULATION, {"runner": "kinematic", "trajectories": head_on_trajectories.to_dict(), "include_trajectories": False}))
    assert job_container_main.main() == 0
    plain = read_outcome(job_folder)
    assert not [line for line in capsys.readouterr().out.splitlines() if parse_frame_line(line)]  # nobody observes: no frames

    (job_folder / OBSERVE_DOCUMENT).write_text(ObservationControl(active=True, speed=1000.0, revision=1).to_document(), encoding="utf-8")
    assert job_container_main.main() == 0
    assert read_outcome(job_folder) == plain
    frames = [parse_frame_line(line) for line in capsys.readouterr().out.splitlines() if parse_frame_line(line)]
    assert [frame["timestamp"] for frame in frames] == [0, 50, 100, 120]  # 1000 steps a second, 20 frames a second at most, and the last step


def test_jobs_that_are_not_simulations_get_no_observation(job_folder, make_job, head_on_trajectories, monkeypatch):
    def refuse(folder):
        raise AssertionError("a post-hoc monitoring job is not observable")

    monkeypatch.setattr(job_container_main, "ContainerObservation", refuse)
    write_job(job_folder, make_job(JobType.MONITORING_POST_HOC, {"trajectories": head_on_trajectories.to_dict()}))
    assert job_container_main.main() == 0 and "result" in read_outcome(job_folder)
