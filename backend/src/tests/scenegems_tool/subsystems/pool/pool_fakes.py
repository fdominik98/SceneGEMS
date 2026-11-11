"""A task pool without processes: a worker runs when the test says so, in the test's own thread."""

import queue
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from scenegems_tool.subsystems.pool.pool_task import PoolTask, TaskOutput, TaskState
from scenegems_tool.subsystems.pool.task_pool import TaskPool


class ManualProcess:
    """Stands in for a worker process: alive from start() until the test lets it work (work) or kills it (die)."""

    def __init__(self, target: Callable[..., None], args: Tuple[Any, ...], name: str, daemon: bool):
        self.target = target
        self.args = args
        self.name = name
        self.started = False
        self.ended = False

    def start(self) -> None:
        self.started = True

    def is_alive(self) -> bool:
        return self.started and not self.ended

    def work(self) -> None:
        """Run the worker to its end, as the process would."""
        self.target(*self.args)
        self.ended = True

    def die(self) -> None:
        """End without running the worker's last word: a killed or crashed process."""
        self.ended = True

    terminate = kill = die

    def join(self, timeout: Optional[float] = None) -> None:
        del timeout


class Recorder:
    """Hears a pool: every state change and every message of a worker, in order."""

    def __init__(self) -> None:
        self.states: List[Tuple[str, TaskState, Optional[str]]] = []
        self.outputs: List[Tuple[str, TaskOutput]] = []

    def on_state(self, task: PoolTask, state: TaskState, reason: Optional[str]) -> None:
        self.states.append((task.request_id, state, reason))

    def on_output(self, task: PoolTask, output: TaskOutput) -> None:
        self.outputs.append((task.request_id, output))

    def states_of(self, request_id: str) -> List[TaskState]:
        return [state for request, state, _ in self.states if request == request_id]


class ManualPool:
    """A TaskPool whose workers are ManualProcess: process(request id) is the worker of a started task."""

    def __init__(self, worker: Callable[[PoolTask, Any], None], size: int, recorder: Optional[Recorder] = None):
        self.recorder = recorder or Recorder()
        self.processes: Dict[str, ManualProcess] = {}
        self.pool = TaskPool(worker, size, self.recorder.on_state, self.recorder.on_output, process_factory=self._process, queue_factory=queue.Queue, event_factory=threading.Event)

    def _process(self, target, args, name, daemon) -> ManualProcess:
        process = ManualProcess(target, args, name, daemon)
        self.processes[args[1].request_id] = process  # run_worker's arguments: the worker, the task, ...
        return process

    def process(self, request_id: str) -> ManualProcess:
        return self.processes[request_id]

    def work(self, request_id: str) -> None:
        """Let the task's worker run to its end and the pool take what it handed back."""
        self.process(request_id).work()
        self.pool.step()


def task(request_id: str, seed: int = 7, key: Optional[str] = None) -> PoolTask:
    if key is None:
        return PoolTask(sender="pool", task_uuid=f"uuid-{request_id}", request_id=request_id, seed=seed)
    return KeyedTask(sender="pool", task_uuid=f"uuid-{request_id}", request_id=request_id, seed=seed, key=key)


class KeyedTask(PoolTask):
    """A task with an order key, as a monitoring task of one scenario has."""

    def __init__(self, sender: str, task_uuid: str, request_id: str, seed: int, key: str):
        super().__init__(sender=sender, task_uuid=task_uuid, request_id=request_id, seed=seed)
        object.__setattr__(self, "_key", key)

    @property
    def order_key(self) -> Optional[str]:
        return self._key  # type: ignore[attr-defined]


class RecordingChannel:
    """A worker's channel that keeps what the worker handed back: emitted is (stream, payload, final) in order."""

    def __init__(self, cancelled: bool = False):
        self.cancelled = cancelled
        self.emitted: List[Tuple[str, Any, bool]] = []
        self.progressed: List[Tuple[str, Optional[float]]] = []

    def emit(self, stream: str, payload: Any, final: bool = False) -> None:
        self.emitted.append((stream, payload, final))

    def progress(self, message: str, fraction: Optional[float] = None, detail: Any = None) -> None:
        self.progressed.append((message, fraction))

    def signals(self) -> list:
        return []

    def next_signal(self, timeout_s: float) -> None:
        return None

    def of(self, stream: str) -> List[Tuple[Any, bool]]:
        """The (payload, final) of every message on one stream."""
        return [(payload, final) for name, payload, final in self.emitted if name == stream]


def manual_pool_factory(processes: Dict[str, ManualProcess]) -> Callable[..., TaskPool]:
    """A pool factory for a PoolService whose workers are ManualProcess, kept in processes by request id."""

    def process(target, args, name, daemon) -> ManualProcess:
        made = ManualProcess(target, args, name, daemon)
        processes[args[1].request_id] = made
        return made

    return lambda worker, size, on_state, on_output: TaskPool(worker, size, on_state, on_output, process_factory=process, queue_factory=queue.Queue, event_factory=threading.Event)
