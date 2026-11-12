"""The monitoring subsystem as a run's series sees it, answering at once: its real service and worker logic behind a pool client that needs no broker, no queue and no thread.

A run waits for its series' answers in the middle of the run, so a test needs the answers to be there when the
run asks. SynchronousPool judges a batch inside the publish that sent it: the request goes through the real
service's make_tasks, the batches through the real worker's series, and the messages get the real service's
form. `silent` and `fail_at` make it a pool that does not answer or whose task fails.
"""

from typing import Any, Dict, List, Optional, Tuple

from scenegems_tool.messaging.mqtt_monitor_service import MqttMonitoringService
from scenegems_tool.subsystems.monitoring.monitoring_worker import SeriesError, _FollowedSeries
from scenegems_tool.subsystems.pool.pool_task import TaskState
from tests.scenegems_tool.messaging.generation_fakes import CONNECTION, GEOFENCE, offline
from tests.scenegems_tool.subsystems.pool.pool_fakes import manual_pool_factory


class _Channel:
    """The worker's channel of a series, publishing straight to the requester."""

    cancelled = False

    def __init__(self, pool: "SynchronousPool"):
        self._pool = pool

    def emit(self, stream: str, payload: Any, final: bool = False) -> None:
        self._pool.publish(stream, payload, final)

    def progress(self, message: str, fraction: Optional[float] = None, detail: Any = None) -> None:
        self._pool.feedback.append((message, detail))


class SynchronousPool:
    """The pool client of a monitoring subsystem that judges inside the call that sent a batch."""

    is_connected = True
    is_heartbeat_valid = True

    def __init__(self, *, silent: bool = False, fail_at: Optional[int] = None, heartbeat: bool = True):
        self.service = offline(MqttMonitoringService(CONNECTION, GEOFENCE, 1, pool_factory=manual_pool_factory({})))
        self.silent = silent  # takes everything and answers nothing after the start
        self.fail_at = fail_at  # the batch at which the series' task fails
        self.is_heartbeat_valid = heartbeat
        self.requests: List[Tuple[str, str, Dict[str, Any], int]] = []
        self.signals: List[Tuple[str, Any]] = []
        self.cancels: List[str] = []
        self.feedback: List[Tuple[str, Any]] = []
        self.connected = False
        self.disconnected = False
        self._series: Optional[_FollowedSeries] = None
        self._task: Any = None

    def client_of(self, *, streams=(), on_state=None, on_stream=None) -> "SynchronousPool":
        self.streams, self.on_state, self.on_stream = streams, on_state, on_stream
        return self

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.disconnected = True

    def publish(self, stream: str, payload: Any, final: bool) -> None:
        if not self.silent:
            self.on_stream(stream, {"request-id": self._task.request_id, **self.service.stream_message(self._task, stream, payload, final)})

    def publish_start_task(self, task_name: str, request_id: str, params: Dict[str, Any], seed: int) -> str:
        self.requests.append((task_name, request_id, dict(params), seed))
        [self._task] = self.service.make_tasks(f"u-{request_id}", request_id, seed, params)
        self._series = _FollowedSeries(self._task, _Channel(self))
        self.on_state(request_id, TaskState.QUEUED, None, seed)
        self.on_state(request_id, TaskState.RUNNING, None, seed)
        return f"u-{request_id}"

    def publish_signal(self, name: str, request_id: str, data: Any = None) -> None:
        self.signals.append((name, data))
        if self.silent:
            return
        if name == "scenes" and self.fail_at is not None and data["index"] >= self.fail_at:
            self.on_state(request_id, TaskState.FAILED, "the worker process ended without a result", self._task.seed)
            return
        try:
            if name == "scenes":
                self._series.take(data)
            elif name == "close":
                self._series.close(data or {})
                self.on_state(request_id, TaskState.FINISHED, None, self._task.seed)
        except SeriesError as error:
            self.on_state(request_id, TaskState.FAILED, f"SeriesError: {error}", self._task.seed)

    def publish_cancel(self, request_id: str) -> None:
        self.cancels.append(request_id)

    def batches(self) -> List[Dict[str, Any]]:
        return [data for name, data in self.signals if name == "scenes"]
