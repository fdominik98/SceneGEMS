"""The worker of an exploration task against a stand-in for the generator: the job document it writes, the progress it relays, the result it emits and how it ends without one."""

import json
import os
import tempfile

import pytest

from scenegems_tool.subsystems.design_space_exploration import design_space_exploration_worker as worker
from scenegems_tool.subsystems.design_space_exploration.design_space_exploration_types import DESIGN_SPACE_STREAM, STOP_MARGIN_S
from scenegems_tool.subsystems.design_space_exploration.design_space_exploration_worker import GeneratorFailed, explore, generator_environment, status_of
from tests.scenegems_tool.subsystems.design_space_exploration.generator_fakes import NAMED_MODEL, STAND_IN_COMMAND, ExplorationChannel, exploration


@pytest.fixture
def task_folders(monkeypatch, tmp_path):
    """The folders the worker makes for its tasks, under the test's own; what is left of them after a task says whether it cleaned up."""
    made = []

    def mkdtemp(prefix=""):
        folder = tmp_path / f"{prefix}{len(made)}"
        folder.mkdir()
        made.append(folder)
        return str(folder)

    monkeypatch.setattr(tempfile, "mkdtemp", mkdtemp)
    return made


def run(task, channel=None, **options):
    channel = channel or ExplorationChannel()
    explore(task, channel, command=STAND_IN_COMMAND, pool_size=1, **options)
    return channel


def test_the_explored_fecs_are_the_tasks_result_with_the_catalogs_names(task_folders):
    channel = run(exploration(seed=7))
    [(message, final)] = channel.of(DESIGN_SPACE_STREAM)
    assert final and (message["error"], message["retryable"]) == (None, False)
    design_space = message["design-space"]
    assert design_space["functional_scenarios"] == [NAMED_MODEL, NAMED_MODEL]
    assert design_space["fecs"] == [{"index": 0, "vessel_count": 3, "obstacle_count": 1}, {"index": 1, "vessel_count": 3, "obstacle_count": 1}]
    assert (design_space["stop_reason"], design_space["complete"], design_space["models_found"], design_space["random_seed"]) == ("exhausted", True, 2, 7)
    assert "models" not in design_space
    assert len(task_folders) == 1 and not task_folders[0].exists(), "the task's folder is gone with the task"


def test_the_generator_gets_the_request_as_its_payload_with_the_tasks_seed_and_no_field_it_does_not_know():
    task = exploration("class A.", seed=41, scopes=("A=1",), scope_overrides=("B=0",), max_models=3, timeout_s=30.0, load_timeout_s=20.0, state_coder_depth=5, status_interval_s=0.5)
    [(message, _)] = run(task).of(DESIGN_SPACE_STREAM)
    assert message["error"] is None, "the stand-in refuses unknown fields, as the generator does"
    assert json.loads(message["design-space"]["message"]) == {
        "problem": "class A.",
        "scopes": ["A=1"],
        "scope_overrides": ["B=0"],
        "random_seed": 41,
        "max_models": 3,
        "timeout_s": 30.0,
        "load_timeout_s": 20.0,
        "state_coder_depth": 5,
        "status_interval_s": 0.5,
    }
    assert message["design-space"]["models_found"] == 3 and not message["design-space"]["complete"]


def test_limits_the_request_leaves_out_are_left_to_the_generator():
    [(message, _)] = run(exploration()).of(DESIGN_SPACE_STREAM)
    assert set(json.loads(message["design-space"]["message"])) == {"problem", "scopes", "scope_overrides", "random_seed", "load_timeout_s", "status_interval_s"}


def test_the_generators_status_lines_are_the_tasks_progress_and_its_other_lines_are_not(capfd):
    channel = run(exploration())
    assert channel.progressed == [("loading the problem", None), ("generating models: 1 of 2 found", 0.5), ("finished: 2 models", 1.0)]
    assert channel.details == [{"phase": "loading"}, {"phase": "generating", "models_found": 1}, {"phase": "finished", "models_found": 2}]
    assert "Loading the problem" in capfd.readouterr().err, "a log line goes to the container's log"


def test_an_error_of_the_generator_is_a_result_that_is_not_retried(task_folders):
    [(message, final)] = run(exploration("// stand-in: error\nclass A extends Missing.")).of(DESIGN_SPACE_STREAM)
    assert final and message == {"design-space": None, "error": "the problem has errors: line 1: no such class Missing", "retryable": False}
    assert not task_folders[0].exists()


@pytest.mark.parametrize(
    "behavior, reason",
    [("crash", "the model generator ended with exit code 3 and left no result"), ("garbage", "neither a result nor an error")],
)
def test_a_generator_that_ends_without_a_result_fails_the_task(task_folders, behavior, reason):
    channel = ExplorationChannel()
    with pytest.raises(GeneratorFailed, match=reason):
        run(exploration(f"// stand-in: {behavior}\nclass A."), channel)
    assert channel.of(DESIGN_SPACE_STREAM) == [] and not task_folders[0].exists()


def test_a_cancelled_exploration_ends_its_generator_and_emits_nothing(task_folders):
    channel = ExplorationChannel(cancel_after=1)  # cancelled once the generator said that it loads
    run(exploration("// stand-in: hang\nclass A."), channel)
    assert channel.of(DESIGN_SPACE_STREAM) == [] and channel.progressed == [("loading the problem", None)]
    assert not task_folders[0].exists(), "the generator is gone: its folder could be removed"


def test_an_exploration_cancelled_as_it_starts_starts_no_generator(task_folders):
    channel = ExplorationChannel()
    channel.cancelled = True
    run(exploration(), channel)
    assert task_folders == [] and channel.emitted == [] and channel.progressed == []


def test_a_generator_that_runs_past_its_own_limits_is_ended_and_fails_the_task(task_folders):
    task = exploration("// stand-in: hang\nclass A.", timeout_s=30.0, load_timeout_s=10.0)
    assert task.run_limit_s == 10.0 + 30.0 + STOP_MARGIN_S
    times = iter([0.0])  # the start; every later look at the clock is past the limit
    with pytest.raises(GeneratorFailed, match="did not end within 100 s"):
        run(task, clock=lambda: next(times, 1000.0))
    assert not task_folders[0].exists()


def test_an_exploration_without_a_time_limit_has_no_limit_of_the_workers_either():
    assert exploration().run_limit_s is None


def test_a_generator_that_cannot_be_started_fails_the_task(task_folders):
    with pytest.raises(OSError):
        explore(exploration(), ExplorationChannel(), command=(os.path.join(os.path.dirname(__file__), "no-such-generator"), "job", "-folder"), pool_size=1)
    assert not task_folders[0].exists()


def test_each_generator_gets_its_share_of_the_containers_memory():
    assert generator_environment(1, {"PATH": "/bin", "JAVA_OPTS": "-Xmx1g"}) == {"PATH": "/bin", "JAVA_OPTS": "-XX:MaxRAMPercentage=75"}
    assert generator_environment(2, {})["JAVA_OPTS"] == "-XX:MaxRAMPercentage=37.5"
    assert generator_environment(3, {})["JAVA_OPTS"] == "-XX:MaxRAMPercentage=25"


def test_the_pool_size_comes_from_the_containers_environment(monkeypatch):
    seen = []
    monkeypatch.setenv("WORKER_COUNT", "3")
    monkeypatch.setattr(worker, "generator_environment", lambda pool_size: seen.append(pool_size) or dict(os.environ))
    explore(exploration(), ExplorationChannel(), command=STAND_IN_COMMAND)
    assert seen == [3]


def test_a_status_line_is_told_from_a_log_line():
    assert status_of('scenegems-status {"message":"generating","progress":0.17,"phase":"generating","models_found":17}') == ("generating", 0.17, {"phase": "generating", "models_found": 17})
    assert status_of('scenegems-status {"message":"loading"}') == ("loading", None, {})
    assert status_of("Loading the problem") is None and status_of("scenegems-status not json") is None and status_of('scenegems-status {"progress":1}') is None


def test_the_pools_worker_explores_its_task_with_the_images_generator(monkeypatch):
    seen = []
    monkeypatch.setattr(worker, "explore", lambda task, channel: seen.append((task.request_id, channel)))
    worker.run_design_space_exploration_worker(exploration(), "channel")
    assert seen == [("r1", "channel")] and worker.GENERATOR_COMMAND == ("generate-models", "job", "-folder")
