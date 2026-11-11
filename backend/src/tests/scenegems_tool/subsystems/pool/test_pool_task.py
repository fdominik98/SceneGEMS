"""A pool task: its states, the seeds of a request's tasks, and what a worker hands back through its channel."""

import queue
import threading

import pytest

from scenegems_tool.subsystems.pool.pool_task import MAX_SEED, OUTPUT_ENDED, PoolTask, TaskChannel, TaskSignal, TaskState, draw_seed, run_worker, task_seed

TASK = PoolTask(sender="pool", task_uuid="uuid-1", request_id="request-1", seed=11)


def test_a_task_ends_finished_failed_or_aborted():
    assert [state.value for state in TaskState] == ["received", "queued", "running", "finished", "failed", "aborted"]
    assert [state for state in TaskState if state.is_final] == [TaskState.FINISHED, TaskState.FAILED, TaskState.ABORTED]
    assert TASK.order_key is None, "a task depends on no other unless its class says so"


def test_the_first_task_of_a_request_has_the_requests_seed_and_the_others_seeds_derived_from_it():
    assert task_seed(42, 0) == 42
    derived = [task_seed(42, index) for index in range(1, 6)]
    assert derived == [task_seed(42, index) for index in range(1, 6)], "the same request gives the same seeds"
    assert len(set(derived)) == 5 and 42 not in derived and all(0 <= seed <= MAX_SEED for seed in derived)
    assert task_seed(43, 1) != task_seed(42, 1)
    with pytest.raises(ValueError):
        task_seed(42, -1)
    assert 0 <= draw_seed() <= MAX_SEED


def channel_of(cancelled: bool = False):
    outputs, signals, cancel = queue.Queue(), queue.Queue(), threading.Event()
    if cancelled:
        cancel.set()
    return TaskChannel(TASK, outputs, cancel, signals), outputs, signals, cancel


def test_a_worker_emits_stream_messages_and_progress_and_reads_its_signals():
    channel, outputs, signals, cancel = channel_of()
    channel.emit("preview", {"step": 1})
    channel.emit("result", {"step": 2}, final=True)
    channel.progress("searching", 0.25, {"phase": "running"})
    preview, result, feedback = outputs.get_nowait(), outputs.get_nowait(), outputs.get_nowait()
    assert (preview.task_uuid, preview.stream, preview.payload, preview.final) == ("uuid-1", "preview", {"step": 1}, False)
    assert result.final and feedback.payload == {"message": "searching", "progress": 0.25, "detail": {"phase": "running"}}
    assert channel.signals() == [] and channel.next_signal(0.0) is None
    signals.put(TaskSignal("start"))
    signals.put(TaskSignal("observe", {"speed": 10}))
    assert channel.signals() == [TaskSignal("start"), TaskSignal("observe", {"speed": 10})]
    assert not channel.cancelled
    cancel.set()
    assert channel.cancelled


def last_word(worker, cancelled: bool = False):
    _, outputs, signals, cancel = channel_of(cancelled)
    run_worker(worker, TASK, outputs, cancel, signals)
    words = []
    while not outputs.empty():
        words.append(outputs.get_nowait())
    return words[-1]


def test_a_worker_that_returns_finished_its_task_or_aborted_it_when_it_was_cancelled():
    ended = last_word(lambda task, channel: channel.emit("result", 1, final=True))
    assert (ended.kind, ended.state, ended.reason) == (OUTPUT_ENDED, TaskState.FINISHED, None)
    assert last_word(lambda task, channel: None, cancelled=True).state == TaskState.ABORTED


def test_a_worker_that_raises_failed_its_task_and_says_why():
    def worker(task, channel):
        raise ValueError("no scene in the request")

    ended = last_word(worker)
    assert (ended.state, ended.reason) == (TaskState.FAILED, "ValueError: no scene in the request")

    def silent(task, channel):
        raise KeyboardInterrupt()

    assert last_word(silent).reason == "KeyboardInterrupt"
