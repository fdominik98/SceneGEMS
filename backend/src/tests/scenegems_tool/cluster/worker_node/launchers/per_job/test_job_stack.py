import io
import shutil
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from scenegems_tool.cluster.protocol.messages import LogStream
from scenegems_tool.cluster.worker_node.instance_scope import INSTANCE_LABEL, InstanceScope
from scenegems_tool.cluster.worker_node.job_observation import JobObservation
from scenegems_tool.cluster.worker_node.jobs.in_container.run_observation import ContainerObservation
from scenegems_tool.cluster.worker_node.launchers.per_job import job_stack
from scenegems_tool.cluster.worker_node.launchers.per_job.job_container_io import (
    JOB_CONTAINER_MAIN,
    JOB_FOLDER,
    OBSERVE_DOCUMENT,
    ObservationControl,
    format_frame_line,
    format_status_line,
)
from scenegems_tool.cluster.worker_node.launchers.per_job.job_stack import RUNNER_SERVICE, JobStack, forward_runner_line, project_compose, runner_service, scope_services

SCOPE = InstanceScope.per_job("m1", "n1", "simulation", "j7")


def test_runner_without_networks_has_no_network():
    service = runner_service("scenegems-simulation-subsystem:latest")
    assert service["command"] == ["python", "-m", JOB_CONTAINER_MAIN]
    assert service["network_mode"] == "none"
    assert "networks" not in service


def test_a_runner_image_with_its_own_program_gets_its_command_and_environment():
    service = runner_service("scenegems-design-space-exploration-subsystem:latest", command=["generate-models", "job"], environment={})
    assert (service["command"], service["environment"], service["network_mode"]) == (["generate-models", "job"], {}, "none")
    assert runner_service("image")["environment"] == {"PYTHONUNBUFFERED": "1"}  # the Python job main's, unless one is given


def test_every_container_of_a_job_stack_has_a_bounded_log():
    services = scope_services(SCOPE, {RUNNER_SERVICE: runner_service("image"), "sitl_0": {"image": "sitl"}, "gazebo": {"image": "gazebo", "logging": {"driver": "local"}}})
    assert services[RUNNER_SERVICE]["logging"] == {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}
    assert services["sitl_0"]["logging"] == services[RUNNER_SERVICE]["logging"]
    assert services["gazebo"]["logging"] == {"driver": "local"}  # a service's own logging stays
    assert services[RUNNER_SERVICE]["logging"] is not services["sitl_0"]["logging"]  # no shared object, so no YAML anchor


def test_runner_on_a_stack_network_waits_for_the_stack():
    service = runner_service("image", networks=["maritime_net"], depends_on=["vessel_0", "vessel_1"])
    assert service["networks"] == ["maritime_net"]
    assert service["depends_on"] == ["vessel_0", "vessel_1"]
    assert "network_mode" not in service


def test_scoped_services_get_scope_names_and_no_published_ports():
    services = scope_services(SCOPE, {"gazebo": {"image": "gz", "container_name": "gazebo", "ports": ["11345:11345"], "restart": "unless-stopped"}})
    assert services["gazebo"] == {"image": "gz", "container_name": "scenegems-m1-n1-simulation-subsystem-j7-gazebo", "logging": job_stack.bounded_logging()}


def test_job_stack_names_the_runner_container_by_scope():
    stack = JobStack(SCOPE, {RUNNER_SERVICE: runner_service("image")})
    assert stack.runner_container == "scenegems-m1-n1-simulation-subsystem-j7-runner"
    assert stack.project.name == SCOPE.compose_project == "scenegems-m1-n1", "the worker node's project, which every instance shares"
    assert stack.project.instance == SCOPE.key == "j7-1", "so the stack is removed by its own label"
    assert stack.project.compose_filename == f"{SCOPE.folder}/docker-compose.yml"


def test_a_stack_in_the_worker_nodes_project_has_unique_service_keys_and_keeps_its_names_as_aliases():
    stack = JobStack(
        SCOPE,
        {
            RUNNER_SERVICE: runner_service("image", networks=["maritime_net"], depends_on=["kinematic_sim", "vessel_0_asv_system"]),
            "kinematic_sim": {"image": "sim", "networks": ["maritime_net"]},
            "vessel_0_asv_system": {"image": "asv", "networks": ["maritime_net", "scenegems_broker"], "labels": ["role=asv"]},
        },
        networks={"maritime_net": {"driver": "bridge"}, "scenegems_broker": {"external": True, "name": "scenegems-m1-n1"}},
        volumes={"runtime": {"external": True}},
    )
    document = project_compose(SCOPE, stack.compose)
    runner, simulator, asv_system = (f"simulation-subsystem-j7-{part}" for part in ("runner", "kinematic-sim", "vessel-0-asv-system"))
    assert list(document["services"]) == [runner, simulator, asv_system], "compose tells a project's containers apart by these keys"
    assert document["services"][runner]["depends_on"] == [simulator, asv_system]
    network = "simulation-subsystem-j7-maritime-net"
    assert document["services"][simulator]["networks"] == {network: {"aliases": ["kinematic_sim"]}}, "the name the runner dials"
    assert document["services"][asv_system]["networks"] == {network: {"aliases": ["vessel_0_asv_system"]}, "scenegems_broker": None}, "no alias on a network other instances share"
    assert document["services"][asv_system]["labels"] == {"role": "asv", INSTANCE_LABEL: "j7-1"}
    assert all(service["labels"][INSTANCE_LABEL] == "j7-1" for service in document["services"].values())
    assert list(document["networks"]) == [network, "scenegems_broker"], "compose tells a project's networks apart by their keys too"
    assert document["networks"][network] == {"driver": "bridge", "name": "scenegems-m1-n1-simulation-subsystem-j7-maritime-net", "labels": {INSTANCE_LABEL: "j7-1"}}
    assert document["networks"]["scenegems_broker"] == {"external": True, "name": "scenegems-m1-n1"}, "the worker node's network stays as it is"
    assert document["volumes"] == {"runtime": {"external": True}}
    assert list(stack.compose["services"]) == [RUNNER_SERVICE, "kinematic_sim", "vessel_0_asv_system"], "the stack itself keeps its own names"


def test_a_runner_without_a_network_gets_only_its_key_and_label():
    document = project_compose(SCOPE, JobStack(SCOPE, {RUNNER_SERVICE: runner_service("image")}).compose)
    ((key, service),) = document["services"].items()
    assert key == "simulation-subsystem-j7-runner" and service["network_mode"] == "none" and "networks" not in service
    assert "networks" not in document


def test_job_stack_needs_a_runner():
    with pytest.raises(ValueError):
        JobStack(SCOPE, {"gazebo": {"image": "gz"}})


# Live observation through the runner's job folder and output, with a folder on disk as the runner's /job


class RecordingReport:
    def __init__(self) -> None:
        self.statuses = []
        self.lines = []

    def status(self, message, progress=None) -> None:
        self.statuses.append((message, progress))

    def log(self, source, text, stream=LogStream.STDOUT) -> None:
        self.lines.append((source, text, stream))


@pytest.fixture
def runner_folder(monkeypatch, tmp_path):
    """docker cp into the runner, as a copy into a folder that stands for its job folder."""
    folder = tmp_path / "runner-job-folder"
    folder.mkdir()
    copies = []

    def copy_into_container(source, container, destination):
        assert destination == f"{JOB_FOLDER}/{OBSERVE_DOCUMENT}"
        copies.append(container)
        shutil.copyfile(source, folder / OBSERVE_DOCUMENT)

    monkeypatch.setattr(job_stack, "copy_into_container", copy_into_container)
    return SimpleNamespace(path=folder, copies=copies)


def test_runner_output_lines_go_to_status_observation_or_log():
    report, observation = RecordingReport(), JobObservation("j7", 1)
    observation.request(True, 10.0)
    for line, stream in [
        (format_status_line("running", 0.5) + "\n", LogStream.STDOUT),
        (format_frame_line('{"timestamp":4}') + "\r\n", LogStream.STDOUT),
        ("plain output\n", LogStream.STDOUT),
        (format_frame_line('{"timestamp":5}') + "\n", LogStream.STDERR),  # only stdout carries frames
        ("\n", LogStream.STDOUT),
    ]:
        forward_runner_line(line, stream, "runner-1", report, observation)
    assert report.statuses == [("running", 0.5)]
    assert report.lines == [("runner-1", "plain output", LogStream.STDOUT), ("runner-1", format_frame_line('{"timestamp":5}'), LogStream.STDERR)]
    assert observation.take_batch() == (1, [{"timestamp": 4}])
    forward_runner_line(format_frame_line('{"timestamp":6}'), LogStream.STDOUT, "runner-1", report, None)  # no observation: the frame is dropped, not logged
    assert len(report.lines) == 2


def test_requests_reach_the_runner_folder_and_its_frames_come_back(runner_folder):
    stack = JobStack(SCOPE, {RUNNER_SERVICE: runner_service("image")})
    observation = JobObservation("j7", 1, min_interval_s=0.0)
    stop = threading.Event()
    copier = threading.Thread(target=stack.copy_observation_requests, args=(observation, stop), daemon=True)
    copier.start()
    try:
        runner = ContainerObservation(str(runner_folder.path), out=io.StringIO(), clock=lambda: 0.0)  # the runner's view of its job folder
        assert not (runner_folder.path / OBSERVE_DOCUMENT).exists()  # nothing is written while nobody observes
        observation.request(True, 25.0)
        _wait_until(lambda: (runner_folder.path / OBSERVE_DOCUMENT).exists())
        assert runner.control() == ObservationControl(active=True, speed=25.0, revision=1)
        assert runner_folder.copies == [stack.runner_container]

        out = io.StringIO()
        runner = ContainerObservation(str(runner_folder.path), out=out, clock=lambda: 0.0)
        for index in range(3):
            runner.write_frame({"timestamp": index})
        for line in out.getvalue().splitlines(keepends=True):
            forward_runner_line(line, LogStream.STDOUT, stack.runner_container, RecordingReport(), observation)
        assert observation.take_batch() == (1, [{"timestamp": 0}, {"timestamp": 1}, {"timestamp": 2}])

        observation.request(True, 50.0)
        observation.request(False, 50.0)  # the latest request wins; the one in between may be skipped
        _wait_until(lambda: getattr(_request_in(runner_folder.path), "revision", 0) == 3)
        assert not _request_in(runner_folder.path).active
    finally:
        stop.set()
        copier.join(timeout=5)
    assert not copier.is_alive()


def test_a_failed_copy_is_retried(monkeypatch, runner_folder):
    stack = JobStack(SCOPE, {RUNNER_SERVICE: runner_service("image")})
    attempts = []
    copy = job_stack.copy_into_container

    def flaky(source, container, destination):
        attempts.append(container)
        if len(attempts) == 1:
            raise subprocess.CalledProcessError(1, ["docker", "cp"], stderr="not running")
        copy(source, container, destination)

    monkeypatch.setattr(job_stack, "copy_into_container", flaky)
    monkeypatch.setattr(job_stack, "_CONTROL_WAIT_S", 0.01)
    observation = JobObservation("j7", 1)
    observation.request(True, 10.0)
    stop = threading.Event()
    copier = threading.Thread(target=stack.copy_observation_requests, args=(observation, stop), daemon=True)
    copier.start()
    try:
        _wait_until(lambda: (runner_folder.path / OBSERVE_DOCUMENT).exists())
    finally:
        stop.set()
        copier.join(timeout=5)
    assert len(attempts) == 2


def _request_in(folder):
    """The request in the runner's folder; None while a copy is half written."""
    try:
        return ObservationControl.from_document((folder / OBSERVE_DOCUMENT).read_text())
    except (OSError, ValueError):
        return None


def _wait_until(condition, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


# Published ports and the wait for the operator's Start (attended jobs)


def test_only_the_named_services_keep_their_published_ports():
    services = scope_services(SCOPE, {"os_mavproxy": {"image": "mavproxy", "ports": ["5770"]}, "os": {"image": "sitl", "ports": ["5760:5760"]}}, published=["os_mavproxy"])
    assert services["os_mavproxy"]["ports"] == ["5770"] and "ports" not in services["os"]
    stack = JobStack(SCOPE, {RUNNER_SERVICE: runner_service("image"), "os_mavproxy": {"image": "mavproxy", "ports": ["5770"]}}, published=["os_mavproxy"])
    assert stack.compose["services"]["os_mavproxy"]["ports"] == ["5770"]


def test_the_ports_docker_assigned_go_into_every_status_detail(monkeypatch):
    from scenegems_tool.cluster.worker_node.job_report import StatusDetailReport

    stack = JobStack(SCOPE, {RUNNER_SERVICE: runner_service("image"), "os_mavproxy": {"image": "mavproxy", "ports": ["5770"]}}, published=["os_mavproxy"])
    asked = []
    answers = iter([None, 49153])  # not assigned yet, then assigned

    def published_port(service, container_port):
        asked.append((service, container_port))
        return next(answers)

    monkeypatch.setattr(stack.project, "published_port", published_port)
    monkeypatch.setattr(job_stack, "_PUBLISHED_PORT_POLL_S", 0.0)
    inner = RecordingDetailReport()
    report = StatusDetailReport(inner)
    report.status("ready to start", None, {"phase": "ready_to_start"})
    stack._report_published_ports({"0": ("os_mavproxy", 5770)}, report, threading.Event())
    assert asked == [("simulation-subsystem-j7-os-mavproxy", 5770)] * 2, "asked by the service's key in the worker node's project, until Docker assigned the port"
    assert inner.statuses[-1] == ("ready to start", None, {"phase": "ready_to_start", "ground_control": {"0": 49153}}), "the latest status again, with the ports"
    report.status("running", 0.0, {"phase": "running"})
    assert inner.statuses[-1] == ("running", 0.0, {"phase": "running", "ground_control": {"0": 49153}}), "and every status after it"
    report.log("runner", "a line")
    assert inner.lines == [("runner", "a line", LogStream.STDOUT)]


def test_a_status_without_anything_to_add_goes_out_as_it_came():
    from scenegems_tool.cluster.worker_node.job_report import StatusDetailReport

    inner = RecordingDetailReport()
    report = StatusDetailReport(inner)
    report.status("creating the job stack")
    assert inner.statuses == [("creating the job stack", None, None)]
    report.add_detail({"ground_control": {"0": 49153}})
    assert inner.statuses[-1] == ("creating the job stack", None, {"ground_control": {"0": 49153}})


class RecordingDetailReport:
    def __init__(self) -> None:
        self.statuses = []
        self.lines = []

    def status(self, message, progress=None, detail=None) -> None:
        self.statuses.append((message, progress, detail))

    def log(self, source, text, stream=LogStream.STDOUT) -> None:
        self.lines.append((source, text, stream))


class WaitingRunner:
    """Stands in for `docker wait` on a clock of its own: every poll takes the poll's time, and the runner stops after stop_after polls."""

    def __init__(self, stop_after=None, on_poll=None):
        self.now = 0.0
        self.polls = 0
        self.stop_after = stop_after
        self.on_poll = on_poll
        self.killed = False

    def communicate(self, timeout=None):
        self.polls += 1
        self.now += timeout
        if self.on_poll is not None:
            self.on_poll(self.polls)
        if self.stop_after is not None and self.polls >= self.stop_after:
            return "0\n", None
        raise subprocess.TimeoutExpired("docker wait", timeout)

    def kill(self):
        self.killed = True


@pytest.fixture
def waiting_runner(monkeypatch):
    """A runner whose wait is polled once a second of its own clock, which is also the launcher's."""
    runner = WaitingRunner()
    monkeypatch.setattr(job_stack.subprocess, "Popen", lambda *args, **kwargs: runner)
    monkeypatch.setattr(job_stack, "time", SimpleNamespace(monotonic=lambda: runner.now))
    monkeypatch.setattr(job_stack, "_WAIT_POLL_S", 1.0)
    monkeypatch.setattr(job_stack, "_START_MARGIN_S", 0.0)
    return runner


def test_the_wait_for_the_start_does_not_count_against_the_jobs_timeout(waiting_runner):
    stack = JobStack(SCOPE, {RUNNER_SERVICE: runner_service("image")})
    observation = JobObservation("j7", 1)
    waiting_runner.on_poll = lambda polls: observation.start() if polls == 20 else None  # the operator, 20 s in
    waiting_runner.stop_after = 23
    assert stack._wait(5.0, None, start=(observation, 60.0)) == 0, "20 s of waiting are four times the job's timeout"
    assert not waiting_runner.killed


def test_a_run_nobody_starts_is_ended_by_the_launcher_at_the_latest(waiting_runner):
    stack = JobStack(SCOPE, {RUNNER_SERVICE: runner_service("image")})
    with pytest.raises(job_stack.JobFailed, match="nobody started the run within 3 s") as failure:
        stack._wait(600.0, None, start=(JobObservation("j7", 1), 3.0))
    assert waiting_runner.killed and not failure.value.retryable and waiting_runner.polls == 4


def test_after_the_start_the_jobs_timeout_counts(waiting_runner):
    stack = JobStack(SCOPE, {RUNNER_SERVICE: runner_service("image")})
    observation = JobObservation("j7", 1)
    waiting_runner.on_poll = lambda polls: observation.start() if polls == 10 else None
    with pytest.raises(job_stack.JobFailed, match="timed out after 5 s"):
        stack._wait(5.0, None, start=(observation, 60.0))
    assert waiting_runner.polls == 16, "the Start at 10 s, then the job's 5 s"
