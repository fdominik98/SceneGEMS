"""The worker node daemon as the chart deploys it, end to end: it connects to a scripted control node over plain HTTP, with no pairing, and runs real jobs.

Everything the worker node talks to is real except the control node's control logic: the plain NanoMQ cluster
broker, the daemon's Deployment as the chart renders it for a cluster of worker nodes only (installed with helm into
a namespace of the test's k3d cluster from a release bundle, local_cluster.py), the pools it starts through the
cluster API (the scene generation pool, the simulation pool and its runs' pods), and the control node's artifact
routes on a real artifact store. The test plays the control node on the control WebSocket, in the test process: the
daemon dials http://control-node-api:8443 as always, and the namespace's service of that name leads to the test
process on this PC (host.k3d.internal, the address k3d gives the Docker host inside the cluster).

Images: every image of the release built under SCENEGEMS_TEST_IMAGE_TAG (latest by default), as the end-to-end test
needs them (tests/scenegems_tool/cluster/worker_node/k3d_cluster.py).
"""

import hashlib
import json
import threading
import time
import uuid
from typing import Iterator

import pytest

from scenegems_tool.cluster.protocol.artifacts import ArtifactContent, ArtifactKind, ArtifactRef, encode_document
from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobType
from scenegems_tool.cluster.protocol.messages import Heartbeat, Hello, JobResult, JobStatus, LeaseAccept, LeaseReject, LeaseRelease, LeaseRenew, LogLines
from scenegems_tool.cluster.worker_node.instance_scope import WORKER_NODE_LABEL, InstanceScope
from scenegems_tool.cluster.worker_node.launchers.per_job.run_pod import RUN_COMPONENT, RUN_COMPONENT_LABEL, RUNNER_SERVICE
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.persistence.artifacts.file_artifact_store import FileArtifactStore
from scenegems_tool.persistence.artifacts.recorded_artifacts import RecordedArtifacts
from scenegems_tool.persistence.clock import utc_now
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import run_kinematic_replay
from tests.scenegems_tool.assurance.local_cluster import LocalCluster, bundle_release, deploy
from tests.scenegems_tool.assurance.local_cluster import worker_node as worker_node_member
from tests.scenegems_tool.cluster.worker_node.daemon.conftest import make_job, make_offer
from tests.scenegems_tool.cluster.worker_node.daemon.fake_control_node import FakeControlNode
from tests.scenegems_tool.cluster.worker_node.jobs.test_pool_jobs_on_kubernetes import _scene_generation_payload
from tests.scenegems_tool.persistence.artifacts.fake_artifact_records import InMemoryArtifactRecords

pytestmark = [pytest.mark.kubernetes, pytest.mark.slow]

JOB_TIMEOUT_S = 300.0
CONNECT_TIMEOUT_S = 300.0  # the daemon's pod starts, then dials with backoff
BACKGROUND = (Heartbeat, JobStatus, LogLines, LeaseRenew)
WORKER_NODE_PARAMETERS = {
    "SCENEGEMS_WORKER_NODE_SLOTS": "simulation:2,scene_generation:1",
    "SCENEGEMS_WORKER_NODE_COMPONENTS": "asv_system/replay,control_layer/none,simulation_layer/kinematic,scene_generation",
    "SCENEGEMS_WORKER_NODE_LABELS": "test=kubernetes",
}
STATE_DIR = "/var/lib/scenegems-worker-node"


def _docker_host(k3d_cluster) -> str:
    """The address pods reach this PC at: the one k3d writes into CoreDNS for host.k3d.internal."""
    hosts = k3d_cluster.kubectl_run("get", "configmap", "coredns", "-n", "kube-system", "-o", "jsonpath={.data.NodeHosts}").stdout
    for line in hosts.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == "host.k3d.internal":
            return parts[0]
    raise AssertionError(f"k3d wrote no host.k3d.internal into CoreDNS: {hosts!r}")


@pytest.fixture(scope="module")
def release_bundle(k3d_cluster, tmp_path_factory):
    return bundle_release(tmp_path_factory.mktemp("daemon-release"), k3d_cluster.image_tag)


@pytest.fixture(scope="module")
def control_node(tmp_path_factory):
    """The scripted control node in the test process, listening on every address of this PC, with a real artifact store."""
    artifacts = RecordedArtifacts(FileArtifactStore(tmp_path_factory.mktemp("artifacts")), InMemoryArtifactRecords(utc_now))
    control_node = FakeControlNode(control_node_id=f"m{uuid.uuid4().hex[:6]}", heartbeat_interval_s=1.0, lease_timeout_s=30.0, artifacts=artifacts).start(bind="0.0.0.0")
    try:
        yield control_node
    finally:
        control_node.stop()


def _deploy_worker_node(k3d_cluster, release_bundle, control_node) -> Iterator[LocalCluster]:
    """A worker node installed by the chart into a namespace of its own, with the cluster broker and the service control-node-api leading to the test process."""
    name = f"daemon-{uuid.uuid4().hex[:6]}"
    namespace = f"scenegems-{name}"
    k3d_cluster.kubectl_run("create", "namespace", namespace)
    k3d_cluster.add_broker(namespace)
    k3d_cluster.apply(
        [
            {"apiVersion": "v1", "kind": "Service", "metadata": {"name": "control-node-api"}, "spec": {"ports": [{"name": "worker-node-api", "port": 8443, "targetPort": control_node.port}]}},
            {
                "apiVersion": "discovery.k8s.io/v1",
                "kind": "EndpointSlice",
                "metadata": {"name": "control-node-api-test-process", "labels": {"kubernetes.io/service-name": "control-node-api"}},
                "addressType": "IPv4",
                "ports": [{"name": "worker-node-api", "port": control_node.port, "protocol": "TCP"}],
                "endpoints": [{"addresses": [_docker_host(k3d_cluster)]}],
            },
        ],
        namespace,
    )
    release_dir, release = release_bundle
    local = deploy(k3d_cluster, release_dir, release, [worker_node_member(name, k3d_cluster.node, **WORKER_NODE_PARAMETERS)], cluster_id=control_node.control_node_id, namespace=namespace)
    try:
        yield local
    finally:
        local.uninstall()


@pytest.fixture(scope="module")
def worker_node(k3d_cluster, release_bundle, control_node):
    yield from _deploy_worker_node(k3d_cluster, release_bundle, control_node)


@pytest.fixture
def artifact_worker_node(k3d_cluster, release_bundle, control_node):
    """Another worker node of the same control node, for the artifact round trip."""
    yield from _deploy_worker_node(k3d_cluster, release_bundle, control_node)


def _name(local: LocalCluster) -> str:
    (member,) = local.members
    return member.name


def _daemon(local: LocalCluster) -> str:
    return f"deployment/worker-node-{_name(local)}"


def _running_runners(local: LocalCluster) -> int:
    """The run pods of the worker node whose runner container runs."""
    selector = f"{WORKER_NODE_LABEL}={_name(local)},{RUN_COMPONENT_LABEL}={RUN_COMPONENT}"
    pods = json.loads(local.kubectl("get", "pods", "-l", selector, "-o", "json", check=False) or '{"items": []}')["items"]
    running = 0
    for pod in pods:
        for status in pod.get("status", {}).get("containerStatuses") or []:
            if status["name"] == RUNNER_SERVICE and "running" in (status.get("state") or {}):
                running += 1
    return running


class RunnerWatch:
    """Samples how many kinematic runners of the worker node run at once."""

    def __init__(self, local: LocalCluster):
        self.most = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, args=(local,), daemon=True)

    def _watch(self, local: LocalCluster) -> None:
        while not self._stop.is_set():
            self.most = max(self.most, _running_runners(local))
            time.sleep(0.5)

    def __enter__(self) -> "RunnerWatch":
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._stop.set()
        self._thread.join(timeout=10)


def _kinematic_job_id(index: int) -> str:
    """Ids that differ from their first character on: a run's pod is named by the start of its job id."""
    return f"{index}-kinematic"


def _answers(connection, count: int) -> dict:
    answers = {}
    while len(answers) < count:
        frame = connection.expect((LeaseAccept, LeaseReject), skip=BACKGROUND)
        answers[frame.lease_id] = frame
    return answers


def _results(connection, count: int, payload: dict) -> dict:
    """Results until count arrived; the rejected kinematic job is offered again once a kinematic slot is free."""
    results = {}
    offered_again = False
    while len(results) < count:
        frame = connection.expect((JobResult, LeaseAccept), timeout_s=JOB_TIMEOUT_S, skip=BACKGROUND)
        if isinstance(frame, JobResult):
            results[frame.lease_id] = frame
        if not offered_again and any(lease.startswith("kinematic") for lease in results):
            connection.send(make_offer("kinematic-2", make_job(_kinematic_job_id(2), payload=payload)))
            offered_again = True
    return results


def test_the_worker_node_as_the_chart_deploys_it_connects_without_pairing_and_runs_jobs_within_its_slots(control_node, worker_node, head_on_trajectories):
    try:
        connection = control_node.wait_for_connection(timeout_s=CONNECT_TIMEOUT_S)
    except AssertionError:
        pytest.fail(f"The worker node never connected:\n{worker_node.logs(_daemon(worker_node))}")
    hello = connection.expect(Hello)
    control_node_id, worker_node_id = control_node.control_node_id, hello.worker_node_id
    assert worker_node_id == _name(worker_node) and hello.worker_node_name == worker_node_id and hello.labels == {"test": "kubernetes"}  # the worker node id is its name
    assert hello.software_revision == worker_node.release["revision"] and hello.resources.cpus >= 1 and hello.resources.memory_mb > 0
    assert hello.machine == "operator-pc"
    assert {offer.job_type: offer.slots for offer in hello.slots} == {JobType.SIMULATION: 2, JobType.SCENE_GENERATION: 1}

    # Nothing was paired: the worker node's state folder holds no pairing state.
    assert "pairing.json" not in worker_node.kubectl("exec", _daemon(worker_node), "--", "ls", STATE_DIR).split()

    payload = {"runner": "kinematic", "trajectories": head_on_trajectories.to_dict(), "include_trajectories": False}
    with RunnerWatch(worker_node) as runners:
        try:
            for index in range(3):
                connection.send(make_offer(f"kinematic-{index}", make_job(_kinematic_job_id(index), payload=payload)))
            connection.send(make_offer("scene-0", make_job("scene-0", job_type=JobType.SCENE_GENERATION, payload=_scene_generation_payload())))
            answers = _answers(connection, 4)
            assert {lease for lease, frame in answers.items() if isinstance(frame, LeaseAccept)} == {"kinematic-0", "kinematic-1", "scene-0"}
            assert "2 simulation slots are in use" in answers["kinematic-2"].reason
            results = _results(connection, 4, payload)
        except AssertionError as error:
            pytest.fail(f"{error}\nWorker node log:\n{worker_node.logs(_daemon(worker_node))}")

    expected_digest = run_kinematic_replay(head_on_trajectories).state_digest()
    for lease in ("kinematic-0", "kinematic-1", "kinematic-2"):
        assert results[lease].outcome == JobOutcome.SUCCEEDED, results[lease].error
        assert results[lease].result["state_digest"] == expected_digest
        assert results[lease].idempotency_key == f"{_kinematic_job_id(int(lease[-1]))}/key"
    scene = results["scene-0"]
    assert scene.outcome == JobOutcome.SUCCEEDED, scene.error
    assert scene.result["request_id"] == "scene-0-1" and isinstance(scene.result["valid"], bool)
    assert 1 <= runners.most <= 2
    assert max(sum(heartbeat.slots_in_use.values()) for heartbeat in connection.received(Heartbeat)) <= 3

    # The scene generation pool dials the plain broker by its service name with no account and mounts no certificate.
    pool = InstanceScope.pooled(control_node_id, worker_node_id, Subsystem.SCENE_GENERATION.value).name
    spec = json.loads(worker_node.kubectl("get", "deployment", pool, "-o", "json"))["spec"]["template"]["spec"]
    (container,) = spec["containers"]
    assert not [mount for mount in container.get("volumeMounts", []) if "trust" in mount["mountPath"]]
    environment = {variable["name"]: variable.get("value", "") for variable in container["env"]}
    assert environment["MQTT_TLS"] == "0" and environment["MQTT_USER"] == "" and "cluster-broker" in environment.values()

    # Stopping the worker node (its Deployment scaled to none) removes its pools and leaves nothing of its instances behind.
    worker_node.kubectl("scale", _daemon(worker_node), "--replicas=0")
    selector = f"{WORKER_NODE_LABEL}={worker_node_id}"

    def instances() -> list:
        return worker_node.kubectl("get", "deployments,pods,services", "-l", selector, "-o", "name").split()

    deadline = time.monotonic() + 180
    while instances() and time.monotonic() < deadline:
        time.sleep(2)
    assert instances() == []
    assert worker_node.kubectl("get", "deployment", f"worker-node-{worker_node_id}", "-o", "name").strip(), "only the stopped daemon's own Deployment"
    assert not connection.received(LeaseRelease)  # nothing was running at the stop


def test_a_job_s_inputs_and_results_travel_as_artifacts(control_node, artifact_worker_node, head_on_trajectories):
    """A kinematic job whose trajectories are a reference into a stored trajectory generation result, and
    whose result comes back with its trajectories as a reference to an artifact the worker node uploaded."""
    try:
        connection = control_node.wait_for_connection(timeout_s=CONNECT_TIMEOUT_S)
    except AssertionError:
        pytest.fail(f"The worker node never connected:\n{artifact_worker_node.logs(_daemon(artifact_worker_node))}")
    connection.expect(Hello)
    trajectory_data = {"algorithm_desc": "straight", "trajectories": head_on_trajectories.to_dict()}
    document = encode_document(trajectory_data, ArtifactContent.JSON)
    stored = control_node.artifacts.put(document, ArtifactKind.TRAJECTORY_DATA.value, "application/json")
    reference = ArtifactRef(sha256=stored.stored.sha256, size_bytes=len(document), kind=ArtifactKind.TRAJECTORY_DATA, pointer="/trajectories")
    job = make_job("artifact-job", payload={"runner": "kinematic", "trajectories": reference.model_dump(mode="json"), "include_trajectories": True})
    connection.send(make_offer("artifact-0", job))
    try:
        connection.expect(LeaseAccept, skip=BACKGROUND)
        result = connection.expect(JobResult, timeout_s=JOB_TIMEOUT_S, skip=BACKGROUND)
    except AssertionError as error:
        pytest.fail(f"{error}\nWorker node log:\n{artifact_worker_node.logs(_daemon(artifact_worker_node))}")
    assert result.outcome == JobOutcome.SUCCEEDED, f"{result.error}\nWorker node log:\n{artifact_worker_node.logs(_daemon(artifact_worker_node))}"
    expected = run_kinematic_replay(head_on_trajectories)
    assert result.result["state_digest"] == expected.state_digest()

    states = ArtifactRef.model_validate(result.result["trajectories"])
    assert states.kind == ArtifactKind.TRAJECTORIES
    content = control_node.artifacts.store.read(states.sha256)
    assert hashlib.sha256(content).hexdigest() == states.sha256 and len(content) == states.size_bytes
    assert json.loads(content) == json.loads(json.dumps(expected.to_trajectories().to_dict()))
    assert (states.sha256, "job", job.job_id, "result:trajectories") in control_node.artifacts.records.references
    # The worker node keeps both artifacts in the cache in its state folder
    cached = artifact_worker_node.kubectl("exec", _daemon(artifact_worker_node), "--", "ls", f"{STATE_DIR}/artifacts").split()
    assert {reference.sha256, states.sha256} <= set(cached)


# Every job type's worker node side in the worker node image: its payload check and what run() does before
# it starts a pod. The image carries only the daemon's requirements, so a missing
# library shows up here and not in the middle of a campaign.
WORKER_NODE_SIDE_CHECK = """
import json
import math
import sys
from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.cluster.worker_node.jobs import job_types, simulation_job
from scenegems_tool.cluster.worker_node.jobs.simulation_runners import ardupilot_runner
from scenegems_tool.cluster.worker_node.jobs.job_payload import parse_payload
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext
from scenegems_tool.cluster.protocol.jobs import JobSpec, JobType
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
def vessel(vessel_id, own):
    return ConcreteActor.from_dict({"id": vessel_id, "type": "OSPassengerShip" if own else "PassengerShip", "length": 30.0, "breadth": 10.0, "safety_radius": 120.0,
        "is_vessel": True, "_is_os": own, "_max_speed": 20.57778, "_max_angular_speed": 0.05, "_max_acceleration": 0.4})

scene = ConcreteScene({vessel(0, True): ActorState(0.0, 0.0, 8.0, 0.0), vessel(1, False): ActorState(3000.0, 0.0, 8.0, math.pi)})
trajectories = TrajectoryBuilder.default_trajectory_from_scene(scene, 1, 60).to_dict()
geofence = {"latitude": 57.7, "longitude": 11.9, "radius_meters": 2000.0}
payloads = [
    ("scene_generation", JobType.SCENE_GENERATION, json.load(sys.stdin)),  # the test data folders are not in the image
    ("trajectory_generation", JobType.TRAJECTORY_GENERATION, {"scenario_content": "{}", "colregs_constraints_content": "", "params": {"maxIterations": 100}}),
    ("simulation kinematic", JobType.SIMULATION, {"runner": "kinematic", "mode": "usv_navigation", "trajectories": trajectories}),
    ("simulation ardupilot_sim", JobType.SIMULATION, {"runner": "ardupilot", "simulation_layer": "ardupilot_sim", "trajectories": trajectories, "geofence": geofence}),
    ("simulation gazebo", JobType.SIMULATION, {"runner": "ardupilot", "simulation_layer": "gazebo", "trajectories": trajectories, "geofence": geofence}),
    ("monitoring.post_hoc", JobType.MONITORING_POST_HOC, {"trajectories": trajectories}),
]
for _, job_type, payload in payloads:
    parse_payload(job_types.payload_model(job_type), JobSpec(job_id="check", job_type=job_type, payload=payload, attempt=1, idempotency_key="check"))
worker_node = WorkerNodeContext("m1", "n1", MQttConnectionInfo("", "", "broker", "broker", 1883, False, False), Geofence(57.7, 11.9, 2000.0), slots={JobType.SIMULATION: 1})
job = JobSpec(job_id="check", job_type=JobType.SIMULATION, payload=payloads[3][2], attempt=1, idempotency_key="check")
stack = ardupilot_runner.build_job_stack(job, worker_node,parse_payload(simulation_job.SimulationPayload, job).root)
assert "runner" in stack.compose["services"] and len(stack.compose["services"]) >= 3, stack.compose["services"].keys()
print("worker node side ok:", ", ".join(sorted(name for name, _, _ in payloads)))
"""


def test_every_job_type_s_worker_node_side_runs_in_the_worker_node_image(k3d_cluster):
    """In a pod of the worker node image, as the daemon runs in one."""
    name = f"worker-node-side-{uuid.uuid4().hex[:6]}"
    arguments = ["run", name, "-n", k3d_cluster.namespace, "--image", k3d_cluster.images()["WORKER_NODE"], "--image-pull-policy=IfNotPresent", "--restart=Never"]
    arguments += ["-i", "--rm", "--quiet", "--command", "--", "python", "-c", WORKER_NODE_SIDE_CHECK]
    result = k3d_cluster.kubectl_run(*arguments, input_text=json.dumps(_scene_generation_payload()), check=False, timeout_s=300)
    assert result.returncode == 0, result.stderr[-4000:] + result.stdout[-4000:]
    assert "worker node side ok: monitoring.post_hoc, scene_generation, simulation ardupilot_sim, simulation gazebo, simulation kinematic, trajectory_generation" in result.stdout
