"""The node container end to end: it connects to a scripted master over plain HTTP, with no pairing, and runs real jobs.

Everything the node talks to is real except the master's control logic: the plain NanoMQ
cluster broker the master's compose file runs, the node image started through
deploy/node/docker-compose.yml, the subsystem containers it starts (kinematic runners, the
scene generation pool), and the master's artifact routes on a real artifact store. The test
plays the master on the control WebSocket.

Images: scenegems-node:<SCENEGEMS_TEST_NODE_IMAGE_TAG>, the subsystem images with
SCENEGEMS_TEST_IMAGE_TAG (both default latest), and SCENEGEMS_BROKER_IMAGE. Containers reach
the test process and the broker through host.docker.internal, which Docker Desktop resolves.
"""

import hashlib
import json
import os
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path

import pytest

from scenegems_tool.cluster.node.instance_scope import InstanceScope
from scenegems_tool.cluster.node.subsystem import IMAGE_ENVIRONMENT_VARIABLES, Subsystem, subsystem_image
from scenegems_tool.cluster.protocol.artifacts import ArtifactContent, ArtifactKind, ArtifactRef, encode_document
from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobType
from scenegems_tool.cluster.protocol.messages import Heartbeat, Hello, JobResult, JobStatus, LeaseAccept, LeaseReject, LeaseRelease, LeaseRenew, LogLines
from scenegems_tool.persistence.artifacts.file_artifact_store import FileArtifactStore
from scenegems_tool.persistence.artifacts.recorded_artifacts import RecordedArtifacts
from scenegems_tool.persistence.clock import utc_now
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import run_kinematic_replay
from tests.scenegems_tool.cluster.node.daemon.conftest import make_job, make_offer
from tests.scenegems_tool.cluster.node.daemon.fake_master import FakeMaster
from tests.scenegems_tool.cluster.node.jobs.test_jobs_in_containers import _scene_generation_payload
from tests.scenegems_tool.persistence.artifacts.fake_artifact_records import InMemoryArtifactRecords
from utils.file_system_utils import REPO_ROOT

pytestmark = [pytest.mark.docker, pytest.mark.slow]

IMAGE_TAG = os.environ.get("SCENEGEMS_TEST_IMAGE_TAG", "latest")
NODE_IMAGE_TAG = os.environ.get("SCENEGEMS_TEST_NODE_IMAGE_TAG", "latest")
BROKER_IMAGE = os.environ.get("SCENEGEMS_BROKER_IMAGE", "scenegems-mqtt-broker:latest")
COMPOSE_FILE = Path(REPO_ROOT) / "deploy" / "node" / "docker-compose.yml"
HOST = "host.docker.internal"
JOB_TIMEOUT_S = 300.0
BACKGROUND = (Heartbeat, JobStatus, LogLines, LeaseRenew)


def _docker(*arguments: str, check: bool = True, timeout: float = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *arguments], capture_output=True, text=True, check=check, timeout=timeout)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _image(subsystem: Subsystem) -> str:
    return subsystem_image(subsystem).rsplit(":", 1)[0] + f":{IMAGE_TAG}"


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    """The plain cluster broker and the fake master: what a node sees of its master."""
    if _docker("info", check=False).returncode != 0:
        pytest.skip("Docker engine is not reachable")
    for image in (f"scenegems-node:{NODE_IMAGE_TAG}", BROKER_IMAGE, _image(Subsystem.SCENARIO_EXECUTION), _image(Subsystem.SCENE_GENERATION)):
        if _docker("image", "inspect", image, check=False).returncode != 0:
            pytest.fail(f"Image {image} is missing; build it with ./build.sh --node --backend or set the test image tags")

    broker_port = _free_port()
    broker = f"scenegems-test-cluster-broker-{uuid.uuid4().hex[:8]}"
    _docker("run", "-d", "--name", broker, "--add-host", f"{HOST}:host-gateway", "--tmpfs", "/data/broker", "-p", f"{broker_port}:1883", BROKER_IMAGE)
    artifacts = RecordedArtifacts(FileArtifactStore(tmp_path_factory.mktemp("artifacts")), InMemoryArtifactRecords(utc_now))
    master = FakeMaster(master_id=f"m{uuid.uuid4().hex[:6]}", host=HOST, heartbeat_interval_s=1.0, lease_timeout_s=30.0, artifacts=artifacts).start(bind="0.0.0.0")
    master.broker_port = broker_port
    try:
        yield master
    finally:
        master.stop()
        _docker("rm", "-f", broker, check=False)


class NodeContainer:
    """deploy/node/docker-compose.yml with a test env file: up, logs, exec and down with volumes."""

    def __init__(self, env_file: Path, name: str):
        self.env_file = env_file
        self.name = name

    def compose(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["docker", "compose", "-f", str(COMPOSE_FILE), "--env-file", str(self.env_file), *arguments], capture_output=True, text=True, check=check, timeout=300)

    def logs(self) -> str:
        return _docker("logs", self.name, check=False).stdout[-6000:]


def _node_container(cluster, tmp_path_factory):
    node_name = f"docker-{uuid.uuid4().hex[:6]}"
    env_file = tmp_path_factory.mktemp("node") / "node.env"
    values = {
        "SCENEGEMS_MASTER_URL": cluster.url,
        "SCENEGEMS_MASTER_ID": cluster.master_id,
        "SCENEGEMS_BROKER_PORT": str(cluster.broker_port),
        "SCENEGEMS_NODE_NAME": node_name,
        "SCENEGEMS_NODE_SLOTS": "simulation:2,scene_generation:1",
        "SCENEGEMS_NODE_COMPONENTS": "asv_software/replay,control_layer/none,simulation_layer/kinematic,scene_generation",
        "SCENEGEMS_NODE_LABELS": "test=docker",
        "SCENEGEMS_IMAGE_TAG": NODE_IMAGE_TAG,  # the node image; the subsystem images come by their variables
        "SCENEGEMS_SOFTWARE_REVISION": "docker-test",
        **{variable: _image(subsystem) for subsystem, variable in IMAGE_ENVIRONMENT_VARIABLES.items()},
    }
    env_file.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
    container = NodeContainer(env_file, f"scenegems-node-{cluster.master_id}-{node_name}")
    container.compose("up", "-d")
    try:
        yield container
    finally:
        container.compose("down", "--volumes", "--timeout", "60", check=False)


@pytest.fixture(scope="module")
def node(cluster, tmp_path_factory):
    yield from _node_container(cluster, tmp_path_factory)


@pytest.fixture
def artifact_node(cluster, tmp_path_factory):
    """Another node of the same master, for the artifact round trip."""
    yield from _node_container(cluster, tmp_path_factory)


def _running_runners(master_id: str, node_id: str) -> int:
    prefix = InstanceScope.per_job(master_id, node_id, "x").docker_name.rsplit("job-", 1)[0] + "job-"
    names = _docker("ps", "--format", "{{.Names}}", check=False).stdout.split()
    return sum(1 for name in names if name.startswith(prefix) and name.endswith("-runner"))


class RunnerWatch:
    """Samples how many kinematic runner containers of the node run at once."""

    def __init__(self, master_id: str, node_id: str):
        self.most = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, args=(master_id, node_id), daemon=True)

    def _watch(self, master_id: str, node_id: str) -> None:
        while not self._stop.is_set():
            self.most = max(self.most, _running_runners(master_id, node_id))
            time.sleep(0.5)

    def __enter__(self) -> "RunnerWatch":
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._stop.set()
        self._thread.join(timeout=5)


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
            connection.send(make_offer("kinematic-2", make_job("kinematic-2", payload=payload)))
            offered_again = True
    return results


def test_the_node_container_connects_without_pairing_and_runs_jobs_within_its_slots(cluster, node, head_on_trajectories):
    try:
        connection = cluster.wait_for_connection(timeout_s=120)
    except AssertionError:
        pytest.fail(f"The node never connected:\n{node.logs()}")
    hello = connection.expect(Hello)
    master_id, node_id = cluster.master_id, hello.node_id
    assert hello.node_name == node.name.rsplit(f"{master_id}-", 1)[1] == node_id and hello.labels == {"test": "docker"}  # the node id is its name
    assert hello.software_revision == "docker-test" and hello.resources.cpus >= 1 and hello.resources.memory_mb > 0
    assert {offer.job_type: offer.slots for offer in hello.slots} == {JobType.SIMULATION: 2, JobType.SCENE_GENERATION: 1}

    # Nothing was paired: the node's volume holds no pairing state.
    assert "pairing.json" not in _docker("exec", node.name, "ls", "/var/lib/scenegems-node").stdout.split()

    payload = {"runner": "kinematic", "trajectories": head_on_trajectories.to_dict(), "include_trajectories": False}
    with RunnerWatch(master_id, node_id) as runners:
        try:
            for index in range(3):
                connection.send(make_offer(f"kinematic-{index}", make_job(f"kinematic-{index}", payload=payload)))
            connection.send(make_offer("scene-0", make_job("scene-0", job_type=JobType.SCENE_GENERATION, payload=_scene_generation_payload())))
            answers = _answers(connection, 4)
            assert {lease for lease, frame in answers.items() if isinstance(frame, LeaseAccept)} == {"kinematic-0", "kinematic-1", "scene-0"}
            assert "2 simulation slots are in use" in answers["kinematic-2"].reason
            results = _results(connection, 4, payload)
        except AssertionError as error:
            pytest.fail(f"{error}\nNode log:\n{node.logs()}")

    expected_digest = run_kinematic_replay(head_on_trajectories).state_digest()
    for lease in ("kinematic-0", "kinematic-1", "kinematic-2"):
        assert results[lease].outcome == JobOutcome.SUCCEEDED, results[lease].error
        assert results[lease].result["state_digest"] == expected_digest
        assert results[lease].idempotency_key == f"{lease}/key"
    scene = results["scene-0"]
    assert scene.outcome == JobOutcome.SUCCEEDED, scene.error
    assert scene.result["request_id"] == "scene-0-1" and isinstance(scene.result["valid"], bool)
    assert 1 <= runners.most <= 2
    assert max(sum(heartbeat.slots_in_use.values()) for heartbeat in connection.received(Heartbeat)) <= 3

    # The scene generation pool dials the plain broker with no account and mounts no certificate.
    pool = InstanceScope.pooled(master_id, node_id, Subsystem.SCENE_GENERATION.value).docker_name
    mounts = _docker("inspect", "--format", "{{range .Mounts}}{{.Destination}} {{end}}", pool).stdout
    assert "/etc/scenegems/trust" not in mounts
    environment = _docker("inspect", "--format", "{{range .Config.Env}}{{println .}}{{end}}", pool).stdout.split("\n")
    assert "MQTT_TLS=0" in environment and "MQTT_USER=" in environment

    # Stopping the node removes its pool and leaves nothing of its instances behind.
    node.compose("stop", "--timeout", "60")
    remaining = [name for name in _docker("ps", "-a", "--format", "{{.Names}}").stdout.split() if name.startswith(f"scenegems-{master_id}-{node_id}-")]
    assert remaining == []
    assert not connection.received(LeaseRelease)  # nothing was running at the stop


def test_a_job_s_inputs_and_results_travel_as_artifacts(cluster, artifact_node, head_on_trajectories):
    """A kinematic job whose trajectories are a reference into a stored trajectory generation result, and
    whose result comes back with its trajectories as a reference to an artifact the node uploaded."""
    try:
        connection = cluster.wait_for_connection(timeout_s=120)
    except AssertionError:
        pytest.fail(f"The node never connected:\n{artifact_node.logs()}")
    connection.expect(Hello)
    trajectory_data = {"algorithm_desc": "straight", "trajectories": head_on_trajectories.to_dict()}
    document = encode_document(trajectory_data, ArtifactContent.JSON)
    stored = cluster.artifacts.put(document, ArtifactKind.TRAJECTORY_DATA.value, "application/json")
    reference = ArtifactRef(sha256=stored.stored.sha256, size_bytes=len(document), kind=ArtifactKind.TRAJECTORY_DATA, pointer="/trajectories")
    job = make_job("artifact-job", payload={"runner": "kinematic", "trajectories": reference.model_dump(mode="json"), "include_trajectories": True})
    connection.send(make_offer("artifact-0", job))
    try:
        connection.expect(LeaseAccept, skip=BACKGROUND)
        result = connection.expect(JobResult, timeout_s=JOB_TIMEOUT_S, skip=BACKGROUND)
    except AssertionError as error:
        pytest.fail(f"{error}\nNode log:\n{artifact_node.logs()}")
    assert result.outcome == JobOutcome.SUCCEEDED, f"{result.error}\nNode log:\n{artifact_node.logs()}"
    expected = run_kinematic_replay(head_on_trajectories)
    assert result.result["state_digest"] == expected.state_digest()

    states = ArtifactRef.model_validate(result.result["trajectories"])
    assert states.kind == ArtifactKind.TRAJECTORIES
    content = cluster.artifacts.store.read(states.sha256)
    assert hashlib.sha256(content).hexdigest() == states.sha256 and len(content) == states.size_bytes
    assert json.loads(content) == json.loads(json.dumps(expected.to_trajectories().to_dict()))
    assert (states.sha256, "job", job.job_id, "result:trajectories") in cluster.artifacts.records.references
    # The node keeps both artifacts in the cache in its state volume
    cached = _docker("exec", artifact_node.name, "ls", "/var/lib/scenegems-node/artifacts").stdout.split()
    assert {reference.sha256, states.sha256} <= set(cached)


# Every job type's node side in the node image: its payload check and what run() does before
# it starts a container. The image carries only the daemon's requirements, so a missing
# library shows up here and not in the middle of a campaign.
NODE_SIDE_CHECK = """
import json
import math
import sys
from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.cluster.node.jobs import job_types, simulation_job
from scenegems_tool.cluster.node.jobs.simulation_runners import ardupilot_runner
from scenegems_tool.cluster.node.jobs.job_payload import parse_payload
from scenegems_tool.cluster.node.node_context import NodeContext
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
node = NodeContext("m1", "n1", MQttConnectionInfo("", "", "broker", "broker", 1883, False, False), Geofence(57.7, 11.9, 2000.0), slots={JobType.SIMULATION: 1})
job = JobSpec(job_id="check", job_type=JobType.SIMULATION, payload=payloads[3][2], attempt=1, idempotency_key="check")
stack = ardupilot_runner.build_job_stack(job, node, parse_payload(simulation_job.SimulationPayload, job).root)
assert "runner" in stack.compose["services"] and len(stack.compose["services"]) >= 3, stack.compose["services"].keys()
print("node side ok:", ", ".join(sorted(name for name, _, _ in payloads)))
"""


def test_every_job_type_s_node_side_runs_in_the_node_image():
    if _docker("info", check=False).returncode != 0:
        pytest.skip("Docker engine is not reachable")
    result = subprocess.run(
        ["docker", "run", "--rm", "-i", f"scenegems-node:{NODE_IMAGE_TAG}", "python", "-c", NODE_SIDE_CHECK],
        input=json.dumps(_scene_generation_payload()),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    assert "node side ok: monitoring.post_hoc, scene_generation, simulation ardupilot_sim, simulation gazebo, simulation kinematic, trajectory_generation" in result.stdout
