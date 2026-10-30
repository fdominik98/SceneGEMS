"""A live simulation end to end: a browser on the live channel watches a kinematic job that a node container runs.

The master is real and runs in this process (control plane on in-memory stores, the node API
over plain HTTP on all interfaces, the operator listener with the live channel on loopback, one event
loop as in the master process). The node is the scenegems-node image started from
deploy/node/docker-compose.yml; it connects to the master, which it trusts without pairing, and runs the job in a runner
container of the scenario execution image. The browser subscribes to the job's instance topic
with a speed as soon as the job is leased, and the frames of the paced run reach it.

Images: scenegems-node:<SCENEGEMS_TEST_NODE_IMAGE_TAG> and the subsystem images with
SCENEGEMS_TEST_IMAGE_TAG (both default latest). Build them from this checkout under a tag of
their own. Containers reach the test process through host.docker.internal (Docker Desktop).
"""

import asyncio
import json
import math
import os
import socket
import subprocess
import threading
import time
import urllib.request
import uuid
from pathlib import Path

import pytest
from websockets.asyncio.client import connect

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.cluster.master.api.master_apps import create_master_apps
from scenegems_tool.cluster.master.api.operator_routes import NODES_PATH
from scenegems_tool.cluster.master.control_plane import ControlPlane
from scenegems_tool.cluster.master.live.topics import create_live_channel
from scenegems_tool.cluster.master.scheduling.fingerprint_policy import ExpectedFingerprints
from scenegems_tool.cluster.master.server import listeners
from scenegems_tool.cluster.master.settings import Listener, MasterSettings
from scenegems_tool.cluster.node.subsystem import IMAGE_ENVIRONMENT_VARIABLES, Subsystem, subsystem_image
from scenegems_tool.cluster.protocol.jobs import JobSubmission, JobType
from scenegems_tool.cluster.protocol.live import instance_topic, job_instance
from scenegems_tool.cluster.protocol.routes import JOBS_PATH, LIVE_PATH
from scenegems_tool.persistence.clock import utc_now
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import run_kinematic_replay
from tests.scenegems_tool.cluster.master.fake_stores import InMemoryJobStore, InMemoryNodeStore
from tests.scenegems_tool.cluster.node.conftest import _vessel
from utils.file_system_utils import REPO_ROOT

pytestmark = [pytest.mark.docker, pytest.mark.slow]

IMAGE_TAG = os.environ.get("SCENEGEMS_TEST_IMAGE_TAG", "latest")
NODE_IMAGE_TAG = os.environ.get("SCENEGEMS_TEST_NODE_IMAGE_TAG", "latest")
COMPOSE_FILE = Path(REPO_ROOT) / "deploy" / "node" / "docker-compose.yml"
HOST = "host.docker.internal"
TIMEOUT_S = 240.0
STEPS = 300
SPEED = 50.0  # 300 s of scenario time in about 6 s


def _docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *arguments], capture_output=True, text=True, check=check, timeout=300)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _image(subsystem: Subsystem) -> str:
    return subsystem_image(subsystem).rsplit(":", 1)[0] + f":{IMAGE_TAG}"


class Master:
    """The master's node API and operator listeners on one event loop in a thread."""

    def __init__(self):
        self.node_port, self.operator_port = _free_port(), _free_port()
        self.master_id = f"m{uuid.uuid4().hex[:6]}"
        nodes = InMemoryNodeStore(utc_now)
        self.plane = ControlPlane(self.master_id, nodes, InMemoryJobStore(nodes, utc_now), ExpectedFingerprints.fixed({}))
        apps = create_master_apps(self.plane, live=create_live_channel(self.plane))
        settings = MasterSettings(
            master_id=self.master_id,
            database_url="postgresql://unused",
            node_api=Listener("0.0.0.0", self.node_port),
            operator=Listener("127.0.0.1", self.operator_port),
        )
        self.servers = listeners(settings, apps)
        self.thread = threading.Thread(target=lambda: asyncio.run(self._serve()), name="master", daemon=True)

    async def _serve(self) -> None:
        await asyncio.gather(*(server.serve() for server in self.servers))

    def start(self) -> "Master":
        self.thread.start()
        deadline = time.monotonic() + 30
        while not all(server.started for server in self.servers):
            assert time.monotonic() < deadline, "the master did not start"
            time.sleep(0.05)
        return self

    def stop(self) -> None:
        for server in self.servers:
            server.should_exit = True
        self.thread.join(timeout=30)

    @property
    def operator_url(self) -> str:
        return f"http://127.0.0.1:{self.operator_port}"

    def get(self, path: str):
        with urllib.request.urlopen(self.operator_url + path, timeout=10) as response:
            return json.loads(response.read())

    def post(self, path: str, body: dict):
        request = urllib.request.Request(self.operator_url + path, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read())


@pytest.fixture(scope="module")
def master():
    if _docker("info", check=False).returncode != 0:
        pytest.skip("Docker engine is not reachable")
    for image in (f"scenegems-node:{NODE_IMAGE_TAG}", _image(Subsystem.SCENARIO_EXECUTION)):
        if _docker("image", "inspect", image, check=False).returncode != 0:
            pytest.fail(f"Image {image} is missing; build it from this checkout or set the test image tags")
    master = Master().start()
    try:
        yield master
    finally:
        master.stop()


@pytest.fixture(scope="module")
def node(master, tmp_path_factory):
    node_name = f"live-{uuid.uuid4().hex[:6]}"
    env_file = tmp_path_factory.mktemp("node") / "node.env"
    values = {
        "SCENEGEMS_MASTER_URL": f"http://{HOST}:{master.node_port}",
        "SCENEGEMS_MASTER_ID": master.master_id,
        "SCENEGEMS_NODE_NAME": node_name,
        "SCENEGEMS_NODE_SLOTS": "simulation:1",
        "SCENEGEMS_NODE_COMPONENTS": "asv_software/replay,control_layer/none,simulation_layer/kinematic",
        "SCENEGEMS_IMAGE_TAG": NODE_IMAGE_TAG,  # the node image; the subsystem images come by their variables
        "SCENEGEMS_SOFTWARE_REVISION": "live-simulation-test",
        **{variable: _image(subsystem) for subsystem, variable in IMAGE_ENVIRONMENT_VARIABLES.items()},
    }
    env_file.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
    compose = ["docker", "compose", "-f", str(COMPOSE_FILE), "--env-file", str(env_file)]
    subprocess.run([*compose, "up", "-d"], capture_output=True, text=True, check=True, timeout=300)
    container = f"scenegems-node-{master.master_id}-{node_name}"
    try:
        deadline = time.monotonic() + TIMEOUT_S
        while not [view for view in master.get(NODES_PATH) if view["connected"]]:
            assert time.monotonic() < deadline, f"the node never connected:\n{_docker('logs', container, check=False).stdout[-4000:]}"
            time.sleep(0.5)
        yield container
    finally:
        subprocess.run([*compose, "down", "--volumes", "--timeout", "60"], capture_output=True, text=True, check=False, timeout=300)


def _trajectories():
    scene = ConcreteScene({_vessel(0, True): ActorState(0.0, 0.0, 6.0, 0.0), _vessel(1, False): ActorState(3000.0, 200.0, 6.0, math.pi)})
    return TrajectoryBuilder.default_trajectory_from_scene(scene, 1, STEPS)


def _wait_for_attempt(master: Master, job_id: str) -> dict:
    deadline = time.monotonic() + TIMEOUT_S
    while True:
        job = master.get(f"{JOBS_PATH}/{job_id}")
        if job["attempt"] >= 1:
            return job
        assert time.monotonic() < deadline, f"job {job_id} was never leased: {job}"
        time.sleep(0.05)


async def _watch(master: Master, topic: str, job_id: str):
    """Subscribes at SPEED and collects frames (with their arrival times) until the job's status is final."""
    frames, statuses = [], []
    async with connect(f"ws://127.0.0.1:{master.operator_port}{LIVE_PATH}", open_timeout=10) as browser:
        await browser.send(json.dumps({"version": 1, "type": "subscribe", "topic": topic, "options": {"speed": SPEED}}))
        subscribed = json.loads(await asyncio.wait_for(browser.recv(), 10))
        assert subscribed["type"] == "subscribed", subscribed
        assert subscribed["snapshot"]["observed_speed"] == SPEED and subscribed["snapshot"]["kind"] == "simulation"
        deadline = time.monotonic() + TIMEOUT_S
        while not statuses or statuses[-1]["state"] not in ("succeeded", "failed"):
            message = json.loads(await asyncio.wait_for(browser.recv(), max(1.0, deadline - time.monotonic())))
            assert message["type"] == "update", message
            data = message["data"]
            if data["kind"] == "simulation_frames":
                assert data["job_id"] == job_id
                frames.extend((time.monotonic(), frame) for frame in data["frames"])
            elif data["kind"] == "status":
                statuses.append(data)
    return subscribed, frames, statuses


def test_a_browser_watches_an_observed_kinematic_run_at_its_speed(master, node):
    trajectories = _trajectories()
    payload = {"runner": "kinematic", "trajectories": trajectories.to_dict(), "monitor": "live", "include_trajectories": False}
    job = master.post(JOBS_PATH, JobSubmission(job_type=JobType.SIMULATION, payload=payload).model_dump(mode="json"))
    leased = _wait_for_attempt(master, job["job_id"])
    topic = instance_topic(leased["lease_owner"], job_instance(job["job_id"], 1))

    _, frames, statuses = asyncio.run(_watch(master, topic, job["job_id"]))

    finished = master.get(f"{JOBS_PATH}/{job['job_id']}")
    assert finished["state"] == "succeeded", (finished["error"], _docker("logs", node, check=False).stdout[-4000:])
    assert finished["result"]["state_digest"] == run_kinematic_replay(trajectories).state_digest()  # observing changed nothing in the run
    timestamps = [frame["timestamp"] for _, frame in frames]
    assert timestamps == sorted(timestamps) and timestamps[-1] == STEPS and len(timestamps) > STEPS / 10
    assert all(set(frame["statesByActorId"]) == {"0", "1"} and frame["scenarioId"] == job["job_id"] for _, frame in frames)
    assert any(frame["ruleResults"] for _, frame in frames)  # the live monitor's outcomes come with the states
    # Paced: the frames of the observed part took about its scenario time divided by the speed
    observed_scenario_s = timestamps[-1] - timestamps[0]
    wall_s = frames[-1][0] - frames[0][0]
    assert wall_s >= 0.7 * observed_scenario_s / SPEED, (wall_s, observed_scenario_s)
    assert statuses[-1]["state"] == "succeeded"
