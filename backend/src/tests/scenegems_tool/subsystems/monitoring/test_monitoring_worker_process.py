"""The monitoring worker in a process of its own: the task, the scenes of its signals and its verdict cross the process boundary."""

import multiprocessing
import time

import pytest

from scenegems_tool.subsystems.monitoring.monitoring_types import CLOSE_SIGNAL, MONITOR_RESULT_STREAM, MONITORED_SCENE_STREAM, SCENES_SIGNAL, MonitorScenarioTask
from scenegems_tool.subsystems.monitoring.monitoring_worker import run_monitoring_worker
from scenegems_tool.subsystems.monitoring.rule_outcomes import RuleOutcomes
from scenegems_tool.subsystems.pool.pool_task import TaskState
from scenegems_tool.subsystems.pool.task_pool import TaskPool
from tests.concrete_level.colregs_monitoring.monitor_runs import monitored_run
from tests.scenegems_tool.subsystems.pool.pool_fakes import Recorder

DEADLINE_S = 120.0  # a safety net: the pool is stepped until the task ended, however long the process takes to start
STEPS = 6


@pytest.mark.slow
def test_a_series_is_judged_in_a_worker_process_of_the_pool():
    context = multiprocessing.get_context("spawn")  # as the subsystem's container starts its workers
    reference = monitored_run((200.0, -200.0), STEPS)
    scenes = [result.scene.to_dict() for result in reference]
    recorder = Recorder()
    pool = TaskPool(run_monitoring_worker, 1, recorder.on_state, recorder.on_output, process_factory=context.Process, queue_factory=context.Queue, event_factory=context.Event)
    try:
        pool.submit(MonitorScenarioTask(sender="monitoring-subsystem", task_uuid="u1", request_id="r1", seed=3, scenario_id="case-1#run0", time_step=1, include_frames=True))
        pool.signal("r1", SCENES_SIGNAL, {"index": 0, "first-timestamp": 0, "scenes": scenes[:4]})
        pool.signal("r1", SCENES_SIGNAL, {"index": 1, "first-timestamp": 4, "scenes": scenes[4:]})
        pool.signal("r1", CLOSE_SIGNAL, {"batches": 2})
        deadline = time.monotonic() + DEADLINE_S
        while not any(state.is_final for _, state, _ in recorder.states):
            assert time.monotonic() < deadline, f"the series did not end in time: {recorder.states}"
            pool.step(wait_s=0.2)
    finally:
        pool.stop()
    assert recorder.states_of("r1") == [TaskState.QUEUED, TaskState.RUNNING, TaskState.FINISHED]
    expected = RuleOutcomes()
    for result in reference:
        expected.add(result)
    [verdict] = [output.payload for _, output in recorder.outputs if output.stream == MONITOR_RESULT_STREAM]
    assert (verdict["scenes"], verdict["monitored-scenes"], verdict["batches"], verdict["summary"]) == (STEPS, STEPS, 2, expected.summary())
    frames = [frame for _, output in recorder.outputs if output.stream == MONITORED_SCENE_STREAM for frame in output.payload["monitored-frames"]]
    assert [frame["timestamp"] for frame in frames] == list(range(STEPS))
