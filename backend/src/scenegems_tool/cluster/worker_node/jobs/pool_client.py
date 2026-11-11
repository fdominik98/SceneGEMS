"""A job as a request to its subsystem: wait for the pool, send the request with its seed, follow the task and take its result.

Every job that a subsystem's pool runs goes through run_pool_request. The request id is the job's id and
attempt, so an earlier attempt's late reply is never taken for this one. The result is the message the
task marked as its result on one of its streams. A task that fails, or is aborted by somebody else, fails
the attempt at once with the subsystem's reason, and a job that stops waiting without a result (cancelled,
lost, released, timed out) cancels its own request, so the pool's other tasks keep running.
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.worker_node.job_report import JobFailed, JobReport
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.subsystems.pool.pool_task import TaskState, draw_seed

_logger = logging.getLogger(__name__)
CANCEL_FLUSH_TIMEOUT_S = 2.0  # how long the job waits for the broker to take its cancel before it disconnects
RESULT_GRACE_S = 2.0  # how long a finished task's result may still be on its way

POOL_STARTUP_TIMEOUT_S = 180.0  # a cold pool: container start, imports and the broker handshake
_POLL_S = 0.1


def wait_for_pool(is_ready: Callable[[], bool], report: JobReport, description: str, cancel: Optional[threading.Event], timeout_s: float = POOL_STARTUP_TIMEOUT_S) -> None:
    """Block until the pool's service heartbeats; a pool that never does fails the attempt, which may be retried."""
    report.status(f"waiting for the {description}")
    deadline = time.monotonic() + timeout_s
    while not is_ready():
        if cancel is not None and cancel.is_set():
            raise JobFailed("cancelled", retryable=False)
        if time.monotonic() > deadline:
            raise JobFailed(f"The {description} sent no heartbeat within {timeout_s:g} s", retryable=True)
        time.sleep(_POLL_S)


def wait_for_reply(replied: threading.Event, report: JobReport, description: str, cancel: Optional[threading.Event], timeout_s: float) -> None:
    report.status(f"waiting for the {description}")
    deadline = time.monotonic() + timeout_s
    while not replied.wait(_POLL_S):
        if cancel is not None and cancel.is_set():
            raise JobFailed("cancelled", retryable=False)
        if time.monotonic() > deadline:
            raise JobFailed(f"No {description} within {timeout_s:g} s", retryable=True)


@dataclass
class PoolReply:
    """What a request came back with: the result message of its task, as the subsystem published it, and the seed the task ran with."""

    request_id: str
    seed: int
    result: Mapping[str, Any]


class _FollowedRequest:
    """What a job has heard of its request: the result, or how its task ended without one. done is set when the job has nothing more to wait for."""

    def __init__(self, request_id: str, is_result: Callable[[str, Mapping[str, Any]], bool], progress: Optional[Callable[[str, Mapping[str, Any]], Optional[str]]], report: JobReport):
        self.request_id = request_id
        self._is_result = is_result
        self._progress = progress
        self._report = report
        self.result: Optional[Mapping[str, Any]] = None
        self.ended: Optional[Tuple[TaskState, Optional[str]]] = None  # the task's end state and its reason, while there is no result
        self.done = threading.Event()

    def on_stream(self, stream: str, message: Mapping[str, Any]) -> None:
        if message.get("request-id") != self.request_id or self.result is not None:
            return
        if self._is_result(stream, message):
            self.result = message
            self.done.set()
        elif self._progress is not None:
            text = self._progress(stream, message)
            if text:
                self._report.status(text)

    def on_state(self, request_id: str, state: TaskState, reason: Optional[str], seed: Optional[int]) -> None:
        del seed  # the job sent the seed itself
        if request_id != self.request_id or self.result is not None or self.ended is not None:
            return
        if state in (TaskState.FAILED, TaskState.ABORTED):
            self.ended = (state, reason)
            self.done.set()
        elif state == TaskState.FINISHED:
            # The result is published before the state; it gets a moment in case the broker handed them over the other way round
            self.ended = (state, "it finished without a result")
            timer = threading.Timer(RESULT_GRACE_S, self.done.set)
            timer.daemon = True
            timer.start()


def run_pool_request(
    job: JobSpec,
    worker_node: Any,
    report: JobReport,
    cancel: Optional[threading.Event],
    *,
    subsystem: Subsystem,
    task_name: str,
    params: Mapping[str, Any],
    seed: Optional[int],
    streams: Sequence[str],
    is_result: Callable[[str, Mapping[str, Any]], bool],
    timeout_s: float,
    pool_description: str,
    reply_description: str,
    progress: Optional[Callable[[str, Mapping[str, Any]], Optional[str]]] = None,
) -> PoolReply:
    """Run the job as one request on the worker node's pool of the subsystem and return the task's result.

    seed: the request's seed; a job that names none gets one drawn here, so every request carries one.
    is_result(stream, message) picks the task's result among its stream messages; progress turns any other
    stream message into a status line. JobFailed when the pool cannot be reached, the task fails or is
    aborted, or no result comes within timeout_s.
    """
    from scenegems_tool.messaging.mqtt_pool_client import MqttPoolClient

    request_id = f"{job.job_id}-{job.attempt}"  # an earlier attempt's late reply is never taken for this one
    request_seed = draw_seed() if seed is None else seed
    followed = _FollowedRequest(request_id, is_result, progress, report)
    pool = worker_node.pools.get(subsystem)
    client = MqttPoolClient(pool.mqtt_connection, pool.service_topic, worker_node.reference_geofence, pool.service_name, streams=streams, on_state=followed.on_state, on_stream=followed.on_stream)
    try:
        client.connect()
    except RuntimeError as error:
        raise JobFailed(str(error), retryable=True) from error
    sent = False
    try:
        wait_for_pool(lambda: client.is_connected and client.is_heartbeat_valid, report, pool_description, cancel)
        client.publish_start_task(task_name, request_id, params, request_seed)
        sent = True
        wait_for_reply(followed.done, report, reply_description, cancel, timeout_s)
    finally:
        if sent and followed.result is None and followed.ended is None:
            _cancel_request(client, request_id)
        client.disconnect()
    if followed.result is None:
        state, reason = followed.ended
        ending = "was aborted" if state == TaskState.ABORTED else "failed"
        raise JobFailed(f"The task of the {pool_description} {ending}" + (f": {reason}" if reason else ""), retryable=True)
    return PoolReply(request_id, request_seed, followed.result)


def _cancel_request(client: Any, request_id: str) -> None:
    """Stop this job's tasks in the pool; a cancel that cannot be sent leaves the job's outcome as it is."""
    try:
        info = client.publish_cancel(request_id)
        if info is not None:
            info.wait_for_publish(timeout=CANCEL_FLUSH_TIMEOUT_S)
    except Exception as error:
        _logger.warning("Could not cancel request %s: %s", request_id, error)
