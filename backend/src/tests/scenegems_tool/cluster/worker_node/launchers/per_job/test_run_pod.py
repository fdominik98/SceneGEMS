"""A run as a pod, against a fake of the cluster API: the translation of every stack of the matrix, the refusals, the run's
files, its log, its time rules, cancel, the cleanup after a failure at each step and the node ports of an attended run.

The node's part (starting the containers, the runner's log, its end and its result.json) is played by Kubelet on the
test's clock, which is also the run's: a run of minutes takes no time.
"""

import io
import json
import os
import re
import threading
import time
from typing import Callable, Dict, List, Optional

import pytest
from kubernetes.client.exceptions import ApiException

from scenegems_tool.cluster.protocol.messages import LogStream
from scenegems_tool.cluster.worker_node import instance_scope
from scenegems_tool.cluster.worker_node.instance_scope import INSTANCE_LABEL, WORKER_NODE_LABEL, InstanceScope
from scenegems_tool.cluster.worker_node.job_observation import JobObservation
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.jobs.in_container.run_observation import ContainerObservation
from scenegems_tool.cluster.worker_node.launchers.kubernetes_api import ClusterPlace, Kind, OwnerReference
from scenegems_tool.cluster.worker_node.launchers.per_job import run_pod
from scenegems_tool.cluster.worker_node.launchers.per_job.job_container_io import (
    JOB_CONTAINER_MAIN,
    JOB_DOCUMENT,
    JOB_FOLDER,
    OBSERVE_DOCUMENT,
    RESULT_DOCUMENT,
    ObservationControl,
    format_frame_line,
    format_status_line,
)
from scenegems_tool.cluster.worker_node.launchers.per_job.run_pod import (
    RUN_COMPONENT,
    RUN_COMPONENT_LABEL,
    RUNNER_SERVICE,
    RunnerLog,
    RunPod,
    UntranslatableStack,
    forward_runner_line,
    interpolate,
    run_pod_selector,
    runner_service,
    split_timestamp,
)
from scenegems_tool.vessel_stack.simulation_docker_stack import build_simulation_docker_stack_artifacts
from tests.scenegems_tool.cluster.worker_node.fake_kubernetes import FakeCluster
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, mqtt_connection
from tests.scenegems_tool.vessel_stack.test_stack_ports import CASES, VESSEL_IDS, listeners_of, trajectories_of
from tests.scenegems_tool.vessel_stack.test_stack_service_names import ENDPOINT_HOST, EXTERNAL_HOSTS, IP_ADDRESS, instance_named_as_a_run_names_it
from utils.file_system_utils import RUNTIME_ASSETS_VOLUME

SCOPE = InstanceScope.per_job("m1", "n1", "simulation", "j7")
POOL_POD = OwnerReference("v1", "Pod", "n1-simulation-subsystem-5d8f9-x2x7q", "uid-pool")
PLACE = ClusterPlace("scenegems", "k3d-lab-server-0", "/var/lib/scenegems/n1/runtime", POOL_POD)
RUNNER_IMAGE = "scenegems-simulation-subsystem:k4"
NAME = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
RESULT = {"result": {"steps": 120, "state_digest": "abc"}}


class Clock:
    """The run's clock: every sleep moves it on at once and calls the hooks with the new time."""

    def __init__(self) -> None:
        self.now = 0.0
        self.hooks: List[Callable[[float], None]] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        for hook in list(self.hooks):
            hook(self.now)


class Kubelet:
    """The node's part: when the pod is created its containers start and the runner's log is there; at ends_at the runner
    writes its result (outcome, unless None) into its job folder and ends with exit_code. start_runner False keeps the runner waiting."""

    def __init__(self, cluster: FakeCluster, clock: Clock, pod: RunPod, *, lines=(), ends_at: Optional[float] = 1.0, exit_code: int = 0, outcome: Optional[dict] = None, start_runner: bool = True):
        self.cluster, self.pod = cluster, pod
        self.lines, self.ends_at, self.exit_code = list(lines), ends_at, exit_code
        self.outcome = RESULT if outcome is None and exit_code == 0 else outcome
        self.start_runner = start_runner
        self.created: Optional[dict] = None
        self.job_folder_at_create: List[str] = []
        self.ended = False
        cluster.on_create.append(self._created)
        clock.hooks.append(self._tick)

    def _created(self, kind, held) -> None:
        if kind != Kind.POD:
            return
        self.created = held
        self.job_folder_at_create = sorted(os.listdir(self.pod.job_folder))
        for sidecar in held["spec"].get("initContainers", []):
            self.cluster.set_container_state(held["metadata"]["name"], sidecar["name"], "running")
        if self.start_runner:
            self.cluster.set_container_state(held["metadata"]["name"], RUNNER_SERVICE, "running")
            self.cluster.set_phase(held["metadata"]["name"], "Running")
            self.cluster.add_log(held["metadata"]["name"], RUNNER_SERVICE, [f"2026-11-17T10:00:{index:02d}.{index:09d}Z {line}" for index, line in enumerate(self.lines)])
        else:
            self.cluster.set_container_state(held["metadata"]["name"], RUNNER_SERVICE, "waiting", reason="PodInitializing")

    def _tick(self, now: float) -> None:
        if self.created is None or self.ended or self.ends_at is None or now < self.ends_at or self.cluster.get(Kind.POD, self.pod.name) is None:
            return
        if self.outcome is not None:
            with open(f"{self.pod.job_folder}/{RESULT_DOCUMENT}", "w", encoding="utf-8") as file:
                json.dump(self.outcome, file)
        self.cluster.set_container_state(self.pod.name, RUNNER_SERVICE, "terminated", exitCode=self.exit_code, reason="Completed" if self.exit_code == 0 else "Error")
        self.ended = True


class RecordingReport:
    def __init__(self) -> None:
        self.statuses: List[tuple] = []
        self.lines: List[tuple] = []

    def status(self, message, progress=None, detail=None) -> None:
        self.statuses.append((message, progress, detail))

    def log(self, source, text, stream=LogStream.STDOUT) -> None:
        self.lines.append((source, text, stream))


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    """The runtime folder as the simulation subsystem has it mounted: its instances folder holds the runs' folders."""
    folder = tmp_path / "runtime"
    (folder / "instances").mkdir(parents=True)
    monkeypatch.setattr(instance_scope, "INSTANCES_FOLDER", str(folder / "instances").replace("\\", "/"))
    monkeypatch.setattr(run_pod, "_WAIT_POLL_S", 0.01)  # the log follower's pauses are real ones
    monkeypatch.setattr(run_pod, "_LOG_RECONNECT_S", 0.01)
    return folder


@pytest.fixture
def cluster() -> FakeCluster:
    return FakeCluster(assign_node_ports=True)


@pytest.fixture
def clock() -> Clock:
    return Clock()


def kinematic_services(**runner_options) -> Dict[str, dict]:
    return {
        "kinematic-sim": {"image": "${SIMULATION_IMAGE:-scenegems-simulation-subsystem:latest}", "command": ["python", "-m", "sim", "--port", "11430"], "networks": ["maritime_net"]},
        "os-asv-system": {
            "image": "scenegems-simulation-subsystem:latest",
            "command": ["python", "-m", "replay", "--port", "12000"],
            "networks": ["maritime_net"],
            "environment": {"PYTHONUNBUFFERED": "1"},
        },
        "os-mavproxy": {"image": "mavproxy", "ports": ["12200"], "networks": ["maritime_net"], "tty": True, "stdin_open": True, "restart": "unless-stopped"},
        RUNNER_SERVICE: runner_service(RUNNER_IMAGE, **runner_options),
    }


def make_pod(cluster: FakeCluster, clock: Clock, services: Optional[Dict[str, dict]] = None, **options) -> RunPod:
    return RunPod(
        SCOPE,
        services if services is not None else kinematic_services(),
        cluster=PLACE,
        api=cluster.api(),
        networks={"maritime_net": {"driver": "bridge"}},
        environ=options.pop("environ", {}),
        clock=clock.monotonic,
        sleep=clock.sleep,
        **options,
    )


# The translation of every stack of the matrix


def matrix_pod(stack, adapter_ids) -> tuple:
    writes, compose = build_simulation_docker_stack_artifacts(instance_named_as_a_run_names_it(stack, VESSEL_IDS, adapter_ids), trajectories_of(VESSEL_IDS), mqtt_connection(), GEOFENCE)
    services = {**compose["services"], RUNNER_SERVICE: runner_service(RUNNER_IMAGE)}
    pod = RunPod(SCOPE, services, cluster=PLACE, networks=compose.get("networks"), volumes=compose.get("volumes"), environ={})
    return compose, writes, pod


@pytest.mark.parametrize("name, stack, adapter_ids", CASES, ids=[case[0] for case in CASES])
def test_every_stack_of_the_matrix_becomes_a_pod_with_nothing_dropped_no_port_twice_and_only_valid_names(runtime, cluster, name, stack, adapter_ids):
    compose, writes, pod = matrix_pod(stack, adapter_ids)
    manifest = pod.manifest()
    spec = manifest["spec"]
    sidecars, [runner] = spec.get("initContainers", []), spec["containers"]
    containers = [*sidecars, runner]
    names = [container["name"] for container in containers]
    assert sorted(names) == sorted([*compose["services"], RUNNER_SERVICE]) and len(set(names)) == len(names), "a container per service, named after it"
    assert all(NAME.match(container_name) and len(container_name) <= 63 for container_name in names)
    assert runner["name"] == RUNNER_SERVICE and runner["args"] == ["python", "-m", JOB_CONTAINER_MAIN]
    assert all(sidecar["restartPolicy"] == "Always" for sidecar in sidecars), "every other service is a sidecar"
    [aliases] = spec["hostAliases"]
    assert aliases["ip"] == "127.0.0.1" and set(aliases["hostnames"]) == set(names)
    assert all(NAME.match(host) for host in aliases["hostnames"])
    for service_name, service in compose["services"].items():
        container = next(container for container in containers if container["name"] == service_name)
        assert "${" not in container["image"] and container["image"], "the image's variable is taken as compose takes it"
        assert len(container.get("env", [])) == len(service.get("environment") or []), f"{service_name}: every variable"
        assert len(container.get("volumeMounts", [])) == len(service.get("volumes") or []), f"{service_name}: every volume"
        assert len(container.get("ports", [])) == len(service.get("ports") or []), f"{service_name}: every port"
        dialled = set(ENDPOINT_HOST.findall(" ".join([*container.get("command", []), *container.get("args", []), *(entry["value"] for entry in container.get("env", []))])))
        assert {host for host in dialled if host not in EXTERNAL_HOSTS and not IP_ADDRESS.match(host)} <= set(aliases["hostnames"]), f"{service_name} dials only names of the pod"
        position = names.index(service_name)
        for dependency in service.get("depends_on") or []:
            assert names.index(dependency) < position, f"{service_name} starts after {dependency}"
    declared = [(port["protocol"], port["containerPort"]) for container in containers for port in container.get("ports", [])]
    assert len(declared) == len(set(declared)), "no two containers declare one port"
    as_compose = {
        "services": {
            container["name"]: {"command": [*container.get("command", []), *container.get("args", [])], "environment": {entry["name"]: entry["value"] for entry in container.get("env", [])}}
            for container in containers
        }
    }
    listeners = [(protocol, port) for _, protocol, port in listeners_of(as_compose, writes)]
    assert len(listeners) == len(set(listeners)), f"{name}: no two containers of the pod listen on one port"
    cluster.api().create_pod(manifest)  # the client's models take it: every field it requires is there


def test_the_matrix_has_stacks_with_every_kind_of_key_the_translation_knows():
    """A guard on the test above: the stacks it translates use what the translation has rules for."""
    seen = set()
    for _, stack, adapter_ids in CASES:
        _, compose = build_simulation_docker_stack_artifacts(instance_named_as_a_run_names_it(stack, (0, 1), adapter_ids), trajectories_of((0, 1)), mqtt_connection(), GEOFENCE)
        for service in compose["services"].values():
            seen.update(service)
    assert {"image", "command", "entrypoint", "environment", "volumes", "ports", "tty", "stdin_open", "depends_on", "restart", "networks", "hostname", "extra_hosts"} == seen


# The pod


def test_the_pod_is_the_runner_with_sidecars_on_the_node_owned_by_the_pool(runtime, cluster, clock):
    pod = make_pod(cluster, clock)
    manifest = pod.manifest()
    metadata, spec = manifest["metadata"], manifest["spec"]
    assert metadata["name"] == SCOPE.name == "n1-simulation-subsystem-j7" and metadata["namespace"] == "scenegems"
    assert metadata["labels"] == {INSTANCE_LABEL: "j7-1", WORKER_NODE_LABEL: "n1", RUN_COMPONENT_LABEL: RUN_COMPONENT}
    assert metadata["ownerReferences"] == [{"apiVersion": "v1", "kind": "Pod", "name": POOL_POD.name, "uid": "uid-pool"}], "a pool that goes takes its runs with it"
    assert spec["restartPolicy"] == "Never" and spec["terminationGracePeriodSeconds"] == 3
    assert spec["nodeSelector"] == {"kubernetes.io/hostname": "k3d-lab-server-0"}
    assert spec["automountServiceAccountToken"] is False and spec["enableServiceLinks"] is False
    assert spec["volumes"] == [{"name": "runtime", "hostPath": {"path": "/var/lib/scenegems/n1/runtime", "type": "Directory"}}]
    assert [sidecar["name"] for sidecar in spec["initContainers"]] == ["kinematic-sim", "os-asv-system", "os-mavproxy"]
    simulator, replay, mavproxy = spec["initContainers"]
    assert simulator == {
        "name": "kinematic-sim",
        "image": "scenegems-simulation-subsystem:latest",
        "imagePullPolicy": "IfNotPresent",
        "args": ["python", "-m", "sim", "--port", "11430"],
        "restartPolicy": "Always",
    }
    assert replay["env"] == [{"name": "PYTHONUNBUFFERED", "value": "1"}]
    assert mavproxy["tty"] is True and mavproxy["stdin"] is True and mavproxy["ports"] == [{"containerPort": 12200, "protocol": "TCP"}]
    [runner] = spec["containers"]
    assert runner == {
        "name": RUNNER_SERVICE,
        "image": RUNNER_IMAGE,
        "imagePullPolicy": "IfNotPresent",
        "args": ["python", "-m", JOB_CONTAINER_MAIN],
        "env": [{"name": "PYTHONUNBUFFERED", "value": "1"}],
        "volumeMounts": [{"name": "runtime", "mountPath": JOB_FOLDER, "subPath": "instances/n1-simulation-subsystem-j7/job"}],
    }
    assert spec["hostAliases"] == [{"ip": "127.0.0.1", "hostnames": ["kinematic-sim", "os-asv-system", "os-mavproxy", "runner"]}]


def test_a_service_starts_after_what_it_depends_on_and_the_rest_in_the_stacks_order():
    services = {
        "gazebo": {"image": "gz", "depends_on": ["os", "ts1"]},
        "os": {"image": "sitl"},
        "os-arduagent": {"image": "agent", "depends_on": {"os-mavproxy": {"condition": "service_started"}}},
        "os-mavproxy": {"image": "mavproxy"},
        "ts1": {"image": "sitl"},
        RUNNER_SERVICE: runner_service("runner"),
    }
    assert run_pod.start_order(services) == ["os", "ts1", "gazebo", "os-mavproxy", "os-arduagent", "runner"]


def test_variables_are_taken_as_compose_takes_them():
    environ = {"SET": "value", "EMPTY": ""}
    assert interpolate("${SET:-default} ${UNSET:-default} ${EMPTY:-default} ${EMPTY-default} ${UNSET-default}", environ) == "value default default  default"
    assert interpolate("$SET ${SET} $$SET ${UNSET} cost: $$5", environ) == "value value $SET  cost: $5"
    with pytest.raises(UntranslatableStack, match="UNSET is required: give it"):
        interpolate("${UNSET:?give it}", environ)
    with pytest.raises(UntranslatableStack, match="EMPTY is required"):
        interpolate("${EMPTY:?}", environ)
    assert interpolate("${EMPTY?}", environ) == ""


def test_the_image_overrides_of_the_subsystems_environment_name_the_images():
    services = {"os": {"image": "${SITL_IMAGE:-scenegems-ardupilot-sitl:latest}"}, RUNNER_SERVICE: runner_service("runner")}
    pod = RunPod(SCOPE, services, environ={"SITL_IMAGE": "registry:5000/scenegems-ardupilot-sitl@sha256:abc"})
    assert pod.translation["sidecars"][0]["image"] == "registry:5000/scenegems-ardupilot-sitl@sha256:abc"


def test_strings_are_split_as_compose_splits_them_and_an_entrypoint_is_the_command():
    services = {"gazebo": {"image": "gz", "entrypoint": "/bin/bash -c 'exec run.sh'", "command": "--verbose 4"}, RUNNER_SERVICE: runner_service("runner")}
    [gazebo] = RunPod(SCOPE, services).translation["sidecars"]
    assert gazebo["command"] == ["/bin/bash", "-c", "exec run.sh"] and gazebo["args"] == ["--verbose", "4"]


def test_a_variable_list_a_hostname_of_its_own_name_and_extra_hosts_are_translated():
    services = {
        "gazebo": {"image": "gz", "hostname": "gazebo", "environment": ["A=1", "B=x=y"], "extra_hosts": ["host.docker.internal:host-gateway", "registry:10.0.0.5"]},
        "os": {"image": "sitl", "networks": {"maritime_net": {"aliases": ["sitl-0"]}}},
        RUNNER_SERVICE: runner_service("runner"),
    }
    translation = RunPod(SCOPE, services, networks={"maritime_net": None}).translation
    assert translation["sidecars"][0]["env"] == [{"name": "A", "value": "1"}, {"name": "B", "value": "x=y"}]
    assert translation["hostAliases"] == [
        {"ip": "127.0.0.1", "hostnames": ["gazebo", "os", "runner", "sitl-0"]},
        {"ip": "10.0.0.5", "hostnames": ["registry"]},
    ], "Docker's host-gateway has nothing to stand for in a pod"


@pytest.mark.parametrize(
    "service, message",
    [
        ({"image": "x", "privileged": True}, "has privileged, which the translation into a pod does not know"),
        ({"image": "x", "cap_add": ["NET_ADMIN"], "devices": ["/dev/ttyS0"]}, "has cap_add, devices"),
        ({"image": "x", "volumes": ["/tmp:/data"]}, "the volume '/tmp'"),
        ({"image": "x", "volumes": ["other:/data"]}, "the volume 'other'"),
        ({"image": "x", "volumes": [f"{RUNTIME_ASSETS_VOLUME}:/data:z"]}, "has the mode 'z'"),
        ({"image": "x", "volumes": [{"type": "bind", "source": "/tmp", "target": "/data"}]}, "the volume"),
        ({"image": "x", "networks": ["scenegems_broker"]}, "the network 'scenegems_broker' is not one of the stack's"),
        ({"image": "x", "networks": {"maritime_net": {"ipv4_address": "10.0.0.2"}}}, "with \\['ipv4_address'\\]"),
        ({"image": "x", "hostname": "elsewhere"}, "has the hostname 'elsewhere'"),
        ({"image": "x", "depends_on": ["missing"]}, "depends on missing, which the stack does not have"),
        ({"image": "x", "depends_on": {"os": {"condition": "service_healthy"}}}, "condition 'service_healthy'"),
        ({"image": "x", "environment": ["FROM_HOST"]}, "the variable FROM_HOST has no value"),
        ({"image": "x", "environment": {"FROM_HOST": None}}, "the variable FROM_HOST has no value"),
        ({"image": "x", "ports": ["5760-5769"]}, "is not one port"),
        ({"image": "x", "ports": ["5760/quic"]}, "has the protocol 'quic'"),
        ({"image": "x", "extra_hosts": ["somewhere:example.org"]}, "needs an IPv4 address"),
        ({"command": ["x"]}, "has no image"),
    ],
)
def test_a_service_the_pod_cannot_hold_is_refused_by_name(service, message):
    services = {"os": {"image": "sitl"}, "bad": service, RUNNER_SERVICE: runner_service("runner")}
    with pytest.raises(UntranslatableStack, match=message) as refusal:
        RunPod(SCOPE, services, networks={"maritime_net": {"driver": "bridge"}}, volumes={RUNTIME_ASSETS_VOLUME: {"external": True}})
    assert not refusal.value.retryable and str(refusal.value).startswith("The run's stack cannot become a pod: ")


@pytest.mark.parametrize(
    "stack, message",
    [
        ({"services": {RUNNER_SERVICE: runner_service("r")}, "configs": {}}, "the stack has \\['configs'\\]"),
        ({"services": {RUNNER_SERVICE: runner_service("r")}, "networks": {"broker": {"external": True}}}, "the network broker"),
        ({"services": {"os": {"image": "sitl"}}}, "it needs a 'runner' service"),
        ({"services": {"vessel_0": {"image": "sitl"}, RUNNER_SERVICE: runner_service("r")}}, "the service 'vessel_0' is not a valid name in a pod"),
        ({"services": {"a": {"image": "x", "depends_on": ["b"]}, "b": {"image": "x", "depends_on": ["a"]}, RUNNER_SERVICE: runner_service("r")}}, "in a circle: a to b to a"),
    ],
)
def test_a_stack_the_pod_cannot_hold_is_refused(stack, message):
    with pytest.raises(UntranslatableStack, match=message):
        run_pod.translate_stack(stack, {})


def test_a_runs_folder_off_the_runtime_folder_cannot_be_mounted(runtime, cluster, clock, monkeypatch, tmp_path):
    pod = make_pod(cluster, clock)
    assert pod.job_sub_path() == "instances/n1-simulation-subsystem-j7/job"
    monkeypatch.setattr(RunPod, "job_folder", property(lambda self: str(tmp_path / "outside" / "job")))
    with pytest.raises(JobFailed, match="is not on the runtime folder"):
        pod.manifest()


# A run


def test_a_run_writes_its_job_creates_the_pod_reads_the_result_and_removes_everything(runtime, cluster, clock):
    pod = make_pod(cluster, clock)
    kubelet = Kubelet(cluster, clock, pod, lines=[format_status_line("running the kinematic replay run", 0.5), "a line of the runner"], ends_at=3.0)
    report = RecordingReport()
    result = pod.run({"job": {"job_id": "j7"}}, report, timeout_s=60.0)
    assert result == RESULT["result"]
    assert kubelet.job_folder_at_create == [JOB_DOCUMENT], "the job document is there before the pod"
    assert [(message, progress) for message, progress, _ in report.statuses] == [("creating the run's pod", None), ("running", None), ("running the kinematic replay run", 0.5)]
    assert report.lines == [(f"{SCOPE.name}/runner", "a line of the runner", LogStream.STDOUT)]
    assert cluster.names(Kind.POD) == [] and cluster.names(Kind.SERVICE) == []
    assert not os.path.exists(SCOPE.folder), "the run's folder goes with it"
    first_call = cluster.log_calls[0]
    assert first_call["container"] == RUNNER_SERVICE and first_call["follow"] and first_call["timestamps"] and "since_seconds" not in first_call
    assert all(call["since_seconds"] for call in cluster.log_calls[1:]), "a later connection (the runner still ran when one ended) starts from about the last line"


def test_the_job_document_is_what_the_runner_reads(runtime, cluster, clock):
    pod = make_pod(cluster, clock)
    documents = []
    cluster.on_create.append(lambda kind, held: documents.append(json.load(open(f"{pod.job_folder}/{JOB_DOCUMENT}", encoding="utf-8"))) if kind == Kind.POD else None)
    Kubelet(cluster, clock, pod)
    pod.run({"job": {"job_id": "j7", "payload": {"runner": "kinematic"}}}, RecordingReport(), timeout_s=60.0)
    assert documents == [{"job": {"job_id": "j7", "payload": {"runner": "kinematic"}}}]


def test_a_runner_that_failed_with_a_reason_fails_the_run_with_it(runtime, cluster, clock):
    pod = make_pod(cluster, clock)
    Kubelet(cluster, clock, pod, exit_code=1, outcome={"error": "Simulation payload rejected: no vessel", "retryable": False})
    with pytest.raises(JobFailed, match="Simulation payload rejected: no vessel") as failure:
        pod.run({}, RecordingReport(), timeout_s=60.0)
    assert not failure.value.retryable and cluster.names(Kind.POD) == [] and not os.path.exists(SCOPE.folder)


def test_a_runner_that_ended_without_a_result_fails_the_run_with_its_exit_code(runtime, cluster, clock):
    pod = make_pod(cluster, clock)
    Kubelet(cluster, clock, pod, exit_code=137)
    with pytest.raises(JobFailed, match="the runner exited with code 137 and no result"):
        pod.run({}, RecordingReport(), timeout_s=60.0)


def test_a_container_whose_image_cannot_be_pulled_fails_the_run_and_the_pod_goes(runtime, cluster, clock):
    pod = make_pod(cluster, clock)
    Kubelet(cluster, clock, pod, ends_at=None, start_runner=False)
    cluster.on_create.append(lambda kind, held: cluster.set_container_state(pod.name, "os-mavproxy", "waiting", reason="ImagePullBackOff", message="mavproxy: not found") if kind == Kind.POD else None)
    with pytest.raises(JobFailed, match="The container os-mavproxy of the run cannot start: ImagePullBackOff: mavproxy: not found") as failure:
        pod.run({}, RecordingReport(), timeout_s=60.0)
    assert failure.value.retryable and cluster.names(Kind.POD) == []


def test_a_pod_that_is_gone_or_failed_before_its_runner_ended_fails_the_run(runtime, cluster, clock):
    pod = make_pod(cluster, clock)
    Kubelet(cluster, clock, pod, ends_at=None)
    clock.hooks.append(lambda now: cluster.objects.pop(("scenegems", Kind.POD, pod.name), None) if now >= 2.0 else None)
    with pytest.raises(JobFailed, match="is gone") as failure:
        pod.run({}, RecordingReport(), timeout_s=60.0)
    assert failure.value.retryable

    clock.hooks.clear()
    cluster.on_create.clear()
    Kubelet(cluster, clock, pod, ends_at=None)
    clock.hooks.append(lambda now: cluster.set_phase(pod.name, "Failed", reason="Evicted") if cluster.get(Kind.POD, pod.name) else None)
    with pytest.raises(JobFailed, match="failed before its runner ended: Evicted"):
        pod.run({}, RecordingReport(), timeout_s=60.0)


# Cleanup after a failure at each step


def test_a_pod_the_api_refuses_fails_the_run_for_good_and_leaves_nothing(runtime, cluster, clock):
    pod = make_pod(cluster, clock)
    cluster.fail_next["create"] = ApiException(status=403, reason="Forbidden")
    with pytest.raises(JobFailed, match="The cluster API failed for run n1-simulation-subsystem-j7: 403 Forbidden") as failure:
        pod.run({}, RecordingReport(), timeout_s=60.0)
    assert not failure.value.retryable and cluster.names(Kind.POD) == [] and not os.path.exists(SCOPE.folder)


def test_a_cluster_api_that_is_down_fails_the_run_for_another_attempt(runtime, cluster, clock):
    pod = make_pod(cluster, clock)
    cluster.fail_next["create"] = ApiException(status=503, reason="Service Unavailable")
    with pytest.raises(JobFailed) as failure:
        pod.run({}, RecordingReport(), timeout_s=60.0)
    assert failure.value.retryable


def test_a_service_the_api_refuses_takes_the_pod_with_it(runtime, cluster, clock):
    pod = make_pod(cluster, clock)
    Kubelet(cluster, clock, pod)
    cluster.on_create.append(lambda kind, held: cluster.fail_next.__setitem__("create", ApiException(status=422, reason="Invalid")) if kind == Kind.POD else None)
    with pytest.raises(JobFailed, match="422 Invalid"):
        pod.run({}, RecordingReport(), timeout_s=60.0, published_ports={"0": ("os-mavproxy", 12200)})
    assert cluster.names(Kind.POD) == [] and cluster.names(Kind.SERVICE) == [] and not os.path.exists(SCOPE.folder)


def test_a_pod_that_cannot_be_read_for_a_while_fails_the_run_and_is_removed(runtime, cluster, clock, monkeypatch):
    pod = make_pod(cluster, clock)
    Kubelet(cluster, clock, pod, ends_at=None)
    api = pod.api
    reads = []

    def unreadable(name):
        reads.append(clock.now)
        if clock.now >= 1.0:
            raise ApiException(status=500, reason="Internal Server Error")
        return type(api).read_pod(api, name)

    monkeypatch.setattr(api, "read_pod", unreadable)
    with pytest.raises(JobFailed, match="could not be read for 30 s: 500 Internal Server Error") as failure:
        pod.run({}, RecordingReport(), timeout_s=600.0)
    assert failure.value.retryable and 30.0 < clock.now < 32.0 and cluster.names(Kind.POD) == [], "an outage of a few seconds is ridden out"


def test_a_failed_delete_is_logged_and_does_not_hide_why_the_run_ended(runtime, cluster, clock, caplog):
    pod = make_pod(cluster, clock)
    Kubelet(cluster, clock, pod, exit_code=1, outcome={"error": "the helm crashed", "retryable": True})
    cluster.on_create.append(lambda kind, held: cluster.fail_next.__setitem__("delete", ApiException(status=500, reason="Internal Server Error")) if kind == Kind.POD else None)
    with pytest.raises(JobFailed, match="the helm crashed"):
        pod.run({}, RecordingReport(), timeout_s=60.0)
    assert "Could not delete the pod of run n1-simulation-subsystem-j7" in caplog.text
    assert not os.path.exists(SCOPE.folder)


def test_a_leftover_pod_of_the_runs_name_goes_first(runtime, cluster, clock):
    pod = make_pod(cluster, clock)
    cluster.add(Kind.POD, {"metadata": {"name": pod.name, "labels": dict(pod.labels)}, "spec": {"containers": [{"name": "runner"}]}})
    cluster.add(Kind.SERVICE, {"metadata": {"name": "gcs-old", "labels": dict(SCOPE.labels)}, "spec": {"ports": [{"port": 12200}]}})
    Kubelet(cluster, clock, pod)
    pod.run({}, RecordingReport(), timeout_s=60.0)
    first_delete = cluster.deletions[0]
    assert first_delete == {"kind": "Pod", "name": pod.name, "propagation_policy": "Background", "grace_period_seconds": 0}
    assert ("Service", "delete", "gcs-old") in cluster.calls
    assert cluster.calls.index(("Pod", "delete", pod.name)) < cluster.calls.index(("Pod", "create", pod.name))


# Ground control ports of an attended run


def test_a_ground_control_port_gets_a_node_port_which_every_status_detail_carries(runtime, cluster, clock):
    pod = make_pod(cluster, clock)
    services = []
    cluster.on_create.append(lambda kind, held: services.append(json.loads(json.dumps(held))) if kind == Kind.SERVICE else None)
    Kubelet(cluster, clock, pod, lines=[format_status_line("ready to start", None, {"phase": "ready_to_start"})])
    report = RecordingReport()
    pod.run({}, report, timeout_s=60.0, published_ports={"0": ("os-mavproxy", 12200)})
    [service] = services
    assert service["metadata"]["name"] == "gcs-n1-simulation-subsystem-j7-0"
    assert service["metadata"]["labels"] == pod.labels, "found by the run's labels, as leftovers too"
    assert service["metadata"]["ownerReferences"][0]["kind"] == "Pod" and service["metadata"]["ownerReferences"][0]["name"] == pod.name, "it goes with the run's pod"
    assert service["spec"]["type"] == "NodePort" and service["spec"]["selector"] == SCOPE.labels
    assert service["spec"]["ports"] == [{"name": "ground-control", "port": 12200, "targetPort": 12200, "protocol": "TCP", "nodePort": 30500}]
    assert report.statuses == [
        ("creating the run's pod", None, None),
        ("running", None, {"ground_control": {"0": 30500}}),
        ("ready to start", None, {"phase": "ready_to_start", "ground_control": {"0": 30500}}),
    ], "every status from the node port on carries it"
    assert cluster.names(Kind.SERVICE) == []


def test_a_service_without_a_node_port_fails_the_run(runtime, clock):
    cluster = FakeCluster(assign_node_ports=False)
    pod = make_pod(cluster, clock)
    Kubelet(cluster, clock, pod)
    with pytest.raises(JobFailed, match="gave the ground control port 12200 of os-mavproxy no port on the node"):
        pod.run({}, RecordingReport(), timeout_s=60.0, published_ports={"0": ("os-mavproxy", 12200)})


# The time rules


def test_the_jobs_timeout_ends_a_run_that_does_not_end(runtime, cluster, clock):
    pod = make_pod(cluster, clock)
    Kubelet(cluster, clock, pod, ends_at=None)
    cluster.on_create.append(lambda kind, held: cluster.set_container_state(pod.name, "os-asv-system", "waiting", reason="CrashLoopBackOff", restarts=4) if kind == Kind.POD else None)
    with pytest.raises(JobFailed, match="timed out after 5 s; not running: os-asv-system: CrashLoopBackOff") as failure:
        pod.run({}, RecordingReport(), timeout_s=5.0)
    assert failure.value.retryable and 5.0 < clock.now <= 5.5 and cluster.names(Kind.POD) == []


def test_observed_time_does_not_count_against_the_timeout_of_a_paced_run(runtime, cluster, clock):
    pod = make_pod(cluster, clock)
    observation = JobObservation("j7", 1)
    observation.request(True, 1.0)  # observed from the start, on the observation's own clock
    observed = {"seconds": 0.0}
    observation.observed_seconds = lambda: observed["seconds"]
    clock.hooks.append(lambda now: observed.__setitem__("seconds", min(now, 20.0)))  # 20 s of it observed
    Kubelet(cluster, clock, pod, ends_at=24.0)
    assert pod.run({}, RecordingReport(), timeout_s=5.0, observation=observation, paced=True) == RESULT["result"], "24 s are 5 s and 20 s observed"
    clock.hooks.clear()
    clock.now = 0.0
    cluster.on_create.clear()
    clock.hooks.append(lambda now: observed.__setitem__("seconds", min(now, 20.0)))
    Kubelet(cluster, clock, pod, ends_at=None)
    with pytest.raises(JobFailed, match=r"timed out after 5 s \(and 20 s observed\)"):
        pod.run({}, RecordingReport(), timeout_s=5.0, observation=observation, paced=True)


def test_a_run_that_is_not_paced_keeps_its_timeout_while_observed(runtime, cluster, clock):
    pod = make_pod(cluster, clock)
    observation = JobObservation("j7", 1)
    observation.observed_seconds = lambda: 100.0
    Kubelet(cluster, clock, pod, ends_at=None)
    with pytest.raises(JobFailed, match="timed out after 5 s$"):
        pod.run({}, RecordingReport(), timeout_s=5.0, observation=observation, paced=False)


def test_the_wait_for_the_start_does_not_count_against_the_jobs_timeout(runtime, cluster, clock):
    pod = make_pod(cluster, clock)
    observation = JobObservation("j7", 1)
    clock.hooks.append(lambda now: observation.start() if now >= 20.0 and not observation.started else None)  # the operator, 20 s in
    Kubelet(cluster, clock, pod, ends_at=23.0)
    assert pod.run({}, RecordingReport(), timeout_s=5.0, observation=observation, start_timeout_s=60.0) == RESULT["result"], "20 s of waiting are four times the job's timeout"


def test_a_run_nobody_starts_is_ended_by_the_subsystem_at_the_latest(runtime, cluster, clock, monkeypatch):
    monkeypatch.setattr(run_pod, "_START_MARGIN_S", 0.0)
    pod = make_pod(cluster, clock)
    Kubelet(cluster, clock, pod, ends_at=None)
    with pytest.raises(JobFailed, match="nobody started the run within 3 s") as failure:
        pod.run({}, RecordingReport(), timeout_s=600.0, observation=JobObservation("j7", 1), start_timeout_s=3.0)
    assert not failure.value.retryable and 3.0 < clock.now <= 3.5 and cluster.names(Kind.POD) == []


def test_after_the_start_the_jobs_timeout_counts(runtime, cluster, clock):
    pod = make_pod(cluster, clock)
    observation = JobObservation("j7", 1)
    clock.hooks.append(lambda now: observation.start() if now >= 10.0 and not observation.started else None)
    Kubelet(cluster, clock, pod, ends_at=None)
    with pytest.raises(JobFailed, match="timed out after 5 s"):
        pod.run({}, RecordingReport(), timeout_s=5.0, observation=observation, start_timeout_s=60.0)
    assert 15.0 < clock.now <= 15.5, "the Start at 10 s, then the job's 5 s"


def test_a_cancel_ends_the_run_and_leaves_no_pod_service_or_folder(runtime, cluster, clock):
    pod = make_pod(cluster, clock)
    cancel = threading.Event()
    clock.hooks.append(lambda now: cancel.set() if now >= 2.0 else None)
    Kubelet(cluster, clock, pod, ends_at=None)
    with pytest.raises(JobFailed, match="cancelled") as failure:
        pod.run({}, RecordingReport(), timeout_s=600.0, cancel=cancel, published_ports={"0": ("os-mavproxy", 12200)})
    assert not failure.value.retryable and 2.0 <= clock.now < 3.0
    assert cluster.names(Kind.POD) == [] and cluster.names(Kind.SERVICE) == [] and not os.path.exists(SCOPE.folder)


def test_a_run_without_a_place_in_the_cluster_cannot_start(runtime, clock):
    pod = RunPod(SCOPE, kinematic_services(), networks={"maritime_net": None})
    with pytest.raises(JobFailed, match="has no place in the cluster") as failure:
        pod.run({}, RecordingReport(), timeout_s=60.0)
    assert not failure.value.retryable


# The observation through the job folder


def test_requests_reach_the_runners_job_folder_whole_and_the_latest_wins(runtime, cluster, clock):
    pod = make_pod(cluster, clock)
    os.makedirs(pod.job_folder)
    observation = JobObservation("j7", 1, min_interval_s=0.0)
    stop = threading.Event()
    writer = threading.Thread(target=pod.copy_observation_requests, args=(observation, stop), daemon=True)
    writer.start()
    try:
        runner = ContainerObservation(pod.job_folder, out=io.StringIO(), clock=lambda: 0.0)  # the runner's view of its job folder
        assert not os.path.exists(f"{pod.job_folder}/{OBSERVE_DOCUMENT}"), "nothing is written while nobody observes"
        observation.request(True, 25.0)
        _wait_until(lambda: os.path.exists(f"{pod.job_folder}/{OBSERVE_DOCUMENT}"))
        assert runner.control() == ObservationControl(active=True, speed=25.0, revision=1)
        observation.request(True, 50.0)
        observation.request(False, 50.0)
        _wait_until(lambda: getattr(_request_in(pod.job_folder), "revision", 0) == 3)
        assert not _request_in(pod.job_folder).active
        assert sorted(os.listdir(pod.job_folder)) == [OBSERVE_DOCUMENT], "no temporary file is left"
    finally:
        stop.set()
        writer.join(timeout=5)
    assert not writer.is_alive()


def test_a_failed_write_is_tried_again(runtime, cluster, clock, monkeypatch):
    pod = make_pod(cluster, clock)
    os.makedirs(pod.job_folder)
    attempts = []
    write = run_pod._write_file

    def flaky(path, text):
        attempts.append(path)
        return False if len(attempts) == 1 else write(path, text)

    monkeypatch.setattr(run_pod, "_write_file", flaky)
    monkeypatch.setattr(run_pod, "_CONTROL_WAIT_S", 0.01)
    observation = JobObservation("j7", 1)
    observation.request(True, 10.0)
    stop = threading.Event()
    writer = threading.Thread(target=pod.copy_observation_requests, args=(observation, stop), daemon=True)
    writer.start()
    try:
        _wait_until(lambda: os.path.exists(f"{pod.job_folder}/{OBSERVE_DOCUMENT}"))
    finally:
        stop.set()
        writer.join(timeout=5)
    assert len(attempts) == 2


def test_an_observed_run_hands_its_frames_to_the_observation(runtime, cluster, clock):
    pod = make_pod(cluster, clock)
    observation = JobObservation("j7", 1, min_interval_s=0.0)
    observation.request(True, 10.0)
    Kubelet(cluster, clock, pod, lines=[format_frame_line(json.dumps({"timestamp": index})) for index in range(3)] + ["done"], ends_at=2.0)
    report = RecordingReport()
    pod.run({}, report, timeout_s=60.0, observation=observation)
    assert observation.take_batch() == (1, [{"timestamp": 0}, {"timestamp": 1}, {"timestamp": 2}])
    assert report.lines == [(f"{SCOPE.name}/runner", "done", LogStream.STDOUT)], "frames never as log lines"


def _request_in(folder):
    try:
        with open(f"{folder}/{OBSERVE_DOCUMENT}", encoding="utf-8") as file:
            return ObservationControl.from_document(file.read())
    except (OSError, ValueError):
        return None


def _wait_until(condition, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


# The runner's log


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
    assert report.statuses == [("running", 0.5, None)]
    assert report.lines == [("runner-1", "plain output", LogStream.STDOUT), ("runner-1", format_frame_line('{"timestamp":5}'), LogStream.STDERR)]
    assert observation.take_batch() == (1, [{"timestamp": 4}])
    forward_runner_line(format_frame_line('{"timestamp":6}'), LogStream.STDOUT, "runner-1", report, None)  # no observation: the frame is dropped, not logged
    assert len(report.lines) == 2


def test_a_log_lines_time_is_read_to_the_nanosecond():
    assert split_timestamp("2026-11-17T10:00:01.000000002Z hello world") == (1794909601000000002, "hello world")
    assert split_timestamp("2026-11-17T10:00:01.5Z x") == (1794909601500000000, "x")
    assert split_timestamp("2026-11-17T11:00:01+01:00 x") == (1794909601000000000, "x")
    assert split_timestamp("no time here") == (None, "no time here")


def placed_runner_pod(cluster: FakeCluster, state: str = "running") -> None:
    cluster.add(Kind.POD, {"metadata": {"name": "run"}, "spec": {"containers": [{"name": RUNNER_SERVICE}]}})
    cluster.set_container_state("run", RUNNER_SERVICE, state)


def follow(cluster: FakeCluster, now_s: float = 1794909700.0) -> tuple:  # 2026-11-17T10:01:40Z
    report = RecordingReport()
    log = RunnerLog(cluster.api(), "run", RUNNER_SERVICE, report, source="run/runner", wall_clock=lambda: now_s)
    log.start()
    return log, report


def test_the_log_is_followed_again_after_its_connection_broke_and_no_line_comes_twice(runtime):
    cluster = FakeCluster()
    placed_runner_pod(cluster)
    stamp = "2026-11-17T10:00:{:02d}.000000000Z {}".format
    cluster.add_log("run", RUNNER_SERVICE, [stamp(1, "one"), stamp(2, "two")], ConnectionResetError("the API server went away"))
    cluster.add_log("run", RUNNER_SERVICE, [stamp(1, "one"), stamp(2, "two"), stamp(3, "three")])
    cluster.on_create.clear()
    log, report = follow(cluster)
    _wait_until(lambda: len(cluster.log_calls) >= 2)
    cluster.set_container_state("run", RUNNER_SERVICE, "terminated", exitCode=0)
    log.join(5)
    assert not log.thread.is_alive()
    assert [text for _, text, _ in report.lines] == ["one", "two", "three"]
    assert cluster.log_calls[1]["since_seconds"] == 98 + 5, "from a little before the last line read (10:00:02, 98 s ago)"


def test_the_log_is_not_asked_for_before_the_runner_started_and_not_after_the_pod_is_gone(runtime):
    cluster = FakeCluster()
    placed_runner_pod(cluster, state="waiting")
    log, report = follow(cluster)
    time.sleep(0.1)
    assert cluster.log_calls == [], "the API refuses the log of a container that waits"
    cluster.objects.clear()
    log.join(5)
    assert not log.thread.is_alive() and cluster.log_calls == []


def test_the_log_of_a_runner_that_ended_is_read_once_whole(runtime):
    cluster = FakeCluster()
    placed_runner_pod(cluster, state="terminated")
    cluster.add_log("run", RUNNER_SERVICE, ["2026-11-17T10:00:01Z last words"])
    log, report = follow(cluster)
    log.join(5)
    assert [text for _, text, _ in report.lines] == ["last words"] and len(cluster.log_calls) == 1


def test_the_selector_of_leftover_runs_names_the_worker_node_and_a_run():
    assert run_pod_selector("n1") == "app.kubernetes.io/component=simulation-run,scenegems.worker-node=n1"
