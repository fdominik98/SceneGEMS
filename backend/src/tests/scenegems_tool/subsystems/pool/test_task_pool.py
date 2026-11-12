"""The queue and the pool of a subsystem: arrival order, the pool's size, order keys, cancel, signals and workers that die."""

import pytest

from scenegems_tool.subsystems.pool.pool_task import TaskState
from scenegems_tool.subsystems.pool.task_pool import LOST_WORKER, TaskPool
from tests.scenegems_tool.subsystems.pool.pool_fakes import ManualPool, task

QUEUED, RUNNING, FINISHED, FAILED, ABORTED = TaskState.QUEUED, TaskState.RUNNING, TaskState.FINISHED, TaskState.FAILED, TaskState.ABORTED


def echo(task, channel):
    """A worker that reports progress, answers each signal it got and returns its result."""
    channel.progress("working", 0.5)
    for signal in channel.signals():
        channel.emit("answers", (signal.name, signal.data))
    channel.emit("result", f"result of {task.request_id} with seed {task.seed}", final=True)


def broken(task, channel):
    raise RuntimeError("the search cannot start")


def test_a_task_is_queued_runs_and_finishes_with_what_its_worker_handed_back():
    manual = ManualPool(echo, size=1)
    manual.pool.submit(task("a", seed=42))
    assert manual.recorder.states_of("a") == [QUEUED] and manual.pool.tasks(QUEUED) == [task("a", seed=42)]
    manual.pool.step()
    assert manual.recorder.states_of("a") == [QUEUED, RUNNING] and manual.process("a").name == "task_a"
    manual.work("a")
    assert manual.recorder.states_of("a") == [QUEUED, RUNNING, FINISHED] and manual.pool.tasks() == []
    feedback, result = (output for _, output in manual.recorder.outputs)
    assert feedback.payload == {"message": "working", "progress": 0.5, "detail": None}
    assert (result.stream, result.payload, result.final) == ("result", "result of a with seed 42", True), "the task's seed reached its worker"


def test_at_most_as_many_tasks_run_as_the_pool_is_large_and_the_others_wait_in_arrival_order():
    manual = ManualPool(echo, size=2)
    for request_id in ("a", "b", "c", "d"):
        manual.pool.submit(task(request_id))
    manual.pool.step()
    assert [t.request_id for t in manual.pool.tasks(RUNNING)] == ["a", "b"] and [t.request_id for t in manual.pool.tasks(QUEUED)] == ["c", "d"]
    manual.work("b")
    assert [t.request_id for t in manual.pool.tasks(RUNNING)] == ["a", "c"], "the place b left goes to the task that waited longest"
    manual.work("a")
    manual.work("c")
    manual.work("d")
    assert [manual.recorder.states_of(request_id)[-1] for request_id in "abcd"] == [FINISHED] * 4


def test_two_tasks_of_one_order_key_never_run_together_while_another_key_goes_ahead():
    manual = ManualPool(echo, size=3)
    manual.pool.submit(task("first", key="scenario 1"))
    manual.pool.submit(task("second", key="scenario 1"))
    manual.pool.submit(task("other", key="scenario 2"))
    manual.pool.step()
    assert [t.request_id for t in manual.pool.tasks(RUNNING)] == ["first", "other"], "a free place is not enough: the second series waits for the first"
    manual.pool.step()
    assert manual.recorder.states_of("second") == [QUEUED]
    manual.work("first")
    assert manual.recorder.states_of("second") == [QUEUED, RUNNING]


def test_a_cancel_stops_only_its_request_a_queued_task_never_starts_and_a_running_one_ends_aborted():
    manual = ManualPool(echo, size=1)
    manual.pool.submit(task("running"))
    manual.pool.submit(task("waiting"))
    manual.pool.submit(task("kept"))
    manual.pool.step()
    assert manual.pool.cancel_request("waiting") == 1 and manual.recorder.states_of("waiting") == [QUEUED, ABORTED]
    assert manual.pool.cancel_request("running") == 1 and manual.recorder.states_of("running") == [QUEUED, RUNNING], "the worker has to notice first"
    manual.work("running")
    assert manual.recorder.states_of("running")[-1] == ABORTED, "a worker that returns after its cancel aborted its task"
    assert manual.recorder.states_of("kept") == [QUEUED, RUNNING] and "waiting" not in manual.processes
    assert manual.pool.cancel_request("unknown") == 0


def test_a_worker_that_raises_fails_its_task_with_the_error_as_the_reason():
    manual = ManualPool(broken, size=1)
    manual.pool.submit(task("a"))
    manual.pool.step()
    manual.work("a")
    assert manual.recorder.states[-1] == ("a", FAILED, "RuntimeError: the search cannot start")


def test_a_worker_that_dies_without_its_last_word_fails_its_task_and_frees_its_place():
    manual = ManualPool(echo, size=1)
    manual.pool.submit(task("lost"))
    manual.pool.submit(task("next"))
    manual.pool.step()
    manual.process("lost").die()
    manual.pool.step()
    assert manual.recorder.states[-2:] == [("lost", FAILED, LOST_WORKER), ("next", RUNNING, None)], "nothing waits for a task whose worker is gone"


def test_a_killed_worker_of_a_cancelled_task_is_an_aborted_task_not_a_failed_one():
    manual = ManualPool(echo, size=1)
    manual.pool.submit(task("a"))
    manual.pool.step()
    manual.pool.cancel_request("a")
    manual.process("a").die()
    manual.pool.step()
    assert manual.recorder.states[-1] == ("a", ABORTED, None)


def test_a_signal_reaches_the_tasks_of_its_request_queued_or_running():
    manual = ManualPool(echo, size=1)
    manual.pool.submit(task("a"))
    manual.pool.submit(task("b"))
    manual.pool.step()
    assert manual.pool.signal("b", "scenes", [1, 2]) == 1, "b still waits: its signals wait with it"
    assert manual.pool.signal("a", "start") == 1 and manual.pool.signal("unknown", "start") == 0
    manual.work("a")
    manual.work("b")
    answers = [(request, output.payload) for request, output in manual.recorder.outputs if output.stream == "answers"]
    assert answers == [("a", ("start", None)), ("b", ("scenes", [1, 2]))]


def test_a_late_word_of_a_task_that_already_ended_is_dropped():
    manual = ManualPool(echo, size=1)
    manual.pool.submit(task("a"))
    manual.pool.step()
    manual.process("a").die()
    manual.pool.step()
    states = list(manual.recorder.states)
    manual.process("a").target(*manual.process("a").args)  # the worker's messages arrive after all
    manual.pool.step()
    assert manual.recorder.states == states and manual.recorder.outputs == []


def test_stop_ends_every_worker_and_drops_the_tasks():
    manual = ManualPool(echo, size=1)
    manual.pool.submit(task("a"))
    manual.pool.submit(task("b"))
    manual.pool.step()
    manual.pool.stop()
    assert manual.pool.tasks() == [] and not manual.process("a").is_alive()


def test_a_pool_holds_a_task_once_and_runs_at_least_one():
    manual = ManualPool(echo, size=1)
    manual.pool.submit(task("a"))
    with pytest.raises(ValueError, match="already holds"):
        manual.pool.submit(task("a"))
    with pytest.raises(ValueError, match="at least one"):
        TaskPool(echo, 0, lambda *_: None, lambda *_: None)
