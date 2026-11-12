"""A per-job stack: the containers of one job in the worker node's compose project, run to completion and removed.

The stack holds a runner service, which executes the job in a subsystem image, and the
services the job needs next to it (SITL, Gazebo). Names come from the job's instance scope
and published ports are dropped, so any number of stacks run side by side on one host and
in one project (project_compose).

A job with an observation (cluster/worker_node/job_observation.py) is observable live: while its
runner runs, every change of the control node's request is copied into the runner's job folder
(OBSERVE_DOCUMENT), and the frame lines the runner writes are taken out of its log and handed
to the observation (job_container_io.py). The job's timeout leaves out the time it was
observed, since an observed run is paced to a chosen speed.

An attended job (start_timeout_s) brings its stack up and waits for the operator's Start, which
reaches the runner as the request to observe does. The wait does not count against the job's
timeout. The ports the stack publishes for a ground control station (published_ports) are
read once Docker assigned them and go out in the detail of the job's status.

Every container of the stack logs to a bounded Docker log (BOUNDED_LOGGING): the frame lines
of an observed run and a simulator's chatter would otherwise fill the worker node's disk until the
stack is removed. The log follower reads the lines as they come, so the rotation never loses
one it needs.
"""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from typing import TYPE_CHECKING, Any, Collection, Dict, List, Mapping, Optional, Tuple

from scenegems_tool.cluster.protocol.messages import STATUS_GROUND_CONTROL, LogStream
from scenegems_tool.cluster.worker_node.instance_scope import InstanceScope
from scenegems_tool.cluster.worker_node.job_report import JobFailed, JobReport, JobResultData, StatusDetailReport
from scenegems_tool.cluster.worker_node.launchers.compose_project import ComposeProject
from scenegems_tool.cluster.worker_node.launchers.docker_cli import copy_from_container, copy_into_container
from scenegems_tool.cluster.worker_node.launchers.per_job.job_container_io import (
    JOB_CONTAINER_MAIN,
    JOB_DOCUMENT,
    JOB_FOLDER,
    OBSERVE_DOCUMENT,
    RESULT_DOCUMENT,
    ObservationControl,
    parse_frame_line,
    parse_status,
)

if TYPE_CHECKING:
    from scenegems_tool.cluster.worker_node.job_observation import JobObservation

RUNNER_SERVICE = "runner"
_WAIT_POLL_S = 0.2
_LOG_DRAIN_TIMEOUT_S = 5.0
_PUBLISHED_PORT_TIMEOUT_S = 30.0  # how long the launcher waits for Docker to assign a published port
_PUBLISHED_PORT_POLL_S = 0.5
_START_MARGIN_S = 60.0  # the runner gives up waiting for its Start itself; the launcher ends it this much later at the latest
_CONTROL_WAIT_S = 0.5  # how often the request copier looks at its stop event, and its pause after a failed copy
# The Docker log of each container of a job stack: at most 3 files of 10 MB
BOUNDED_LOGGING = {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}


def bounded_logging() -> dict:
    """A copy of BOUNDED_LOGGING per service: PyYAML writes an object shared by two services as an anchor."""
    return {"driver": BOUNDED_LOGGING["driver"], "options": dict(BOUNDED_LOGGING["options"])}


def runner_service(
    image: str,
    *,
    networks: Optional[List[str]] = None,
    depends_on: Optional[List[str]] = None,
    environment: Optional[Dict[str, str]] = None,
) -> dict:
    """The service that runs the job's in-container part; without networks it has no network at all.

    environment replaces the Python job main's own, for a runner that needs more than it (a simulation's vessel stack).
    """
    service: dict = {
        "image": image,
        "command": ["python", "-m", JOB_CONTAINER_MAIN],
        "environment": dict(environment) if environment is not None else {"PYTHONUNBUFFERED": "1"},
        "logging": bounded_logging(),
    }
    if depends_on:
        service["depends_on"] = list(depends_on)
    if networks:
        service["networks"] = list(networks)
    else:
        service["network_mode"] = "none"
    return service


def scope_services(scope: InstanceScope, services: Dict[str, dict], published: Collection[str] = ()) -> Dict[str, dict]:
    """Container names from the scope; published ports dropped, since instances share the host, but for the services named in published,
    whose ports Docker assigns; a bounded log unless the service sets its own."""
    scoped = {}
    for key, service in services.items():
        service = dict(service)
        service["container_name"] = scope.container_name(key)
        if key not in published:
            service.pop("ports", None)
        service.pop("restart", None)  # a job's containers stop with the job
        service.setdefault("logging", bounded_logging())
        scoped[key] = service
    return scoped


def _labels(labels: Any) -> Dict[str, str]:
    """A compose labels entry, a map or a list of key=value, as a map."""
    if not labels:
        return {}
    if isinstance(labels, dict):
        return {str(key): str(value) for key, value in labels.items()}
    return dict(str(label).partition("=")[::2] for label in labels)


def _is_external(definition: Any) -> bool:
    return bool(isinstance(definition, dict) and definition.get("external"))


def _service_networks(networks: Any, network_keys: Dict[str, str], alias: str) -> Dict[str, Any]:
    """A service's networks as a map under their keys in the project, with the alias on the stack's own networks: there the stack's services reach each other by it."""
    entries = dict(networks) if isinstance(networks, dict) else {network: None for network in networks}
    scoped: Dict[str, Any] = {}
    for network, entry in entries.items():
        if network in network_keys:
            entry = dict(entry or {})
            entry["aliases"] = sorted({*entry.get("aliases", []), alias})
        scoped[network_keys.get(network, network)] = entry
    return scoped


def project_compose(scope: InstanceScope, compose: dict) -> dict:
    """A stack's compose document as it runs in the worker node's project, next to the daemon and every other instance.

    Compose tells the containers and the networks of a project apart by their keys in the file,
    so the key of each service and of each network of the stack becomes unique in the project
    (scope.service_key) and the references between them follow; two stacks with a network of
    the same key would otherwise take each other's away. The name a service has inside the
    stack stays as its alias on the stack's own networks, since that is the name the runner
    dials. Every container and every network of the stack carries the instance's label, which
    is how the stack is removed, and a network gets a name of its own instead of the project's.
    A network the stack only joins (external) keeps its key and its name.
    """
    network_keys = {key: scope.service_key(key) for key, definition in (compose.get("networks") or {}).items() if not _is_external(definition)}
    keys = {key: scope.service_key(key) for key in compose["services"]}
    services: Dict[str, dict] = {}
    for key, service in compose["services"].items():
        service = dict(service)
        service["labels"] = {**_labels(service.get("labels")), **scope.labels}
        dependencies = service.get("depends_on")
        if isinstance(dependencies, dict):
            service["depends_on"] = {keys.get(name, name): condition for name, condition in dependencies.items()}
        elif dependencies:
            service["depends_on"] = [keys.get(name, name) for name in dependencies]
        if service.get("networks"):
            service["networks"] = _service_networks(service["networks"], network_keys, key)
        services[keys[key]] = service
    document = {**compose, "services": services}
    if compose.get("networks"):
        networks: Dict[str, Any] = {}
        for key, definition in compose["networks"].items():
            if key in network_keys:
                definition = {**(definition or {}), "name": (definition or {}).get("name") or scope.network_name(key), "labels": {**_labels((definition or {}).get("labels")), **scope.labels}}
            networks[network_keys.get(key, key)] = definition
        document["networks"] = networks
    return document


class JobStack:
    def __init__(self, scope: InstanceScope, services: Dict[str, dict], *, networks: Optional[dict] = None, volumes: Optional[dict] = None, published: Collection[str] = ()):
        if RUNNER_SERVICE not in services:
            raise ValueError(f"A job stack needs a {RUNNER_SERVICE!r} service")
        self.scope = scope
        self.compose: dict = {"services": scope_services(scope, services, published)}
        if networks:
            self.compose["networks"] = networks
        if volumes:
            self.compose["volumes"] = volumes
        self.runner_container = scope.container_name(RUNNER_SERVICE)
        self.project = ComposeProject(scope.compose_project, f"{scope.folder}/docker-compose.yml", instance=scope.key)

    def run(
        self,
        job_document: dict,
        report: JobReport,
        *,
        timeout_s: float,
        cancel: Optional[threading.Event] = None,
        observation: Optional["JobObservation"] = None,
        paced: bool = True,
        start_timeout_s: Optional[float] = None,
        published_ports: Optional[Mapping[str, Tuple[str, int]]] = None,
    ) -> JobResultData:
        """Create the stack, hand the runner its job, wait for it to stop and return its result. The stack is removed either way.

        paced: the runner slows down while observed, so the observed time does not count against timeout_s.
        start_timeout_s: the runner waits for the operator's Start, at most this long; timeout_s counts from the Start.
        published_ports: by a label of the caller (an agent id), the service and the container port whose host port is reported
        in the status detail (STATUS_GROUND_CONTROL).
        """
        stop_requests = threading.Event()
        try:
            self.project.force_remove(networks=True)  # a leftover of an earlier run of this scope
            self.project.write(project_compose(self.scope, self.compose))
            report.status("creating the job stack")
            self.project.create()
            self._copy_job_document(job_document)
            self.project.start()
            if published_ports:
                report = StatusDetailReport(report)
                threading.Thread(target=self._report_published_ports, args=(published_ports, report, stop_requests), name=f"{self.runner_container}_ports", daemon=True).start()
            report.status("running")
            followers = _follow_logs(self.runner_container, report, observation)
            if observation is not None:
                threading.Thread(target=self.copy_observation_requests, args=(observation, stop_requests), name=f"{self.runner_container}_observe", daemon=True).start()
            exit_code = self._wait(timeout_s, cancel, observation if paced else None, start=(observation, start_timeout_s) if observation is not None and start_timeout_s is not None else None)
            for follower in followers:
                follower.join(timeout=_LOG_DRAIN_TIMEOUT_S)
            outcome = self._read_outcome()
        except subprocess.CalledProcessError as error:
            raise JobFailed(f"Docker failed for job stack {self.scope.docker_name}: {error.stderr or error}", retryable=True) from error
        finally:
            stop_requests.set()
            self.project.force_remove(networks=True)
            shutil.rmtree(self.scope.folder, ignore_errors=True)
        if exit_code != 0 or "result" not in outcome:
            reason = outcome.get("error") or f"the runner exited with code {exit_code} and no result"
            raise JobFailed(str(reason), retryable=bool(outcome.get("retryable", False)))
        return outcome["result"]

    def _copy_job_document(self, job_document: dict) -> None:
        with tempfile.TemporaryDirectory(prefix="scenegems-job-") as folder:
            with open(os.path.join(folder, JOB_DOCUMENT), "w", encoding="utf-8") as file:
                json.dump(job_document, file)
            # "<folder>/." copies the folder's content and creates JOB_FOLDER in the container.
            copy_into_container(os.path.join(folder, "."), self.runner_container, JOB_FOLDER)

    def copy_observation_requests(self, observation: "JobObservation", stop: threading.Event) -> None:
        """Copies each new request of the observation into the runner's job folder until stop is set; the latest request wins."""
        applied = 0  # revision 0 is the request nobody made: nothing is written for a job that is never observed
        while not stop.is_set():
            control = observation.wait_for_change(applied, _CONTROL_WAIT_S)
            if control.revision == applied or stop.is_set():
                continue
            if self._copy_control(control):
                applied = control.revision
            else:
                stop.wait(_CONTROL_WAIT_S)

    def _copy_control(self, control: ObservationControl) -> bool:
        with tempfile.TemporaryDirectory(prefix="scenegems-observe-") as folder:
            local = os.path.join(folder, OBSERVE_DOCUMENT)
            with open(local, "w", encoding="utf-8") as file:
                file.write(control.to_document())
            try:
                copy_into_container(local, self.runner_container, f"{JOB_FOLDER}/{OBSERVE_DOCUMENT}")
                return True
            except subprocess.CalledProcessError:
                return False  # stopped meanwhile, or Docker had a hiccup: retried while the runner runs

    def _report_published_ports(self, published_ports: Mapping[str, Tuple[str, int]], report: StatusDetailReport, stop: threading.Event) -> None:
        """Reads the host ports Docker gave the published services, waiting a while for each, and adds them to the job's status detail."""
        ports: Dict[str, int] = {}
        deadline = time.monotonic() + _PUBLISHED_PORT_TIMEOUT_S
        while len(ports) < len(published_ports) and time.monotonic() < deadline and not stop.is_set():
            for label, (service, container_port) in published_ports.items():
                if label not in ports:
                    port = self.project.published_port(self.scope.service_key(service), container_port)
                    if port is not None:
                        ports[label] = port
            if len(ports) < len(published_ports):
                stop.wait(_PUBLISHED_PORT_POLL_S)
        if ports and not stop.is_set():
            report.add_detail({STATUS_GROUND_CONTROL: ports})

    def _wait(self, timeout_s: float, cancel: Optional[threading.Event], observation: Optional["JobObservation"] = None, start: Optional[Tuple["JobObservation", float]] = None) -> int:
        process = subprocess.Popen(["docker", "wait", self.runner_container], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        deadline = time.monotonic() + timeout_s
        waiting_since = time.monotonic()
        while True:
            try:
                output, _ = process.communicate(timeout=_WAIT_POLL_S)
                return int(output.strip().splitlines()[-1])
            except subprocess.TimeoutExpired:
                pass
            except (ValueError, IndexError) as error:
                raise JobFailed(f"Could not read the exit code of {self.runner_container}", retryable=True) from error
            if cancel is not None and cancel.is_set():
                process.kill()
                raise JobFailed("cancelled", retryable=False)
            if start is not None:
                start_observation, start_timeout_s = start
                if start_observation.started:
                    start = None
                    deadline = time.monotonic() + timeout_s  # the job's time counts from the operator's Start
                elif time.monotonic() > waiting_since + start_timeout_s + _START_MARGIN_S:
                    process.kill()
                    raise JobFailed(f"nobody started the run within {start_timeout_s:g} s", retryable=False)
                continue
            observed_s = observation.observed_seconds() if observation is not None else 0.0
            if time.monotonic() > deadline + observed_s:
                process.kill()
                raise JobFailed(f"timed out after {timeout_s:g} s" + (f" (and {observed_s:.0f} s observed)" if observed_s else ""), retryable=True)

    def _read_outcome(self) -> dict:
        with tempfile.TemporaryDirectory(prefix="scenegems-result-") as folder:
            local = os.path.join(folder, RESULT_DOCUMENT)
            if not copy_from_container(self.runner_container, f"{JOB_FOLDER}/{RESULT_DOCUMENT}", local):
                return {}
            with open(local, encoding="utf-8") as file:
                return json.load(file)


def forward_runner_line(line: str, stream: LogStream, container: str, report: JobReport, observation: Optional["JobObservation"] = None) -> None:
    """One line of the runner's output: a status line as status, a frame line to the observation (never as a log line), the rest as a log line."""
    line = line.rstrip("\r\n")
    if stream == LogStream.STDOUT:
        status = parse_status(line)
        if status is not None:
            message, progress, detail = status
            if detail is None:
                report.status(message, progress)
            else:
                report.status(message, progress, detail)
            return
        frame = parse_frame_line(line)
        if frame is not None:
            if observation is not None:
                observation.add_frames([(frame, len(line))])
            return
    if line:
        report.log(container, line, stream)


def _follow_logs(container: str, report: JobReport, observation: Optional["JobObservation"] = None) -> List[threading.Thread]:
    """Forward the container's output until it stops (forward_runner_line)."""
    process = subprocess.Popen(["docker", "logs", "-f", container], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")

    def forward(pipe, stream: LogStream) -> None:
        for line in pipe:
            forward_runner_line(line, stream, container, report, observation)

    followers = [
        threading.Thread(target=forward, args=(process.stdout, LogStream.STDOUT), name=f"{container}_stdout", daemon=True),
        threading.Thread(target=forward, args=(process.stderr, LogStream.STDERR), name=f"{container}_stderr", daemon=True),
    ]
    for follower in followers:
        follower.start()
    return followers
