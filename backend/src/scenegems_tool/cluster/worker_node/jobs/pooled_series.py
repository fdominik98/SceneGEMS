"""A run's series of scenes in the worker node's monitoring subsystem: the run as a requester of the monitoring pool.

The run's runner container sends one monitor-scenario request for the run (its job id is the scenario), then
the scenes as scenes signals in time order, and a close at the end (subsystems/monitoring/monitoring_types.py).
Scenes are collected into batches of SCENES_PER_BATCH and sent without waiting, so the monitor does not slow the
run. The series waits for the pool only where the run needs an answer now:

    every_rule_decided   sends what is collected and waits until it is judged (a run that stops early asks each step)
    latest_frame         sends what is collected, asking for its frames, and waits for them
    close                sends the rest and the close, and waits for the verdict

A series whose task fails, or that the pool does not answer in time, fails the run's attempt, which may be
retried. A run that ends without its verdict cancels its series (abandon); the simulation subsystem cancels it
as well when the run's task ends, in case the runner was killed.
"""

import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.jobs.pool_client import request_id_of
from scenegems_tool.subsystems.monitoring.monitoring_types import (
    CLOSE_SIGNAL,
    MONITOR_RESULT_STREAM,
    MONITOR_SCENARIO_TASK,
    MONITORED_SCENE_STREAM,
    SCENES_PER_BATCH,
    SCENES_SIGNAL,
    live_series_request_id,
)
from scenegems_tool.subsystems.pool.pool_task import TaskState

START_TIMEOUT_S = 180.0  # for the pool's heartbeat and for the series' task to leave the queue
REPLY_TIMEOUT_S = 120.0  # for an answer the run waits for
_POLL_S = 0.05


class PooledSeries:
    def __init__(
        self,
        client_of: Callable[..., Any],
        request_id: str,
        scenario_id: str,
        time_step: int,
        colregs_constraints_content: Optional[str],
        *,
        seed: int = 0,
        start_timeout_s: float = START_TIMEOUT_S,
        reply_timeout_s: float = REPLY_TIMEOUT_S,
        clock: Callable[[], float] = time.monotonic,
    ):
        """client_of(streams=, on_state=, on_stream=) makes the pool client of the monitoring subsystem (messaging/mqtt_pool_client.py)."""
        self.request_id = request_id
        self.time_step = time_step
        self._reply_timeout_s = reply_timeout_s
        self._clock = clock
        self._changed = threading.Condition()
        self._state: Optional[TaskState] = None
        self._reason: Optional[str] = None
        self._judged = 0  # batches the pool judged
        self._decided = False  # every rule decided, as of the batch judged last
        self._frames: Dict[int, List[Dict[str, Any]]] = {}  # the frames of the batches that asked for them and are not taken yet
        self._verdict: Optional[Dict[str, Any]] = None
        self._pending: List[Dict[str, Any]] = []  # scenes collected for the next batch
        self._sent = 0  # batches sent
        self._sent_scenes = 0
        self._latest_batch: Optional[int] = None  # the batch that holds the scene added last, once it is sent
        self._client = client_of(streams=(MONITORED_SCENE_STREAM, MONITOR_RESULT_STREAM), on_state=self._on_state, on_stream=self._on_stream)
        self._client.connect()
        try:
            deadline = clock() + start_timeout_s
            while not (self._client.is_connected and self._client.is_heartbeat_valid):
                if clock() > deadline:
                    raise JobFailed(f"The monitoring pool sent no heartbeat within {start_timeout_s:g} s", retryable=True)
                time.sleep(_POLL_S)
            params = {"scenario-id": scenario_id, "time-step": time_step, "colregs-constraints-content": colregs_constraints_content, "include-frames": False}
            self._client.publish_start_task(MONITOR_SCENARIO_TASK, request_id, params, seed)
            self._wait(lambda: self._state is not None and self._state != TaskState.RECEIVED and self._state != TaskState.QUEUED, "start the run's series", start_timeout_s)
        except BaseException:
            self.abandon()
            raise

    # What the pool says, on the client's thread

    def _on_state(self, request_id: str, state: TaskState, reason: Optional[str], seed: Optional[int]) -> None:
        del seed
        if request_id != self.request_id:
            return
        with self._changed:
            self._state, self._reason = state, reason
            self._changed.notify_all()

    def _on_stream(self, stream: str, message: Dict[str, Any]) -> None:
        if message.get("request-id") != self.request_id:
            return
        with self._changed:
            if stream == MONITORED_SCENE_STREAM:
                index = int(message["index"])
                if index >= self._judged:
                    self._judged = index + 1
                    self._decided = bool(message.get("every-rule-decided", False))
                if message.get("monitored-frames"):
                    self._frames[index] = list(message["monitored-frames"])
            elif stream == MONITOR_RESULT_STREAM:
                self._verdict = dict(message)
            self._changed.notify_all()

    def _wait(self, reached: Callable[[], bool], what: str, timeout_s: Optional[float] = None) -> None:
        """Block until reached() holds; JobFailed when the series' task ended badly or the pool does not answer in time."""
        timeout_s = self._reply_timeout_s if timeout_s is None else timeout_s
        with self._changed:
            self._changed.wait_for(lambda: reached() or self._state in (TaskState.FAILED, TaskState.ABORTED), timeout=timeout_s)
            if reached():
                return
            if self._state in (TaskState.FAILED, TaskState.ABORTED):
                ending = "was aborted" if self._state == TaskState.ABORTED else "failed"
                raise JobFailed(f"The run's series in the monitoring pool {ending}" + (f": {self._reason}" if self._reason else ""), retryable=True)
            raise JobFailed(f"The monitoring pool did not {what} within {timeout_s:g} s", retryable=True)

    # What the run asks, on the run's thread

    def add(self, scene: Any) -> None:
        if len(self._pending) >= SCENES_PER_BATCH:
            self._send(frames=False)  # a full batch goes when the next scene comes, so the scene added last is always still collected
        self._pending.append(scene.to_dict())
        self._latest_batch = None

    def _send(self, frames: bool) -> Optional[int]:
        """Send the collected scenes as the next batch; its index, or None when nothing is collected."""
        if not self._pending:
            return None
        index = self._sent
        self._client.publish_signal(SCENES_SIGNAL, self.request_id, {"index": index, "first-timestamp": self._sent_scenes * self.time_step, "scenes": self._pending, "frames": frames})
        self._sent += 1
        self._sent_scenes += len(self._pending)
        self._pending = []
        self._latest_batch = index
        return index

    def _judged_all(self) -> None:
        sent = self._sent
        self._wait(lambda: self._judged >= sent, "judge the run's scenes")

    def every_rule_decided(self) -> bool:
        self._send(frames=True)  # asked each step by a run that may stop here: its observers get this step's frame from the same answer
        self._judged_all()
        with self._changed:
            return self._decided

    def latest_frame(self) -> Optional[Dict[str, Any]]:
        self._send(frames=True)
        batch = self._latest_batch
        if batch is None:
            return None
        self._judged_all()
        with self._changed:
            frames = self._frames.get(batch)
            self._frames = {index: kept for index, kept in self._frames.items() if index >= batch}  # earlier batches' frames are not asked for again
            return frames[-1] if frames else None

    def close(self) -> Dict[str, Any]:
        try:
            self._send(frames=False)
            self._client.publish_signal(CLOSE_SIGNAL, self.request_id, {"batches": self._sent})
            self._wait(lambda: self._verdict is not None, "return the run's verdict")
        except BaseException:
            self.abandon()
            raise
        self._client.disconnect()
        verdict = self._verdict or {}
        return {"scenes": int(verdict["scenes"]), "monitored_scenes": int(verdict["monitored-scenes"]), "time_step": int(verdict["time-step"]), **verdict["summary"]}

    def abandon(self) -> None:
        try:
            self._client.publish_cancel(self.request_id)
        except Exception:
            pass  # the connection is gone; the simulation subsystem cancels the series when the run's task ends
        try:
            self._client.disconnect()
        except Exception:
            pass


def pooled_series_of(pool: Tuple[str, Dict[str, str], Tuple[float, float, float]], job: JobSpec, time_step: int, colregs_constraints_content: Optional[str]) -> PooledSeries:
    """The series of the job's run in the monitoring subsystem this process was given (monitoring_types.monitoring_pool_from_environment)."""
    from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo, service_topic
    from scenegems_tool.messaging.mqtt_pool_client import MqttPoolClient
    from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

    service_name, broker_environment, (latitude, longitude, radius) = pool
    connection = MQttConnectionInfo.from_environment(broker_environment)
    request_id = live_series_request_id(request_id_of(job))

    def client_of(**handlers: Any) -> MqttPoolClient:
        return MqttPoolClient(connection, service_topic(connection.topic_root, service_name), Geofence(latitude, longitude, radius), service_name, name=f"run_{request_id}", **handlers)

    seed = job.payload.get("seed", 0) if isinstance(job.payload, dict) else 0
    return PooledSeries(client_of, request_id, job.job_id, time_step, colregs_constraints_content, seed=int(seed or 0))
