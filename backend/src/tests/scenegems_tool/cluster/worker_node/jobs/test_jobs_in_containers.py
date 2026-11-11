"""Jobs end to end in real subsystem containers, run from this machine against a throwaway broker.

Needs Docker and the subsystem images. SCENEGEMS_TEST_IMAGE_TAG selects the image tag
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

from functional_level.models.model_parser import ModelParser
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.messages import LogStream
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.jobs.calibration_deviation_job import CalibrationDeviationPayload, compare
from scenegems_tool.cluster.worker_node.jobs.job_runner import run_job
from scenegems_tool.cluster.worker_node.launchers.docker_cli import container_ids_for_instance, is_container_running
from scenegems_tool.cluster.worker_node.subsystem import IMAGE_ENVIRONMENT_VARIABLES, Subsystem, subsystem_image
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext
from scenegems_tool.messaging.mqtt_client import CLUSTER_TOPIC_ROOT, MQttConnectionInfo
from scenegems_tool.subsystems.design_space_exploration.design_space import default_specification, parse_scope
from scenegems_tool.subsystems.monitoring.monitoring_worker import SeriesMonitor
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import run_kinematic_replay
from utils.file_system_utils import COLREGS_CONSTANTS_FOLDER, FUNCTIONAL_MODELS_FOLDER, STATIC_OBSTACLE_TYPES_FOLDER, VESSEL_TYPES_FOLDER

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
    return WorkerNodeContext(control_node_id=control_node_id, worker_node_id=worker_node_id, mqtt_connection=connection, reference_geofence=GEOFENCE, slots=slots, broker_network=network)


@pytest.fixture
def control_node_id() -> str:
    return f"t{uuid.uuid4().hex[:6]}"


def test_kinematic_simulation_runs_in_a_container(broker, control_node_id, make_job, head_on_trajectories):
    worker_node = make_worker_node(broker, control_node_id, "n1", {JobType.SIMULATION: 1})
    job = make_job(JobType.SIMULATION, {"runner": "kinematic", "trajectories": head_on_trajectories.to_dict(), "include_trajectories": False})
    report = RecordingReport()
    result = run_job(job, worker_node, report)
    assert result["state_digest"] == run_kinematic_replay(head_on_trajectories).state_digest()
    messages = [text for _, text, _ in report.statuses]
    assert "running the kinematic replay run" in messages and "run finished" in messages
    scope = worker_node.job_scope(job)
    assert not container_ids_for_instance(scope.compose_project, scope.key)


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
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=300)
    assert results[0] is not None and results[1] is not None
    assert results[0]["state_digest"] == results[1]["state_digest"]
    # Both runner containers were up at once: each started before the other finished.
    assert reports[0].first("running") < reports[1].first("run finished")
    assert reports[1].first("running") < reports[0].first("run finished")


def test_post_hoc_monitoring_runs_on_the_monitoring_pool(broker, control_node_id, make_job, head_on_trajectories):
    """Needs the monitoring subsystem image built from the pooled subsystems code."""
    worker_node = make_worker_node(broker, control_node_id, "n1", {JobType.MONITORING_POST_HOC: 2})
    in_process = SeriesMonitor("reference", head_on_trajectories.time_step)
    in_process.add(head_on_trajectories.scene_list)
    try:
        results = [
            run_job(make_job(JobType.MONITORING_POST_HOC, {"trajectories": head_on_trajectories.to_dict(), "include_frames": frames}, job_id=f"monitor-{index}"), worker_node, RecordingReport())
            for index, frames in enumerate((False, True))
        ]
        pool = worker_node.pools.get(Subsystem.MONITORING)
        assert pool.names.container_name == f"scenegems-{control_node_id}-n1-monitoring-subsystem" and is_container_running(pool.names.container_name), "one long-lived container for both jobs"
    finally:
        worker_node.shutdown()
    for result in results:
        assert (result["scenes"], result["monitored_scenes"], result["time_step"]) == (121, 121, 1)
        assert {key: result[key] for key in ("rules", "failed_rules", "encounters", "encounter_roles", "passed")} == json.loads(json.dumps(in_process.summary()))
    assert "frames" not in results[0] and [frame["timestamp"] for frame in results[1]["frames"]] == list(range(121))
    assert {frame["scenarioId"] for frame in results[1]["frames"]} == {"monitor-1-1"}


def test_the_design_space_exploration_pool_explores_and_refuses_what_does_not_parse(broker, control_node_id, make_job):
    """Needs the design space exploration image built from the pooled subsystems code. Both jobs go to one long-lived container."""
    worker_node = make_worker_node(broker, control_node_id, "n1", {JobType.DESIGN_SPACE_EXPLORATION: 1})
    report = RecordingReport()
    try:
        explored = make_job(JobType.DESIGN_SPACE_EXPLORATION, {"problem": default_specification(), "scopes": list(parse_scope("TS = 1, StaticObstacle = 0")), "timeout_s": 120}, job_id="explore-1")
        result = run_job(explored, worker_node, report)
        pool = worker_node.pools.get(Subsystem.DESIGN_SPACE_EXPLORATION)
        assert pool.names.container_name == f"scenegems-{control_node_id}-n1-design-space-exploration-subsystem" and is_container_running(pool.names.container_name)
        broken = make_job(JobType.DESIGN_SPACE_EXPLORATION, {"problem": "class A extends Missing.", "scopes": ["A=1"], "timeout_s": 60}, job_id="explore-2")
        with pytest.raises(JobFailed) as failure:
            run_job(broken, worker_node, RecordingReport())
        assert not failure.value.retryable and str(failure.value)
        assert is_container_running(pool.names.container_name), "a problem that does not parse ends its generator, not the subsystem"
    finally:
        worker_node.shutdown()
    assert (result["stop_reason"], result["complete"], result["models_found"]) == ("exhausted", True, 7)
    assert result["fecs"] == [{"index": index, "vessel_count": 2, "obstacle_count": 0} for index in range(7)]
    scenarios = [ModelParser.parse_problem(source) for source in result["functional_scenarios"]]
    assert len({scenario.fec_shape_hash() for scenario in scenarios}) == 7
    assert all("\nTS(ts1).\n" in source and "tS1" not in source for source in result["functional_scenarios"])  # the catalog's name for the generator's tS1
    assert all(source.startswith(default_specification().split("declare", 1)[0].rstrip()) for source in result["functional_scenarios"])  # the metamodel and constraints as given, then the model
    messages = [(text, progress) for _, text, progress in report.statuses]
    assert any(text.startswith("finished") for text, _ in messages) and messages[-1][1] == 1.0


def test_a_kinematic_run_with_the_live_monitor_runs_in_a_container(broker, control_node_id, make_job, head_on_trajectories):
    """Needs the simulation subsystem image built from Phase 4 (P4.2) code."""
    worker_node = make_worker_node(broker, control_node_id, "n1", {JobType.SIMULATION: 1})
    job = make_job(JobType.SIMULATION, {"runner": "kinematic", "trajectories": head_on_trajectories.to_dict(), "include_trajectories": False, "monitor": "live"})
    result = run_job(job, worker_node, RecordingReport())
    assert result["state_digest"] == run_kinematic_replay(head_on_trajectories).state_digest()
    assert not result["monitor"]["passed"] and result["monitor"]["stopped_early_at"] is None


def test_calibration_runs_on_the_simulation_pool(broker, control_node_id, make_job, head_on_trajectories):
    """Needs the simulation subsystem image built from the pooled subsystems code."""
    worker_node = make_worker_node(broker, control_node_id, "n1", {JobType.CALIBRATION_DEVIATION: 1})
    payload = {"trajectories": [head_on_trajectories.to_dict()] * 2, "reference": "head_on"}
    try:
        result = run_job(make_job(JobType.CALIBRATION_DEVIATION, payload), worker_node, RecordingReport())
        assert is_container_running(worker_node.pools.get(Subsystem.SIMULATION).names.container_name)
    finally:
        worker_node.shutdown()
    assert result == json.loads(json.dumps(compare(CalibrationDeviationPayload.model_validate(payload), lambda message, progress=None: None)))
    assert result["exact"] and result["deviation_bound_m"] == 0.0


def _scene_generation_payload() -> dict:
    def read(path):
        with open(path, encoding="utf-8") as file:
            return file.read()

    return {
        "functional_scenario_content": read(f"{FUNCTIONAL_MODELS_FOLDER}/all/2vessel_0obstacle_scenarios/fec0.problem"),
        "colregs_constraints_content": read(f"{COLREGS_CONSTANTS_FOLDER}/general_maritime_constants.yaml"),
        "vessel_types_content": read(f"{VESSEL_TYPES_FOLDER}/vessel_types.yaml"),
        "obstacle_types_content": read(f"{STATIC_OBSTACLE_TYPES_FOLDER}/static_obstacle_types.yaml"),
        "timeout_s": 120,
    }


@pytest.mark.slow
def test_two_scene_generation_pools_run_side_by_side(broker, control_node_id, make_job):
    """Two worker nodes on one machine and one broker: each pool answers its own job, on its own topics only."""
    worker_nodes = [make_worker_node(broker, control_node_id, worker_node_id, {JobType.SCENE_GENERATION: 2}) for worker_node_id in ("n1", "n2")]
    for number, worker_node in enumerate(worker_nodes, start=1):
        worker_node.set_instance_number(number)  # as the control node's Welcome would: it names the pool on the broker
    heartbeat_topics = set()
    listener = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    listener.on_message = lambda client, userdata, message: heartbeat_topics.add(message.topic)
    listener.connect("localhost", broker[1])
    listener.subscribe("+/service/virtual/real/+/heartbeat")
    listener.loop_start()
    results = {}

    def run(worker_node):
        payload = {**_scene_generation_payload(), "seed": 5}
        results[worker_node.worker_node_id] = run_job(make_job(JobType.SCENE_GENERATION, payload, job_id=f"scene-{worker_node.worker_node_id}"), worker_node, RecordingReport())

    try:
        threads = [threading.Thread(target=run, args=(worker_node,)) for worker_node in worker_nodes]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=600)
        pool_containers = [worker_node.pools.get(Subsystem.SCENE_GENERATION).names.container_name for worker_node in worker_nodes]
        assert all(is_container_running(name) for name in pool_containers)
        assert pool_containers == [f"scenegems-{control_node_id}-n1-scene-generation-subsystem", f"scenegems-{control_node_id}-n2-scene-generation-subsystem"]
        pool_topics = {worker_node.pools.get(Subsystem.SCENE_GENERATION).service_topic for worker_node in worker_nodes}
        assert {topic.rsplit("/", 1)[1] for topic in pool_topics} == {"scene-generation-subsystem-1", "scene-generation-subsystem-2"}
    finally:
        listener.loop_stop()
        listener.disconnect()
        for worker_node in worker_nodes:
            worker_node.shutdown()

    assert set(results) == {"n1", "n2"}
    for worker_node_id, result in results.items():
        assert result["request_id"] == f"scene-{worker_node_id}-1"
        assert isinstance(result["valid"], bool)
        assert result["evaluation_data"]["random_seed"] == 5
    # The job takes the worker's final scene, so the same seed gives both pools the same scene.
    assert results["n1"]["evaluation_data"]["best_scene"] == results["n2"]["evaluation_data"]["best_scene"]
    assert heartbeat_topics == {f"{topic}/heartbeat" for topic in pool_topics}, "each pool under its own name, with no level for its worker node"
    assert not any(is_container_running(name) for name in pool_containers)
