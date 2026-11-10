import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import pytest

from scenegems_tool.cluster.protocol.jobs import JobSpec, JobType
from scenegems_tool.cluster.protocol.messages import LeaseOffer
from scenegems_tool.cluster.worker_node.daemon.configuration.worker_node_configuration import WorkerNodeConfiguration
from scenegems_tool.cluster.worker_node.daemon.control.reconnect_backoff import ReconnectBackoff
from scenegems_tool.cluster.worker_node.daemon.resource_probe import ResourceProbe
from scenegems_tool.cluster.worker_node.daemon.worker_node_daemon import WorkerNodeDaemon
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from tests.scenegems_tool.cluster.worker_node.daemon.fake_control_node import FakeControlNode

TIMEOUT_S = 10.0
FINGERPRINTS = {"scenegems-scenario-execution-subsystem:latest": "f" * 64}


def make_job(job_id: str = "job-1", job_type: JobType = JobType.SIMULATION, attempt: int = 1, payload: Optional[dict] = None) -> JobSpec:
    return JobSpec(job_id=job_id, job_type=job_type, payload=payload or {}, attempt=attempt, idempotency_key=f"{job_id}/key")


def make_offer(lease_id: str, job: Optional[JobSpec] = None) -> LeaseOffer:
    return LeaseOffer(lease_id=lease_id, job=job or make_job(f"job-of-{lease_id}"), expires_at=datetime.now(timezone.utc) + timedelta(seconds=30))


@dataclass
class ScriptedJobs:
    """A stand-in for run_job: each job blocks until the test finishes or fails it, or its cancel event is set."""

    started: "queue.Queue[str]" = field(default_factory=queue.Queue)
    cancelled: List[str] = field(default_factory=list)
    _outcomes: Dict[str, "queue.Queue"] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    running: int = 0
    most_running: int = 0

    def _outcome(self, job_id: str) -> "queue.Queue":
        with self._lock:
            return self._outcomes.setdefault(job_id, queue.Queue())

    def __call__(self, job: JobSpec, worker_node, report, cancel: threading.Event):
        with self._lock:
            self.running += 1
            self.most_running = max(self.most_running, self.running)
        try:
            report.status(f"running {job.job_id}", 0.1)
            report.log("runner", f"started {job.job_id}")
            self.started.put(job.job_id)
            outcome = self._outcome(job.job_id)
            while True:
                if cancel.is_set():
                    self.cancelled.append(job.job_id)
                    raise JobFailed("cancelled", retryable=False)
                try:
                    kind, value = outcome.get(timeout=0.02)
                except queue.Empty:
                    continue
                if kind == "fail":
                    raise value
                return value
        finally:
            with self._lock:
                self.running -= 1

    def wait_started(self, timeout_s: float = TIMEOUT_S) -> str:
        return self.started.get(timeout=timeout_s)

    def finish(self, job_id: str, result: Optional[dict] = None) -> None:
        self._outcome(job_id).put(("finish", result if result is not None else {"job": job_id}))

    def fail(self, job_id: str, error: BaseException) -> None:
        self._outcome(job_id).put(("fail", error))


class DaemonThread:
    """A WorkerNodeDaemon running in a thread, as its container would run it."""

    def __init__(self, daemon: WorkerNodeDaemon):
        self.daemon = daemon
        self.stop_event = threading.Event()
        self.error: Optional[BaseException] = None
        self.thread = threading.Thread(target=self._run, name="worker-node-daemon", daemon=True)

    def _run(self) -> None:
        try:
            self.daemon.run(self.stop_event)
        except BaseException as error:  # handed to the test
            self.error = error

    def start(self) -> "DaemonThread":
        self.thread.start()
        return self

    def stop(self, timeout_s: float = TIMEOUT_S) -> None:
        self.stop_event.set()
        self.thread.join(timeout=timeout_s)
        assert not self.thread.is_alive(), "the daemon did not stop"

    def wait_exit(self, timeout_s: float = TIMEOUT_S) -> Optional[BaseException]:
        self.thread.join(timeout=timeout_s)
        assert not self.thread.is_alive(), "the daemon is still running"
        return self.error


@pytest.fixture
def fake_control_node():
    with FakeControlNode() as control_node:
        yield control_node


def worker_node_values(control_node: FakeControlNode, state_dir, **overrides) -> Dict[str, str]:
    values = {
        "SCENEGEMS_CONTROL_NODE_URL": control_node.url,
        "SCENEGEMS_CONTROL_NODE_ID": control_node.control_node_id,
        "SCENEGEMS_WORKER_NODE_NAME": "test-worker-node",
        "SCENEGEMS_WORKER_NODE_SLOTS": "simulation:2,scene_generation:1",
        "SCENEGEMS_WORKER_NODE_COMPONENTS": "asv_software/replay,control_layer/none,simulation_layer/kinematic,scene_generation",
        "SCENEGEMS_WORKER_NODE_LABELS": "site=lab",
        "SCENEGEMS_WORKER_NODE_STATE_DIR": str(state_dir),
        "SCENEGEMS_SOFTWARE_REVISION": "test-revision",
    }
    values.update({key: value for key, value in overrides.items() if value is not None})
    return {key: value for key, value in values.items() if value != ""}


@pytest.fixture
def worker_node_configuration(fake_control_node, tmp_path):
    def build(**overrides) -> WorkerNodeConfiguration:
        return WorkerNodeConfiguration.from_values(worker_node_values(fake_control_node, tmp_path / "state", **overrides))

    return build


@pytest.fixture
def jobs() -> ScriptedJobs:
    return ScriptedJobs()


@pytest.fixture
def start_daemon(tmp_path, jobs):
    """Start a WorkerNodeDaemon with scripted jobs and fast reconnects; every started daemon is stopped at the end."""
    started: List[DaemonThread] = []

    def start(configuration: WorkerNodeConfiguration, **options) -> DaemonThread:
        options.setdefault("run", jobs)
        options.setdefault("probe", ResourceProbe(disk_path=tmp_path))
        options.setdefault("fingerprints", lambda: dict(FINGERPRINTS))
        options.setdefault("backoff", ReconnectBackoff(initial_s=0.05, maximum_s=0.2))
        options.setdefault("clean_leftovers", False)
        options.setdefault("shutdown_timeout_s", 5.0)
        runner = DaemonThread(WorkerNodeDaemon(configuration, **options)).start()
        started.append(runner)
        return runner

    yield start
    for runner in started:
        runner.stop_event.set()
        runner.thread.join(timeout=TIMEOUT_S)


def wait_for(condition, timeout_s: float = TIMEOUT_S) -> None:
    deadline = time.monotonic() + timeout_s
    while not condition():
        assert time.monotonic() < deadline, "condition not met in time"
        time.sleep(0.02)
