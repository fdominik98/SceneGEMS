import io
import shutil
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from scenegems_tool.cluster.protocol.messages import LogStream
from scenegems_tool.cluster.worker_node.instance_scope import InstanceScope
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
from scenegems_tool.cluster.worker_node.launchers.per_job.job_stack import RUNNER_SERVICE, JobStack, forward_runner_line, runner_service, scope_services

SCOPE = InstanceScope.per_job("m1", "n1", "j7-1")


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
    assert services["gazebo"] == {"image": "gz", "container_name": "scenegems-m1-n1-job-j7-1-gazebo", "logging": job_stack.bounded_logging()}


def test_job_stack_names_the_runner_container_by_scope():
    stack = JobStack(SCOPE, {RUNNER_SERVICE: runner_service("image")})
    assert stack.runner_container == "scenegems-m1-n1-job-j7-1-runner"
    assert stack.project.name == SCOPE.compose_project
    assert stack.project.compose_filename == f"{SCOPE.folder}/docker-compose.yml"


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
