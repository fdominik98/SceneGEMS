"""Simulation jobs end to end in real subsystem containers, run from this machine against a throwaway broker.

These wait for a run to become a pod: the pools are Deployments in a cluster now, and the jobs that only need a pool
run on k3d (test_pool_jobs_on_kubernetes.py). Needs Docker and the subsystem images. SCENEGEMS_TEST_IMAGE_TAG selects the image tag
(default latest), so a branch can test the images built from it. The containers reach the
broker through host.docker.internal, which Docker Desktop resolves.
"""

import json
import os
import socket
import subprocess
import threading
import time
import uuid

import paho.mqtt.client as mqtt
import pytest

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.messages import LogStream
from scenegems_tool.cluster.worker_node.jobs.job_runner import run_job
from scenegems_tool.cluster.worker_node.launchers.docker_cli import container_ids_for_instance
from scenegems_tool.cluster.worker_node.subsystem import IMAGE_ENVIRONMENT_VARIABLES, Subsystem, subsystem_image
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext
from scenegems_tool.messaging.mqtt_client import CLUSTER_TOPIC_ROOT, MQttConnectionInfo
from scenegems_tool.subsystems.monitoring.monitoring_worker import SeriesMonitor
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import run_kinematic_replay

pytestmark = pytest.mark.docker

BROKER_IMAGE = "scenegems-mqtt-broker:latest"
GEOFENCE = Geofence(57.7, 11.9, 2000.0)


class RecordingReport:
    def __init__(self):
        self.statuses = []
        self.lines = []

    def status(self, message, progress=None):
        self.statuses.append((time.monotonic(), message, progress))

    def log(self, source, text, stream=LogStream.STDOUT):
        self.lines.append((source, text, stream))

    def first(self, message):
        return next(stamp for stamp, text, _ in self.statuses if text == message)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _broker_accepts(port: int) -> bool:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    try:
        client.connect("localhost", port, 5)
        client.disconnect()
        return True
    except OSError:
        return False


@pytest.fixture(scope="module", autouse=True)
def test_images():
    tag = os.environ.get("SCENEGEMS_TEST_IMAGE_TAG", "latest")
    previous = {variable: os.environ.get(variable) for variable in IMAGE_ENVIRONMENT_VARIABLES.values()}
    for subsystem, variable in IMAGE_ENVIRONMENT_VARIABLES.items():
        os.environ[variable] = subsystem_image(subsystem).rsplit(":", 1)[0] + f":{tag}" if previous[variable] is None else previous[variable]
    yield
    for variable, value in previous.items():
        if value is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = value


@pytest.fixture(scope="module")
def broker():
    """A NanoMQ broker on its own network, published on a free local port: (network, port)."""
    suffix = uuid.uuid4().hex[:8]
    network, name, port = f"scenegems-test-{suffix}", f"scenegems-test-broker-{suffix}", _free_port()
    subprocess.run(["docker", "network", "create", network], check=True, capture_output=True)
    subprocess.run(["docker", "run", "-d", "--name", name, "--network", network, "--tmpfs", "/data/broker", "-p", f"{port}:1883", BROKER_IMAGE], check=True, capture_output=True)
    try:
        deadline = time.monotonic() + 30
        while not _broker_accepts(port):
            assert time.monotonic() < deadline, "the test broker did not start"
            time.sleep(0.5)
        yield network, port
    finally:
        subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)
        subprocess.run(["docker", "network", "rm", network], check=False, capture_output=True)


def make_worker_node(broker, control_node_id: str, worker_node_id: str, slots) -> WorkerNodeContext:
    network, port = broker
    connection = MQttConnectionInfo("", "", "host.docker.internal", "localhost", port, False, False, topic_root=CLUSTER_TOPIC_ROOT)
    return WorkerNodeContext(control_node_id=control_node_id, worker_node_id=worker_node_id, mqtt_connection=connection, reference_geofence=GEOFENCE, slots=slots)


@pytest.fixture
def control_node_id() -> str:
    return f"t{uuid.uuid4().hex[:6]}"


def test_kinematic_simulation_runs_in_a_container(broker, control_node_id, make_job, head_on_trajectories):
    worker_node = make_worker_node(broker, control_node_id, "n1", {JobType.SIMULATION: 1})
    job = make_job(JobType.SIMULATION, {"runner": "kinematic", "trajectories": head_on_trajectories.to_dict(), "include_trajectories": False})
    report = RecordingReport()
    try:
        result = run_job(job, worker_node, report)
        scope = worker_node.job_scope(job)
        assert not container_ids_for_instance(scope.compose_project, scope.key)
    finally:
        worker_node.shutdown()  # its pool would answer the next test's requests on the shared broker
    assert result["state_digest"] == run_kinematic_replay(head_on_trajectories).state_digest()
    messages = [text for _, text, _ in report.statuses]
    assert "running the kinematic replay run" in messages and "run finished" in messages


def test_a_moos_ivp_job_steps_the_helm_in_its_container(broker, control_node_id, make_job, head_on_trajectories):
    """The kinematic runner in mode moos_ivp: the own ship's ASV system container is the MOOS-IvP image (./build.sh --simulation), stepped over the stack's network."""
    worker_node = make_worker_node(broker, control_node_id, "n1", {JobType.SIMULATION: 1})
    payload = {"runner": "kinematic", "mode": "moos_ivp", "moos_ivp": {"avoidance": "cpa"}, "trajectories": head_on_trajectories.to_dict(), "include_trajectories": False}
    results = []
    try:
        for index in range(2):
            job = make_job(JobType.SIMULATION, payload, job_id=f"moos-ivp-{index}")
            results.append(run_job(job, worker_node, RecordingReport()))
            scope = worker_node.job_scope(job)
            assert not container_ids_for_instance(scope.compose_project, scope.key)
    finally:
        worker_node.shutdown()
    first, second = results
    assert first["state_digest"] == second["state_digest"], "the helm runs one pass per step on the stepped clock, so a job repeats"
    assert first["state_digest"] != run_kinematic_replay(head_on_trajectories).state_digest(), "the helm steers the own ship off its planned track"
    record = first["run_record"]
    assert record["stacks"] == {"0": "moos_ivp, none, kinematic", "1": "replay, none, kinematic"}
    helm = record["moos_ivp"]
    assert helm["vessel"] == 0 and helm["parameters"]["avoidance"] == "cpa" and helm["avoidance_behaviour"] == "BHV_AvoidCollision"
    assert helm["no_decision_steps"] == 0 and helm["moos_ivp_commit"] and [0.0, "spawn", "avd_c1"] in helm["events"]


def test_two_kinematic_jobs_run_side_by_side(broker, control_node_id, make_job, head_on_trajectories):
    worker_node = make_worker_node(broker, control_node_id, "n1", {JobType.SIMULATION: 2})
    jobs = [
        make_job(JobType.SIMULATION, {"runner": "kinematic", "mode": "usv_navigation", "trajectories": head_on_trajectories.to_dict(), "include_trajectories": False}, job_id=f"side-{index}")
        for index in range(2)
    ]
    reports = [RecordingReport(), RecordingReport()]
    results = [None, None]

    def run(index):
        results[index] = run_job(jobs[index], worker_node, reports[index])

    threads = [threading.Thread(target=run, args=(index,)) for index in range(2)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=300)
    finally:
        worker_node.shutdown()
    assert results[0] is not None and results[1] is not None
    assert results[0]["state_digest"] == results[1]["state_digest"]
    # Both runner containers were up at once: each started before the other finished.
    assert reports[0].first("running") < reports[1].first("run finished")
    assert reports[1].first("running") < reports[0].first("run finished")


def test_a_kinematic_run_with_the_live_monitor_is_judged_by_the_monitoring_pool(broker, control_node_id, make_job, head_on_trajectories):
    """Needs the simulation and monitoring subsystem images built from the pooled subsystems code.

    The run's runner container asks the worker node's monitoring subsystem to judge its scenes, so that pool has to be
    up, as the daemon has it up for a worker node with the monitoring component.
    """
    worker_node = make_worker_node(broker, control_node_id, "n1", {JobType.SIMULATION: 1, JobType.MONITORING_POST_HOC: 1})
    job = make_job(JobType.SIMULATION, {"runner": "kinematic", "trajectories": head_on_trajectories.to_dict(), "include_trajectories": False, "monitor": "live"})
    in_process = SeriesMonitor("reference", head_on_trajectories.time_step)
    in_process.add(head_on_trajectories.scene_list)
    try:
        worker_node.pools.start([Subsystem.MONITORING])
        result = run_job(job, worker_node, RecordingReport())
    finally:
        worker_node.shutdown()
    assert result["state_digest"] == run_kinematic_replay(head_on_trajectories).state_digest()
    assert not result["monitor"]["passed"] and result["monitor"]["stopped_early_at"] is None
    assert {key: result["monitor"][key] for key in ("rules", "failed_rules", "passed")} == json.loads(json.dumps({key: in_process.summary()[key] for key in ("rules", "failed_rules", "passed")}))
