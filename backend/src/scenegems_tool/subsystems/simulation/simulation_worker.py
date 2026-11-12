"""The worker of a simulation task: it brings the run's vessel stack up, runs it, and takes it down again.

A run-simulation request carries a simulation job's payload. The worker hands it to the runner the payload
names (cluster/worker_node/jobs/simulation_runners/), which resolves the stack, writes its generated files,
starts its containers (the simulator, per vessel a controller and an ASV system, and the runner container that
owns the run's clock), waits for the operator's Start when the run is attended, follows the run and removes the
stack. The simulation subsystem is the one subsystem that starts containers: its own container holds the Docker
socket, and the stacks it starts sit next to it in the worker node's compose project.

The runner talks to a report and an observation, as it did when the worker node's daemon called it. Here both
are the task's channel:

    status           exec/feedback, with its detail (the phase of an attended run, what its vessels lack, its ports)
    log lines        sensor/simulation_log, in batches
    frames           sensor/simulation_frames, in batches, while somebody observes
    observe, start   the task's signals set the observation, which the stack passes into the runner container
    cancel           ends the wait for the runner; the stack is removed

A compare-repeats task is the subsystem's other kind of work: it starts no container and compares the
trajectories of finished repeats in the worker itself (compare_repeats).

At the end the worker emits the run's result on sensor/simulation_result. A run that fails with a reason (a stack
the worker node cannot run, a runner that reported an error, nobody started it in time) is a result too, with
whether another attempt can succeed: the requester has to hear the reason and the retry rule. A worker that
dies fails its task.
"""

import os
import threading
from typing import Any, Callable, Dict, List, Optional

from scenegems_tool.cluster.protocol.jobs import JobSpec, JobType
from scenegems_tool.cluster.protocol.messages import LogStream
from scenegems_tool.cluster.worker_node.job_observation import JobObservation
from scenegems_tool.cluster.worker_node.job_report import JobFailed, JobResultData
from scenegems_tool.cluster.worker_node.launchers.container_environment import geofence_from_environment
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo, service_name_from_environment
from scenegems_tool.subsystems.simulation.simulation_types import (
    BROKER_NETWORK_VARIABLE,
    CONTROL_NODE_VARIABLE,
    OBSERVE_SIGNAL,
    SIMULATION_FRAMES_STREAM,
    SIMULATION_LOG_STREAM,
    SIMULATION_RESULT_STREAM,
    SIMULATION_SERVICE_NAME,
    START_SIGNAL,
    WORKER_NODE_VARIABLE,
    CompareRepeatsTask,
    RunSimulationTask,
)

RELAY_INTERVAL_S = 0.05  # how often the worker passes signals in and frames and log lines out
LOG_BATCH_LINES = 200  # at most this many lines per log message

RunStack = Callable[[JobSpec, WorkerNodeContext, Any, Any], JobResultData]


def worker_node_number(service_name: str) -> int:
    """The number the control node gave the worker node, from the name its simulation subsystem was started under (simulation-subsystem-3); 1 for a subsystem on its own."""
    _, _, number = service_name.rpartition("-")
    return int(number) if number.isdigit() and int(number) >= 1 else 1


def context_from_environment() -> WorkerNodeContext:
    """What a runner needs of the worker node, as the subsystem's launcher configured the container (launchers/pooled/simulation_pool.py).

    The worker node's number names its other subsystems on the broker: a run that is judged while it runs is told the monitoring subsystem by it.
    """
    return WorkerNodeContext(
        control_node_id=os.environ[CONTROL_NODE_VARIABLE],
        worker_node_id=os.environ[WORKER_NODE_VARIABLE],
        mqtt_connection=MQttConnectionInfo.from_environment(),
        reference_geofence=geofence_from_environment(),
        broker_network=os.environ.get(BROKER_NETWORK_VARIABLE, "").strip() or None,
        instance_number=worker_node_number(service_name_from_environment(SIMULATION_SERVICE_NAME)),
    )


class CancelFlag:
    """The task's cancel flag as the event a job stack waits on."""

    def __init__(self, channel: Any):
        self._channel = channel

    def is_set(self) -> bool:
        return bool(self._channel.cancelled)


class ChannelReport:
    """A runner's report on the task's channel: status as progress at once, log lines kept until the relay takes them."""

    def __init__(self, channel: Any):
        self._channel = channel
        self._lines: List[Dict[str, str]] = []
        self._lock = threading.Lock()

    def status(self, message: str, progress: Optional[float] = None, detail: Optional[Dict[str, Any]] = None) -> None:
        self._channel.progress(message, progress, detail)

    def log(self, source: str, text: str, stream: LogStream = LogStream.STDOUT) -> None:
        with self._lock:
            self._lines.append({"source": source, "text": text, "stream": LogStream(stream).value})

    def take_lines(self, limit: Optional[int] = None) -> List[Dict[str, str]]:
        """The oldest lines that wait, at most limit (LOG_BATCH_LINES unless given)."""
        limit = LOG_BATCH_LINES if limit is None else limit
        with self._lock:
            taken, self._lines = self._lines[:limit], self._lines[limit:]
            return taken


class TaskRelay:
    """Carries a running task's traffic between its channel and the runner: signals into the observation, frames and log lines out.

    step() is one round; run on a thread between start() and stop(). stop() does the last rounds: what the run wrote
    until its end goes out before the result. frame_batches and log_batches count what went out.
    """

    def __init__(self, channel: Any, observation: Optional[JobObservation], report: ChannelReport, interval_s: float = RELAY_INTERVAL_S):
        self._channel = channel
        self._observation = observation
        self._report = report
        self._interval_s = interval_s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.frame_batches = 0
        self.log_batches = 0

    def step(self, last: bool = False) -> None:
        for signal in self._channel.signals():
            self._take(signal.name, signal.data or {})
        while self._observation is not None:
            batch = self._observation.take_batch(force=last)
            if batch is None:
                break
            self._channel.emit(SIMULATION_FRAMES_STREAM, {"index": self.frame_batches, "frames": batch[1]})
            self.frame_batches += 1
            if not last:
                break  # one batch a round: the observation paces them
        while True:
            lines = self._report.take_lines()
            if not lines:
                break
            self._channel.emit(SIMULATION_LOG_STREAM, {"index": self.log_batches, "lines": lines})
            self.log_batches += 1

    def _take(self, name: str, data: Any) -> None:
        if self._observation is None:
            return
        if name == OBSERVE_SIGNAL:
            self._observation.request(bool(data.get("active", False)), float(data.get("speed", 1.0)))
        elif name == START_SIGNAL:
            self._observation.start()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="simulation_task_relay", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self._interval_s):
            self.step()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        self.step(last=True)


def run_task(task: RunSimulationTask, channel: Any, context: WorkerNodeContext, run_stack: Optional[RunStack] = None, threaded: bool = True) -> None:
    """Run the task's simulation with the runner its payload names and emit the result; a cancelled task emits none.

    run_stack: what runs the job's stack, jobs/simulation_job.run_stack unless given. threaded: the relay runs on a
    thread of its own; without it the caller steps it (a test).
    """
    if run_stack is None:
        from scenegems_tool.cluster.worker_node.jobs.simulation_job import run_stack as run_stack_of_the_job

        run_stack = run_stack_of_the_job
    job = JobSpec(job_id=task.job_id, job_type=JobType.SIMULATION, payload=dict(task.payload), attempt=task.attempt, idempotency_key=task.request_id)
    observation = context.observations.open(job)
    report = ChannelReport(channel)
    relay = TaskRelay(channel, observation, report)
    if threaded:
        relay.start()
    try:
        outcome: Dict[str, Any] = {"result": run_stack(job, context, report, CancelFlag(channel)), "error": None, "retryable": False}
    except JobFailed as failure:
        outcome = {"result": None, "error": str(failure), "retryable": bool(failure.retryable)}
    finally:
        relay.stop()
        context.observations.close(job)
    if channel.cancelled:
        return  # nobody waits for it
    channel.emit(SIMULATION_RESULT_STREAM, {**outcome, "frame-batches": relay.frame_batches, "log-batches": relay.log_batches}, final=True)


def compare_repeats(task: CompareRepeatsTask, channel: Any) -> None:
    """Compare the repeats of the task's payload and emit the result; a comparison that fails with a reason is a result too, as a run's is."""
    from pydantic import ValidationError

    from scenegems_tool.cluster.worker_node.jobs.calibration_deviation_job import CalibrationDeviationPayload, compare

    try:
        outcome: Dict[str, Any] = {"result": compare(CalibrationDeviationPayload.model_validate(dict(task.payload)), channel.progress), "error": None, "retryable": False}
    except JobFailed as failure:
        outcome = {"result": None, "error": str(failure), "retryable": bool(failure.retryable)}
    except ValidationError as error:
        outcome = {"result": None, "error": f"Invalid calibration.deviation payload: {error}", "retryable": False}
    if not channel.cancelled:
        channel.emit(SIMULATION_RESULT_STREAM, {**outcome, "frame-batches": 0, "log-batches": 0}, final=True)


def run_simulation_worker(task: Any, channel: Any) -> None:
    """What a worker process of the simulation pool runs for a task: a run, or a comparison of repeats."""
    if isinstance(task, CompareRepeatsTask):
        compare_repeats(task, channel)
    else:
        run_task(task, channel, context_from_environment())
