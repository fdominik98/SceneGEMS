"""The task pool with real worker processes: a task, its channel and its signals cross the process boundary."""

import multiprocessing
import time

import pytest

from scenegems_tool.subsystems.pool.pool_task import PoolTask, TaskState
from scenegems_tool.subsystems.pool.task_pool import TaskPool
from tests.scenegems_tool.subsystems.pool.pool_fakes import Recorder

DEADLINE_S = 60.0  # a safety net: the pool is stepped until the tasks ended, however long a process takes to start


def answer(task, channel):
    """Runs in the worker process: waits for its signal, then answers with it and the task's seed."""
    signal = channel.next_signal(DEADLINE_S)
    channel.progress("answering", 0.5)
    channel.emit("result", {"seed": task.seed, "signal": None if signal is None else (signal.name, signal.data), "cancelled": channel.cancelled}, final=True)


def crash(task, channel):
    raise RuntimeError("no result for this one")


def step_until(pool: TaskPool, recorder: Recorder, done) -> None:
    deadline = time.monotonic() + DEADLINE_S
    while not done():
        assert time.monotonic() < deadline, f"the tasks did not end in time: {recorder.states}"
        pool.step(wait_s=0.2)


@pytest.mark.slow
def test_tasks_run_in_processes_of_their_own_and_hand_back_through_the_pool():
    context = multiprocessing.get_context("spawn")  # as a subsystem's container starts its workers
    recorder = Recorder()
    pool = TaskPool(answer, 2, recorder.on_state, recorder.on_output, process_factory=context.Process, queue_factory=context.Queue, event_factory=context.Event)
    try:
        pool.submit(PoolTask(sender="pool", task_uuid="u1", request_id="r1", seed=41))
        pool.submit(PoolTask(sender="pool", task_uuid="u2", request_id="r2", seed=42))
        pool.signal("r1", "start", {"speed": 10})
        pool.signal("r2", "start")
        step_until(pool, recorder, lambda: len([state for _, state, _ in recorder.states if state.is_final]) == 2)
    finally:
        pool.stop()
    assert recorder.states_of("r1") == [TaskState.QUEUED, TaskState.RUNNING, TaskState.FINISHED] and recorder.states_of("r2")[-1] == TaskState.FINISHED
    results = {request: output.payload for request, output in recorder.outputs if output.stream == "result"}
    assert results == {"r1": {"seed": 41, "signal": ("start", {"speed": 10}), "cancelled": False}, "r2": {"seed": 42, "signal": ("start", None), "cancelled": False}}
    assert [output.payload["message"] for _, output in recorder.outputs if output.kind == "feedback"] == ["answering", "answering"]


@pytest.mark.slow
def test_a_worker_process_that_raises_fails_its_task_with_the_reason():
    context = multiprocessing.get_context("spawn")
    recorder = Recorder()
    pool = TaskPool(crash, 1, recorder.on_state, recorder.on_output, process_factory=context.Process, queue_factory=context.Queue, event_factory=context.Event)
    try:
        pool.submit(PoolTask(sender="pool", task_uuid="u1", request_id="r1", seed=1))
        step_until(pool, recorder, lambda: any(state.is_final for _, state, _ in recorder.states))
    finally:
        pool.stop()
    assert recorder.states[-1] == ("r1", TaskState.FAILED, "RuntimeError: no result for this one")
