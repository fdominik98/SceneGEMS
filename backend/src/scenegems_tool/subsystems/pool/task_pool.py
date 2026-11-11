"""The queue and the pool of a subsystem: tasks wait in arrival order and at most `size` of them run at once.

Every running task has a worker process of its own. A task starts when a place in the pool is free
and no running task has its order key (pool_task.PoolTask.order_key): tasks that depend on each
other's order run one after the other, all others side by side.

The pool is stepped: step() takes what the workers handed back, notices workers that ended, and
starts the tasks that may start. A subsystem's container steps it on a thread (start, stop); a test
steps it itself. Whoever owns the pool hears every state change (on_state) and every message of a
worker (on_output) from the thread that steps it.

A worker that ends without saying how (a process that was killed, or crashed hard) fails its task:
nothing waits for a task whose worker is gone.
"""

import logging
import multiprocessing
import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from scenegems_tool.subsystems.pool.pool_task import OUTPUT_ENDED, PoolTask, TaskOutput, TaskSignal, TaskState, run_worker

_logger = logging.getLogger(__name__)

Worker = Callable[[PoolTask, Any], None]  # (task, channel): runs in the task's worker process
StateListener = Callable[[PoolTask, TaskState, Optional[str]], None]  # (task, its new state, why it failed)
OutputListener = Callable[[PoolTask, TaskOutput], None]

STEP_WAIT_S = 0.05  # how long a step of the pool's own thread waits for a worker's next message
TERMINATE_JOIN_S = 2.0
LOST_WORKER = "the worker process ended without a result"


@dataclass
class _Entry:
    task: PoolTask
    state: TaskState
    cancel_event: Any
    signal_queue: Any
    process: Any = None


class TaskPool:
    def __init__(
        self,
        worker: Worker,
        size: int,
        on_state: StateListener,
        on_output: OutputListener,
        *,
        process_factory: Callable[..., Any] = multiprocessing.Process,
        queue_factory: Callable[[], Any] = multiprocessing.Queue,
        event_factory: Callable[[], Any] = multiprocessing.Event,
    ):
        if size < 1:
            raise ValueError(f"A pool runs at least one task at once, got {size}")
        self.worker = worker
        self.size = size
        self._on_state = on_state
        self._on_output = on_output
        self._process_factory = process_factory
        self._queue_factory = queue_factory
        self._event_factory = event_factory
        self._output_queue = queue_factory()
        self._entries: Dict[str, _Entry] = {}  # by task uuid: queued and running tasks, in arrival order
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # What the owner asks

    def submit(self, task: PoolTask) -> None:
        """Queue a task; it starts at the next step that has a place for it."""
        with self._lock:
            if task.task_uuid in self._entries:
                raise ValueError(f"The pool already holds task {task.task_uuid}")
            self._entries[task.task_uuid] = _Entry(task, TaskState.QUEUED, self._event_factory(), self._queue_factory())
        self._on_state(task, TaskState.QUEUED, None)

    def cancel_request(self, request_id: str) -> int:
        """Cancel the tasks of a request: a queued one never starts, a running one is told to stop. Returns how many it holds."""
        with self._lock:
            entries = [entry for entry in self._entries.values() if entry.task.request_id == request_id]
            queued = [entry for entry in entries if entry.state == TaskState.QUEUED]
            for entry in entries:
                entry.cancel_event.set()
            for entry in queued:
                del self._entries[entry.task.task_uuid]
        for entry in queued:
            self._on_state(entry.task, TaskState.ABORTED, None)
        return len(entries)

    def signal(self, request_id: str, name: str, data: Any = None) -> int:
        """Hand a signal to the tasks of a request, queued or running; a worker reads it from its channel. Returns how many got it."""
        with self._lock:
            entries = [entry for entry in self._entries.values() if entry.task.request_id == request_id]
        for entry in entries:
            entry.signal_queue.put(TaskSignal(name, data))
        return len(entries)

    def tasks(self, state: Optional[TaskState] = None) -> List[PoolTask]:
        """The tasks the pool holds, in arrival order; only those in the state when one is given."""
        with self._lock:
            return [entry.task for entry in self._entries.values() if state is None or entry.state == state]

    # Stepping

    def step(self, wait_s: float = 0.0) -> None:
        """One round: the workers' messages, the workers that ended, the tasks that may start. Waits up to wait_s for a first message."""
        self._drain(wait_s)
        self._reap()
        self._start_waiting()

    def _drain(self, wait_s: float = 0.0) -> None:
        while True:
            try:
                output = self._output_queue.get(timeout=wait_s) if wait_s > 0 else self._output_queue.get_nowait()
            except queue.Empty:
                return
            wait_s = 0.0
            self._take(output)

    def _take(self, output: TaskOutput) -> None:
        with self._lock:
            entry = self._entries.get(output.task_uuid)
            if entry is None:
                return  # a task that already ended: a late word of a worker that was cancelled or lost
            if output.kind == OUTPUT_ENDED:
                del self._entries[output.task_uuid]
        if output.kind == OUTPUT_ENDED:
            self._on_state(entry.task, output.state or TaskState.FAILED, output.reason)
        else:
            self._on_output(entry.task, output)

    def _reap(self) -> None:
        """Fail the tasks whose worker is gone without its last word."""
        with self._lock:
            gone = [entry for entry in self._entries.values() if entry.state == TaskState.RUNNING and entry.process is not None and not entry.process.is_alive()]
        if not gone:
            return
        self._drain()  # a worker's last word may have arrived since the messages were read
        lost = []
        with self._lock:
            for entry in gone:
                if self._entries.pop(entry.task.task_uuid, None) is not None:
                    lost.append(entry)
        for entry in lost:
            cancelled = bool(entry.cancel_event.is_set())
            self._on_state(entry.task, TaskState.ABORTED if cancelled else TaskState.FAILED, None if cancelled else LOST_WORKER)

    def _start_waiting(self) -> None:
        started = []
        with self._lock:
            running = [entry for entry in self._entries.values() if entry.state == TaskState.RUNNING]
            busy_keys = {entry.task.order_key for entry in running if entry.task.order_key is not None}
            free = self.size - len(running)
            for entry in self._entries.values():
                if free <= 0:
                    break
                if entry.state != TaskState.QUEUED or entry.task.order_key in busy_keys:
                    continue
                entry.process = self._process_factory(
                    target=run_worker,
                    args=(self.worker, entry.task, self._output_queue, entry.cancel_event, entry.signal_queue),
                    name=f"task_{entry.task.request_id}",
                    daemon=True,
                )
                entry.state = TaskState.RUNNING
                if entry.task.order_key is not None:
                    busy_keys.add(entry.task.order_key)
                free -= 1
                started.append(entry)
        for entry in started:
            entry.process.start()
            self._on_state(entry.task, TaskState.RUNNING, None)

    # The pool's own thread, in a subsystem's container

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="task_pool", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.step(STEP_WAIT_S)
            except Exception:
                _logger.exception("A step of the task pool failed; continuing")

    def stop(self) -> None:
        """Stop the pool's thread and every worker; the tasks it held are dropped without a word."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=TERMINATE_JOIN_S)
            self._thread = None
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
        for entry in entries:
            entry.cancel_event.set()
        for entry in entries:
            process = entry.process
            if process is None or not process.is_alive():
                continue
            process.terminate()
            process.join(timeout=TERMINATE_JOIN_S)
            if process.is_alive():
                process.kill()
                process.join(timeout=1.0)
