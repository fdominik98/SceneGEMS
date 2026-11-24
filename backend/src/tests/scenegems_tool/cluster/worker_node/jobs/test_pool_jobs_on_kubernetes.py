"""Jobs served by pools in a real cluster (k3d), through jobs/pool_client.py as the daemon relays them.

The launcher runs in the test process with the daemon's service account (worker_node/conftest.py k3d_worker_node),
and so does the job's side of the request; the pools run as Deployments of the imported images and reach the
cluster broker by its service, the test process by its node port. Needs k3d, kubectl, Docker and the images
(worker_node/k3d_cluster.py). The jobs that run a simulation wait for a run to become a pod (test_jobs_in_containers.py).
"""

import json
import threading
import time

import paho.mqtt.client as mqtt
import pytest

from functional_level.models.model_parser import ModelParser
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.messages import LogStream
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.jobs.calibration_deviation_job import CalibrationDeviationPayload, compare
from scenegems_tool.cluster.worker_node.jobs.job_runner import run_job
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.gateway.frame_series import decode_frames
from scenegems_tool.subsystems.design_space_exploration.design_space import default_specification, parse_scope
from scenegems_tool.subsystems.monitoring.monitoring_worker import SeriesMonitor
from utils.file_system_utils import COLREGS_CONSTANTS_FOLDER, FUNCTIONAL_MODELS_FOLDER, STATIC_OBSTACLE_TYPES_FOLDER, VESSEL_TYPES_FOLDER

pytestmark = pytest.mark.kubernetes


class RecordingReport:
    def __init__(self):
        self.statuses = []
        self.lines = []

    def status(self, message, progress=None):
        self.statuses.append((time.monotonic(), message, progress))

    def log(self, source, text, stream=LogStream.STDOUT):
        self.lines.append((source, text, stream))


def test_post_hoc_monitoring_runs_on_the_monitoring_pool(k3d_worker_node, make_job, head_on_trajectories):
    worker_node = k3d_worker_node({JobType.MONITORING_POST_HOC: 2})
    in_process = SeriesMonitor("reference", head_on_trajectories.time_step)
    in_process.add(head_on_trajectories.scene_list)
    results = [
        run_job(make_job(JobType.MONITORING_POST_HOC, {"trajectories": head_on_trajectories.to_dict(), "include_frames": frames}, job_id=f"monitor-{index}"), worker_node, RecordingReport())
        for index, frames in enumerate((False, True))
    ]
    pool = worker_node.pools.get(Subsystem.MONITORING)
    assert pool.names.deployment == f"{worker_node.worker_node_id}-monitoring-subsystem" and pool.is_available(), "one long-lived pool for both jobs"
    for result in results:
        assert (result["scenes"], result["monitored_scenes"], result["time_step"]) == (121, 121, 1)
        assert {key: result[key] for key in ("rules", "failed_rules", "encounters", "encounter_roles", "passed")} == json.loads(json.dumps(in_process.summary()))
    frames = decode_frames(results[1]["frames"])
    assert "frames" not in results[0] and [frame["timestamp"] for frame in frames] == list(range(121))
    assert {frame["scenarioId"] for frame in frames} == {"monitor-1-1"}


def test_the_design_space_exploration_pool_explores_and_refuses_what_does_not_parse(k3d_worker_node, make_job):
    """Both jobs go to one long-lived pool."""
    worker_node = k3d_worker_node({JobType.DESIGN_SPACE_EXPLORATION: 1})
    report = RecordingReport()
    explored = make_job(JobType.DESIGN_SPACE_EXPLORATION, {"problem": default_specification(), "scopes": list(parse_scope("TS = 1, StaticObstacle = 0")), "timeout_s": 120}, job_id="explore-1")
    result = run_job(explored, worker_node, report)
    pool = worker_node.pools.get(Subsystem.DESIGN_SPACE_EXPLORATION)
    assert pool.names.deployment == f"{worker_node.worker_node_id}-design-space-exploration-subsystem" and pool.is_available()
    broken = make_job(JobType.DESIGN_SPACE_EXPLORATION, {"problem": "class A extends Missing.", "scopes": ["A=1"], "timeout_s": 60}, job_id="explore-2")
    with pytest.raises(JobFailed) as failure:
        run_job(broken, worker_node, RecordingReport())
    assert not failure.value.retryable and str(failure.value)
    assert pool.is_available(), "a problem that does not parse ends its generator, not the subsystem"
    assert (result["stop_reason"], result["complete"], result["models_found"]) == ("exhausted", True, 7)
    assert result["fecs"] == [{"index": index, "vessel_count": 2, "obstacle_count": 0} for index in range(7)]
    scenarios = [ModelParser.parse_problem(source) for source in result["functional_scenarios"]]
    assert len({scenario.fec_shape_hash() for scenario in scenarios}) == 7
    assert all("\nTS(ts1).\n" in source and "tS1" not in source for source in result["functional_scenarios"])  # the catalog's name for the generator's tS1
    assert all(source.startswith(default_specification().split("declare", 1)[0].rstrip()) for source in result["functional_scenarios"])  # the metamodel and constraints as given, then the model
    messages = [(text, progress) for _, text, progress in report.statuses]
    assert any(text.startswith("finished") for text, _ in messages) and messages[-1][1] == 1.0


def test_calibration_runs_on_the_simulation_pool(k3d_cluster, k3d_worker_node, make_job, head_on_trajectories):
    """The simulation pool in its pod: its service account, the node's runtime folder; a comparison needs no run."""
    worker_node = k3d_worker_node({JobType.CALIBRATION_DEVIATION: 1})
    payload = {"trajectories": [head_on_trajectories.to_dict()] * 2, "reference": "head_on"}
    result = run_job(make_job(JobType.CALIBRATION_DEVIATION, payload), worker_node, RecordingReport())
    pool = worker_node.pools.get(Subsystem.SIMULATION)
    assert pool.is_available()
    assert result == json.loads(json.dumps(compare(CalibrationDeviationPayload.model_validate(payload), lambda message, progress=None: None)))
    assert result["exact"] and result["deviation_bound_m"] == 0.0
    [pod] = k3d_cluster.pods(",".join(f"{key}={value}" for key, value in pool.names.labels.items()))
    assert pod["spec"]["serviceAccountName"] == "simulation-subsystem"
    assert pod["spec"]["volumes"][0]["hostPath"]["path"] == f"/var/lib/scenegems/{worker_node.worker_node_id}/runtime"


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
def test_two_scene_generation_pools_run_side_by_side(k3d_cluster, k3d_worker_node, make_job):
    """Two worker nodes in one namespace and on one broker: each pool answers its own job, on its own topics only."""
    worker_nodes = [k3d_worker_node({JobType.SCENE_GENERATION: 2}) for _ in range(2)]
    heartbeat_topics = set()
    listener = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    listener.on_message = lambda client, userdata, message: heartbeat_topics.add(message.topic)
    listener.connect("127.0.0.1", k3d_cluster.broker_port)
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
        pools = [worker_node.pools.get(Subsystem.SCENE_GENERATION) for worker_node in worker_nodes]
        assert all(pool.is_available() for pool in pools)
        assert [pool.names.deployment for pool in pools] == [f"{worker_node.worker_node_id}-scene-generation-subsystem" for worker_node in worker_nodes]
        pool_topics = {pool.service_topic for pool in pools}
        assert {topic.rsplit("/", 1)[1] for topic in pool_topics} == {f"scene-generation-subsystem-{worker_node.instance_number}" for worker_node in worker_nodes}
    finally:
        listener.loop_stop()
        listener.disconnect()

    assert set(results) == {worker_node.worker_node_id for worker_node in worker_nodes}
    for worker_node_id, result in results.items():
        assert result["request_id"] == f"scene-{worker_node_id}-1"
        assert isinstance(result["valid"], bool)
        assert result["evaluation_data"]["random_seed"] == 5
    first, second = results.values()
    # The job takes the worker's final scene, so the same seed gives both pools the same scene.
    assert first["evaluation_data"]["best_scene"] == second["evaluation_data"]["best_scene"]
    assert {f"{topic}/heartbeat" for topic in pool_topics} <= heartbeat_topics, "each pool under its own name"
    assert all(topic.split("/")[:4] == ["scenegems", "service", "virtual", "real"] and topic.count("/") == 5 for topic in heartbeat_topics), "with no level for its worker node"
