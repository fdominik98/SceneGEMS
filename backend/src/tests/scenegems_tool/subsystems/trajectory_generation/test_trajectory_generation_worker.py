"""The trajectory generation worker in process: the generator choice, seeds and the complete flag."""

import json
from types import SimpleNamespace

import pytest

from scenegems_tool.subsystems.trajectory_generation import trajectory_generation_worker
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_types import (
    TRAJECTORY_PREVIEW_STREAM,
    TRAJECTORY_RESULT_STREAM,
    MqttTrajectoryGenerationTask,
    TrajectoryGenerationParams,
)
from tests.scenegems_tool.subsystems.pool.pool_fakes import RecordingChannel
from tests.scenegems_tool.vessel_stack.scenarios import encounter_trajectories
from utils.file_system_utils import COLREGS_CONSTANTS_FOLDER


def _task(seed=1, **params) -> MqttTrajectoryGenerationTask:
    scene = encounter_trajectories("crossing_from_starboard", 60).initial_scene
    with open(f"{COLREGS_CONSTANTS_FOLDER}/general_maritime_constants.yaml", encoding="utf-8") as file:
        constants = file.read()
    return MqttTrajectoryGenerationTask(
        sender="test",
        task_uuid="uuid",
        request_id="request",
        scenario_content=json.dumps({"best_scene": scene.to_dict(), "scenario_name": "crossing"}),
        colregs_constraints_content=constants,
        params=TrajectoryGenerationParams.from_wire(params),
        seed=seed,
    )


def _results(channel: RecordingChannel):
    """The (trajectory data, valid, complete, error) of every result the worker put on its result stream; each is final."""
    results = channel.of(TRAJECTORY_RESULT_STREAM)
    assert all(final for _, final in results)
    return [(result["trajectory-data"], result["valid"], result["complete"], result["error-message"]) for result, _ in results]


def _run(task):
    """The previews and the results of a task run in process."""
    channel = RecordingChannel()
    trajectory_generation_worker.run_trajectory_generation_worker(task, channel)
    return [preview for preview, _ in channel.of(TRAJECTORY_PREVIEW_STREAM)], _results(channel)


def test_the_straight_generator_returns_at_once_with_a_complete_plan():
    previews, results = _run(_task(seed=9, generator="straight", timespan=120, timeStep=10))
    assert previews == []
    [(payload, valid, complete, error)] = results
    assert (valid, complete, error) == (True, True, None)
    assert (payload["algorithm_desc"], payload["config_name"], payload["random_seed"]) == ("straight", "crossing", 9)
    assert len(payload["trajectories"]["scene_list"]) == 13


def test_the_search_is_repeatable_with_a_seed_and_records_it():
    first = _run(_task(seed=21, maxIterations=40, includeMonitorResults=False))[1]
    second = _run(_task(seed=21, maxIterations=40, includeMonitorResults=False))[1]
    assert first[0][1:] == (True, True, None)
    assert first[0][0]["random_seed"] == 21 and first[0][0]["algorithm_desc"] == "RRTStar_algo"
    assert first[0][0]["trajectories"] == second[0][0]["trajectories"]


def test_the_search_is_seeded_with_the_tasks_seed(monkeypatch):
    seeds = []
    monkeypatch.setattr(trajectory_generation_worker.random, "seed", seeds.append)
    _run(_task(seed=77, generator="straight"))
    assert seeds == [77], "every task has a seed: the request's, or the one drawn for it"


class _Path(list):
    """A planned path of two scenes."""

    def __init__(self):
        super().__init__([0, 1])


class _Search:
    """Stands in for MonitorGuidedPlanner at the end of a search."""

    def __init__(self, plan=None, partial=None, first_failed_step=None):
        self.plan, self.partial, self.iteration_count, self.first_failed_step = plan, partial, 7, first_failed_step

    def plan_trajectory(self):
        if self.plan is None:
            raise RuntimeError("no complete plan")
        return self.plan, 3

    def current_best_trajectories(self):
        return self.partial

    def current_best_monitored_trajectory(self):
        return None


@pytest.mark.parametrize(
    "search, expected",
    [
        (_Search(plan=_Path()), (True, True, None)),
        (_Search(plan=_Path(), first_failed_step=25), (True, False, None)),  # a plan that still fails a COLREGS rule
        (_Search(partial=_Path()), (True, False, None)),  # valid for the workbench, not complete
        (_Search(), (False, False, "No trajectory could be planned: no complete plan")),
    ],
)
def test_a_partial_path_is_valid_but_not_complete(search, expected, monkeypatch):
    monkeypatch.setattr(trajectory_generation_worker, "_trajectory_payload", lambda data, monitored: {"trajectories": data.trajectories})
    task = SimpleNamespace(params=TrajectoryGenerationParams(include_monitor_results=False))
    channel = RecordingChannel()
    trajectory_generation_worker._emit_result(channel, task, search, lambda trajectories, iteration: SimpleNamespace(trajectories=trajectories))
    [(payload, valid, complete, error)] = _results(channel)
    assert (valid, complete, error) == expected


def test_previews_are_spaced_from_the_end_of_the_last_one(monkeypatch):
    """Building a preview of a long path can take longer than the interval. Timed from its start, every
    step then published one; the planner is told about a dropped preview so it can offer it again."""
    clock = [100.0]
    captured = {}

    def slow_payload(data, monitored):
        clock[0] += 5.0
        return {"trajectories": data}

    def build_planner(task, scene, others, constants, observer, termination_signal):
        captured["observer"] = observer

    monkeypatch.setattr(trajectory_generation_worker, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(trajectory_generation_worker, "_trajectory_payload", slow_payload)
    monkeypatch.setattr(trajectory_generation_worker, "_make_trajectory_data_factory", lambda content, start, seed: lambda trajectories, iteration: (trajectories, iteration))
    monkeypatch.setattr(trajectory_generation_worker, "_build_planner", build_planner)
    monkeypatch.setattr(trajectory_generation_worker, "_emit_result", lambda *args: None)
    channel = RecordingChannel()
    trajectory_generation_worker.run_trajectory_generation_worker(_task(seed=1), channel)
    observer = captured["observer"]

    assert observer("path", None, 1) is True  # built from 100 to 105
    clock[0] += 0.5
    assert observer("path", None, 2) is False  # half a second after the last one was out
    clock[0] += 0.6
    assert observer("path", None, 3) is True
    assert [payload["trajectories"] for payload, _ in channel.of(TRAJECTORY_PREVIEW_STREAM)] == [("path", 1), ("path", 3)]
