"""A task of a subsystem's pool: what it is, the states it goes through, and what its worker gets.

A request to a subsystem becomes one or more tasks. Every task carries the request's seed (the
first task the seed itself, further ones a seed derived from it), so a request repeats exactly.
A task is received, queued and running, and ends finished, failed or aborted.

The worker of a task runs in a process of its own and talks back through its TaskChannel: it emits
messages on the task's streams (previews, the result), reports progress, reads the signals sent to
the task and sees when the task was cancelled. Standard library only.
"""

import hashlib
import queue
import secrets
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

MAX_SEED = 2**31 - 1

OUTPUT_STREAM = "stream"  # a message on one of the task's streams
OUTPUT_FEEDBACK = "feedback"  # progress of a running task
OUTPUT_ENDED = "ended"  # the worker's last word: how the task ended


class TaskState(str, Enum):
    RECEIVED = "received"  # the subsystem took the request and made the task
    QUEUED = "queued"  # it waits for a free place in the pool, or for an earlier task of its order key
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"
    ABORTED = "aborted"  # cancelled, queued or running

    @property
    def is_final(self) -> bool:
        return self in (TaskState.FINISHED, TaskState.FAILED, TaskState.ABORTED)


@dataclass(frozen=True)
class PoolTask:
    """One task. A subsystem's own task class adds what its worker needs (subsystems/*/..._types.py)."""

    sender: str  # the subsystem's name on the broker
    task_uuid: str
    request_id: str  # the request the task belongs to; a cancel or a signal names it
    seed: int  # the task's seed: every random draw of the worker comes from it

    @property
    def order_key(self) -> Optional[str]:
        """Tasks with the same key never run at the same time: the later one waits for the earlier. None for a task that depends on no other."""
        return None


def draw_seed() -> int:
    """A fresh seed, for a request that names none."""
    return secrets.randbelow(MAX_SEED + 1)


def task_seed(seed: int, index: int) -> int:
    """The seed of the index-th task of a request with this seed: the seed itself for the first, a fixed derivation of it for the others."""
    if index < 0:
        raise ValueError(f"A task index is not negative: {index}")
    if index == 0:
        return seed
    digest = hashlib.sha256(f"{seed}/{index}".encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big") % (MAX_SEED + 1)


@dataclass(frozen=True)
class TaskSignal:
    """A signal sent to a task while it is queued or running (signal-task), other than cancel."""

    name: str
    data: Any = None


@dataclass(frozen=True)
class TaskOutput:
    """What a worker process hands back to the pool: a stream message, progress, or its end."""

    task_uuid: str
    kind: str  # OUTPUT_STREAM, OUTPUT_FEEDBACK or OUTPUT_ENDED
    stream: str = ""
    payload: Any = None
    final: bool = False  # a stream message that is the task's last on that stream: its result
    state: Optional[TaskState] = None  # OUTPUT_ENDED: finished, failed or aborted
    reason: Optional[str] = None  # why a task failed


class TaskChannel:
    """A worker's side of its task: the cancel flag, the signals, and the way out for messages and progress."""

    def __init__(self, task: PoolTask, output_queue: Any, cancel_event: Any, signal_queue: Any):
        self.task = task
        self._output_queue = output_queue
        self._cancel_event = cancel_event
        self._signal_queue = signal_queue

    @property
    def cancelled(self) -> bool:
        return bool(self._cancel_event.is_set())

    def emit(self, stream: str, payload: Any, final: bool = False) -> None:
        """A message on one of the task's streams; final marks the task's result on that stream."""
        self._output_queue.put(TaskOutput(self.task.task_uuid, OUTPUT_STREAM, stream=stream, payload=payload, final=final))

    def progress(self, message: str, fraction: Optional[float] = None, detail: Optional[Dict[str, Any]] = None) -> None:
        self._output_queue.put(TaskOutput(self.task.task_uuid, OUTPUT_FEEDBACK, payload={"message": message, "progress": fraction, "detail": detail}))

    def signals(self) -> List[TaskSignal]:
        """The signals that arrived since the last call, in order; empty when there is none."""
        received: List[TaskSignal] = []
        while True:
            try:
                received.append(self._signal_queue.get_nowait())
            except queue.Empty:
                return received

    def next_signal(self, timeout_s: float) -> Optional[TaskSignal]:
        """The next signal, waiting up to timeout_s for it; None when none came."""
        try:
            return self._signal_queue.get(timeout=timeout_s)
        except queue.Empty:
            return None


def run_worker(worker: Any, task: PoolTask, output_queue: Any, cancel_event: Any, signal_queue: Any) -> None:
    """What a worker process runs: the subsystem's worker for the task, and then how the task ended.

    A worker that returns ended its task: finished, or aborted when the task was cancelled meanwhile.
    A worker that raises failed it, with the error as the reason. A process that dies without this
    last word is noticed by the pool (task_pool.py).
    """
    channel = TaskChannel(task, output_queue, cancel_event, signal_queue)
    try:
        worker(task, channel)
    except BaseException as error:  # the process ends here either way, and the pool has to hear why
        reason = f"{type(error).__name__}: {error}" if str(error) else type(error).__name__
        output_queue.put(TaskOutput(task.task_uuid, OUTPUT_ENDED, state=TaskState.FAILED, reason=reason))
        return
    output_queue.put(TaskOutput(task.task_uuid, OUTPUT_ENDED, state=TaskState.ABORTED if channel.cancelled else TaskState.FINISHED))
