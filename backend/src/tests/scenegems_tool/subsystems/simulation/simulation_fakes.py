"""A simulation task and what stands in for its surroundings in tests: the worker node's context, the channel, and a runner that runs no stack."""

import time
from typing import Any, Callable, Dict, List, Optional

from scenegems_tool.cluster.protocol.messages import LogStream
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.subsystems.pool.pool_task import TaskSignal
from scenegems_tool.subsystems.simulation.simulation_types import RunSimulationTask
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from tests.scenegems_tool.subsystems.pool.pool_fakes import RecordingChannel

PAYLOAD = {"runner": "kinematic", "seed": 4, "trajectories": {"scene_list": [], "time_step": 1}}
WAIT_S = 30.0  # a safety net for a stand-in runner that waits for its signals


def simulation_task(job_id: str = "job-1", attempt: int = 1, seed: int = 4, payload: Optional[Dict[str, Any]] = None) -> RunSimulationTask:
    return RunSimulationTask(sender="simulation-subsystem", task_uuid=f"u-{job_id}", request_id=f"{job_id}-{attempt}", seed=seed, job_id=job_id, attempt=attempt, payload=payload or PAYLOAD)


def task_context() -> WorkerNodeContext:
    """The worker node as the subsystem's container knows it."""
    return WorkerNodeContext(
        control_node_id="m1",
        worker_node_id="n1",
        mqtt_connection=MQttConnectionInfo("", "", "broker", "broker", 1883, False, False, topic_root="scenegems"),
        reference_geofence=Geofence(57.7, 11.9, 2000.0),
        broker_network="scenegems-m1-n1",
    )


class SignalChannel(RecordingChannel):
    """A worker's channel whose signals the test puts in (send); it keeps the progress details too."""

    def __init__(self, signals: Optional[List[TaskSignal]] = None):
        super().__init__()
        self.pending: List[TaskSignal] = list(signals or [])
        self.details: List[Any] = []

    def send(self, name: str, data: Any = None) -> None:
        self.pending.append(TaskSignal(name, data))

    def signals(self) -> List[TaskSignal]:
        taken, self.pending = self.pending, []
        return taken

    def progress(self, message: str, fraction: Optional[float] = None, detail: Any = None) -> None:
        super().progress(message, fraction, detail)
        self.details.append(detail)


def stand_in_run(
    result: Optional[Dict[str, Any]] = None, *, failure: Optional[JobFailed] = None, wait_for_start: bool = False, frames: int = 0, seen: Optional[Dict[str, Any]] = None
) -> Callable[..., Dict[str, Any]]:
    """A run_stack that starts no container: it reports, logs, optionally waits for the operator's Start and writes frames, then returns or fails.

    seen collects what it was called with (job, context, cancelled at the end).
    """

    def run_stack(job, context, report, cancel):
        observation = context.observations.of(job)
        report.status("generating the stack", None, {"phase": "preparing"})
        report.log("runner", "the stack is up")
        report.log("runner", "a warning", LogStream.STDERR)
        if wait_for_start:
            deadline = time.monotonic() + WAIT_S
            revision = 0
            while not observation.started:
                assert time.monotonic() < deadline, "nobody started the run"
                revision = observation.wait_for_change(revision, 0.05).revision
            report.status("running", 0.0, {"phase": "running"})
        if frames:
            observation.add_frames(({"timestamp": index}, 20) for index in range(frames))
        if seen is not None:
            seen.update(job=job, context=context, cancelled=cancel.is_set(), observed=observation.active, speed=observation.control.speed)
        if failure is not None:
            raise failure
        report.status("run finished", 1.0)
        return result if result is not None else {"steps": 120, "state_digest": "abc"}

    return run_stack
