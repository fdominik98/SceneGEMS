"""Simulation runs in a real cluster (k3d): a run is one pod that the worker node's simulation pool creates.

The launcher runs in the test process with the daemon's service account (worker_node/conftest.py k3d_worker_node);
the simulation pool runs as its Deployment, under the simulation subsystem's own service account, and creates the
pod of each run through the cluster API. Needs k3d, kubectl, Docker and the images of SCENEGEMS_TEST_IMAGE_TAG
(worker_node/k3d_cluster.py), and for the runs with a stack image of their own the MOOS-IvP, USV Navigation and
ArduPilot SITL images of that tag (stack_images, sitl_image).
"""

import json
import math
import os
import threading
import time
from typing import Dict, List, Optional

import pytest

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.messages import LogStream
from scenegems_tool.cluster.worker_node.instance_scope import WORKER_NODE_LABEL
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.jobs.job_runner import run_job
from scenegems_tool.cluster.worker_node.launchers.per_job.run_pod import RUN_COMPONENT, RUN_COMPONENT_LABEL, RUNNER_SERVICE
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.subsystems.monitoring.monitoring_worker import SeriesMonitor
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import run_kinematic_replay
from tests.scenegems_tool.cluster.worker_node.conftest import _vessel
from tests.scenegems_tool.cluster.worker_node.k3d_cluster import CONTAINER_LOG_MAX_SIZE

pytestmark = pytest.mark.kubernetes

GEOFENCE = {"latitude": 57.7, "longitude": 11.9, "radius_meters": 2000.0}


class RecordingReport:
    def __init__(self):
        self.statuses = []
        self.lines = []

    def status(self, message, progress=None, detail=None):
        self.statuses.append((time.monotonic(), message, progress))

    def log(self, source, text, stream=LogStream.STDOUT):
        self.lines.append((source, text, stream))

    def first(self, message):
        return next(stamp for stamp, text, _ in self.statuses if text == message)

    def messages(self):
        return [text for _, text, _ in self.statuses]


class RunPods:
    """Looks at the run pods of a worker node every half second while a test runs: every pod it saw, and how many at once."""

    def __init__(self, k3d_cluster, worker_node_id: str):
        self._cluster = k3d_cluster
        self.selector = f"{WORKER_NODE_LABEL}={worker_node_id},{RUN_COMPONENT_LABEL}={RUN_COMPONENT}"
        self.seen: Dict[str, dict] = {}
        self.most_at_once = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, daemon=True)

    def __enter__(self) -> "RunPods":
        self._thread.start()
        return self

    def __exit__(self, *_) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def _watch(self) -> None:
        while not self._stop.wait(0.5):
            try:
                pods = self._cluster.pods(self.selector)
            except Exception:
                continue
            for pod in pods:
                self.seen.setdefault(pod["metadata"]["name"], pod)
            self.most_at_once = max(self.most_at_once, len(pods))


def assert_nothing_left(k3d_cluster, worker_node) -> None:
    """No run pod, no run service and no run folder of the worker node; a pod that is being deleted may take its grace period."""
    selector = f"{WORKER_NODE_LABEL}={worker_node.worker_node_id},{RUN_COMPONENT_LABEL}={RUN_COMPONENT}"
    k3d_cluster.wait_for(lambda: not k3d_cluster.pods(selector), timeout_s=60, what="the run's pod gone")
    assert k3d_cluster.json("services", "-l", selector)["items"] == []
    instances = f"{worker_node.cluster.runtime_host_path}/instances"
    listing = k3d_cluster.node_run("sh", "-c", f"ls -1 {instances} 2>/dev/null || true").stdout.split()
    assert [name for name in listing if name.startswith(f"{worker_node.worker_node_id}-simulation-subsystem-")] == [], "no run's folder on the node"


def kinematic_job(make_job, trajectories, job_id: str, **fields):
    return make_job(JobType.SIMULATION, {"runner": "kinematic", "trajectories": trajectories.to_dict(), "include_trajectories": False, **fields}, job_id=job_id)


def collect_frames(observation, stop: threading.Event) -> List[dict]:
    """Takes the observation's batches until stop, as the daemon's relay does; returns the frames in order."""
    frames: List[dict] = []
    while not stop.is_set():
        batch = observation.take_batch()
        if batch is None:
            stop.wait(0.05)
            continue
        frames.extend(batch[1])
    while True:
        batch = observation.take_batch(force=True)
        if batch is None:
            return frames
        frames.extend(batch[1])


@pytest.fixture(scope="module")
def stack_images(k3d_cluster):
    """The ASV system images of the stacks below, imported into the cluster by tag and named to the pools as the daemon names them."""
    tag = k3d_cluster.image_tag
    images = {"MOOS_IVP_IMAGE": f"scenegems-moos-ivp:{tag}", "USV_NAVIGATION_IMAGE": f"scenegems-usv-navigation:{tag}"}
    k3d_cluster.import_images(list(images.values()))
    previous = {variable: os.environ.get(variable) for variable in images}
    os.environ.update(images)
    yield images
    for variable, value in previous.items():
        if value is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = value


# Runs


def test_a_kinematic_run_is_one_pod_owned_by_the_pool_and_gives_the_in_process_digest(k3d_cluster, k3d_worker_node, make_job, head_on_trajectories):
    worker_node = k3d_worker_node({JobType.SIMULATION: 1})
    report = RecordingReport()
    with RunPods(k3d_cluster, worker_node.worker_node_id) as pods:
        job = kinematic_job(make_job, head_on_trajectories, "kinematic-1")
        result = run_job(job, worker_node, report)
    assert result["state_digest"] == run_kinematic_replay(head_on_trajectories).state_digest()
    assert "running the kinematic replay run" in report.messages() and "run finished" in report.messages()
    [pod] = pods.seen.values()
    pool = worker_node.pools.get(Subsystem.SIMULATION)
    [pool_pod] = k3d_cluster.pods(",".join(f"{key}={value}" for key, value in pool.names.labels.items()))
    assert pod["metadata"]["name"] == worker_node.job_scope(job).name == f"{worker_node.worker_node_id}-simulation-subsystem-kinemati"
    assert [(owner["kind"], owner["name"]) for owner in pod["metadata"]["ownerReferences"]] == [("Pod", pool_pod["metadata"]["name"])], "owned by the pool's pod"
    spec = pod["spec"]
    assert spec["nodeName"] == k3d_cluster.node and spec["restartPolicy"] == "Never"
    assert [container["name"] for container in spec["containers"]] == [RUNNER_SERVICE]
    assert {container["name"] for container in spec["initContainers"]} == {"kinematic-sim", "os-asv-system", "ts1-asv-system"}
    assert all(container["restartPolicy"] == "Always" for container in spec["initContainers"])
    assert spec["hostAliases"] == [{"ip": "127.0.0.1", "hostnames": ["kinematic-sim", "os-asv-system", "runner", "ts1-asv-system"]}]
    assert spec["serviceAccountName"] == "default" and spec["automountServiceAccountToken"] is False, "a run talks to no cluster API"
    assert_nothing_left(k3d_cluster, worker_node)


def test_a_moos_ivp_run_steps_the_helm_in_its_sidecar_and_repeats(k3d_cluster, k3d_worker_node, stack_images, make_job, head_on_trajectories):
    """The kinematic runner in mode moos_ivp: the own ship's ASV system is a sidecar of the MOOS-IvP image, its MOOSDB on the own ship's port."""
    worker_node = k3d_worker_node({JobType.SIMULATION: 1})
    payload = {"mode": "moos_ivp", "moos_ivp": {"avoidance": "cpa"}}
    results = [run_job(kinematic_job(make_job, head_on_trajectories, f"moos-ivp-{index}", **payload), worker_node, RecordingReport()) for index in range(2)]
    first, second = results
    assert first["state_digest"] == second["state_digest"], "the helm runs one pass per step on the stepped clock, so a job repeats"
    assert first["state_digest"] != run_kinematic_replay(head_on_trajectories).state_digest(), "the helm steers the own ship off its planned track"
    record = first["run_record"]
    assert record["stacks"] == {"0": "moos_ivp, none, kinematic", "1": "replay, none, kinematic"}
    helm = record["moos_ivp"]
    assert helm["vessel"] == 0 and helm["parameters"]["avoidance"] == "cpa" and helm["avoidance_behaviour"] == "BHV_AvoidCollision"
    assert helm["no_decision_steps"] == 0 and helm["moos_ivp_commit"] and [0.0, "spawn", "avd_c1"] in helm["events"]
    assert_nothing_left(k3d_cluster, worker_node)


def test_two_kinematic_runs_side_by_side_on_one_node_are_two_pods(k3d_cluster, k3d_worker_node, stack_images, make_job, head_on_trajectories):
    """Two pods with the same container names and ports inside: each pod is a network of its own."""
    worker_node = k3d_worker_node({JobType.SIMULATION: 2})
    jobs = [kinematic_job(make_job, head_on_trajectories, f"side-{index}", mode="usv_navigation") for index in range(2)]
    reports = [RecordingReport(), RecordingReport()]
    results: List[Optional[dict]] = [None, None]
    failures: List[BaseException] = []

    def run(index):
        try:
            results[index] = run_job(jobs[index], worker_node, reports[index])
        except BaseException as error:  # the test thread reports it
            failures.append(error)

    threads = [threading.Thread(target=run, args=(index,)) for index in range(2)]
    with RunPods(k3d_cluster, worker_node.worker_node_id) as pods:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=600)
    assert not failures, failures
    assert results[0]["state_digest"] == results[1]["state_digest"]
    assert reports[0].first("running") < reports[1].first("run finished") and reports[1].first("running") < reports[0].first("run finished"), "both runners ran at once"
    assert pods.most_at_once == 2 and len(pods.seen) == 2
    assert {pod["spec"]["nodeName"] for pod in pods.seen.values()} == {k3d_cluster.node}
    assert_nothing_left(k3d_cluster, worker_node)


def test_a_kinematic_run_with_the_live_monitor_is_judged_by_the_monitoring_pool(k3d_cluster, k3d_worker_node, make_job, head_on_trajectories):
    """The runner reaches the cluster's broker from the pod by its service name, and asks the worker node's monitoring pool to judge its scenes."""
    worker_node = k3d_worker_node({JobType.SIMULATION: 1, JobType.MONITORING_POST_HOC: 1})
    in_process = SeriesMonitor("reference", head_on_trajectories.time_step)
    in_process.add(head_on_trajectories.scene_list)
    worker_node.pools.start([Subsystem.MONITORING])
    result = run_job(kinematic_job(make_job, head_on_trajectories, "judged-1", monitor="live"), worker_node, RecordingReport())
    assert result["state_digest"] == run_kinematic_replay(head_on_trajectories).state_digest()
    assert not result["monitor"]["passed"] and result["monitor"]["stopped_early_at"] is None
    assert {key: result["monitor"][key] for key in ("rules", "failed_rules", "passed")} == json.loads(json.dumps({key: in_process.summary()[key] for key in ("rules", "failed_rules", "passed")}))
    assert_nothing_left(k3d_cluster, worker_node)


def test_an_observed_run_hands_its_frames_to_the_jobs_observation(k3d_cluster, k3d_worker_node, make_job, head_on_trajectories):
    worker_node = k3d_worker_node({JobType.SIMULATION: 1})
    job = kinematic_job(make_job, head_on_trajectories, "observed-1")
    observation = worker_node.observations.open(job)
    observation.request(True, 20.0)  # 20 steps a second: every step is a frame
    stop = threading.Event()
    collected: List[dict] = []
    collector = threading.Thread(target=lambda: collected.extend(collect_frames(observation, stop)), daemon=True)
    collector.start()
    try:
        result = run_job(job, worker_node, RecordingReport())
    finally:
        stop.set()
        collector.join(timeout=10)
        worker_node.observations.close(job)
    assert result["state_digest"] == run_kinematic_replay(head_on_trajectories).state_digest(), "an observed run is the same run"
    assert [frame["timestamp"] for frame in collected] == list(range(121)), "every step, once, in order"
    assert {frame["scenarioId"] for frame in collected} == {job.job_id}
    assert_nothing_left(k3d_cluster, worker_node)


def test_the_runners_log_is_followed_across_the_kubelets_rotation(k3d_cluster, k3d_worker_node, make_job):
    """An observed run whose frame lines are several times the kubelet's log file (CONTAINER_LOG_MAX_SIZE): every frame arrives, in order."""
    worker_node = k3d_worker_node({JobType.SIMULATION: 1})
    scene = ConcreteScene({_vessel(0, True): ActorState(0.0, 0.0, 8.0, 0.0), _vessel(1, False): ActorState(0.0, 3000.0, 8.0, 0.0)})
    steps = 2400
    trajectories = TrajectoryBuilder.default_trajectory_from_scene(scene, 1, steps)
    job = kinematic_job(make_job, trajectories, "rotation-1")
    observation = worker_node.observations.open(job)
    observation.request(True, 20.0)  # 20 frames a second, the most a run writes: about 25 kB a second of log
    stop = threading.Event()
    collected: List[dict] = []
    collector = threading.Thread(target=lambda: collected.extend(collect_frames(observation, stop)), daemon=True)
    log_files: List[str] = []

    def look_at_the_log_files() -> None:
        """The runner's log files on the node while it runs: a rotated file is the proof the rotation happened."""
        while not stop.wait(5.0):
            listing = k3d_cluster.node_run(
                "sh", "-c", f"ls /var/log/pods/{k3d_cluster.namespace}_{worker_node.worker_node_id}-simulation-subsystem-rotation*/{RUNNER_SERVICE}/ 2>/dev/null", check=False
            ).stdout.split()
            log_files.extend(name for name in listing if name not in log_files)

    looker = threading.Thread(target=look_at_the_log_files, daemon=True)
    collector.start()
    looker.start()
    try:
        result = run_job(job, worker_node, RecordingReport())
    finally:
        stop.set()
        collector.join(timeout=10)
        looker.join(timeout=30)
        worker_node.observations.close(job)
    assert result["steps"] == steps
    print(f"log files of the runner seen on the node: {log_files}; {sum(len(json.dumps(frame)) for frame in collected)} bytes of frames")
    assert any(name != "0.log" for name in log_files), f"the kubelet rotated the runner's log at {CONTAINER_LOG_MAX_SIZE} while it was followed: {log_files}"
    timestamps = [frame["timestamp"] for frame in collected]
    assert timestamps == list(range(steps + 1)), f"every frame once and in order; {len(timestamps)} of {steps + 1} arrived"
    assert sum(len(json.dumps(frame)) for frame in collected) > 2 * 1024 * 1024, "more than two of the kubelet's log files"
    assert_nothing_left(k3d_cluster, worker_node)


def test_a_cancelled_run_leaves_no_pod_service_or_folder(k3d_cluster, k3d_worker_node, make_job, head_on_trajectories):
    worker_node = k3d_worker_node({JobType.SIMULATION: 1})
    job = kinematic_job(make_job, head_on_trajectories, "cancelled-1")
    observation = worker_node.observations.open(job)
    observation.request(True, 1.0)  # paced to real time: 120 s, far more than the test waits
    report = RecordingReport()
    cancel = threading.Event()
    outcome: Dict[str, BaseException] = {}

    def run() -> None:
        try:
            run_job(job, worker_node, report, cancel)
        except BaseException as error:  # the test thread reads it
            outcome["error"] = error

    thread = threading.Thread(target=run)
    thread.start()
    try:
        k3d_cluster.wait_for(lambda: "running the kinematic replay run" in report.messages(), timeout_s=300, what="the runner running")
    finally:
        cancel.set()
        thread.join(timeout=120)
        worker_node.observations.close(job)
    assert not thread.is_alive() and isinstance(outcome.get("error"), JobFailed), outcome
    assert "run finished" not in report.messages()
    assert_nothing_left(k3d_cluster, worker_node)


def test_a_run_whose_runner_fails_fails_the_job_with_the_runners_reason(k3d_cluster, k3d_worker_node, make_job, head_on_trajectories):
    """COLREGS constants that do not parse: the pod is created and the run steps, and its runner fails on the series the monitoring pool refused."""
    worker_node = k3d_worker_node({JobType.SIMULATION: 1, JobType.MONITORING_POST_HOC: 1})
    worker_node.pools.start([Subsystem.MONITORING])
    job = kinematic_job(make_job, head_on_trajectories, "failing-1", monitor="live", colregs_constraints_content="rules: [unclosed")
    report = RecordingReport()
    with pytest.raises(JobFailed) as failure:
        run_job(job, worker_node, report)
    assert str(failure.value).startswith("The run's series in the monitoring pool"), str(failure.value)
    assert "creating the run's pod" in report.messages(), "the runner ran and failed, with its result.json"
    assert_nothing_left(k3d_cluster, worker_node)


def test_the_subsystem_removes_the_runs_an_earlier_process_left_and_nothing_else(k3d_cluster, k3d_worker_node, make_job, head_on_trajectories):
    """What the subsystem's start does (simulation_service_main.remove_leftover_stacks), run in the pool's own container with its account and its runtime folder."""
    worker_node = k3d_worker_node({JobType.SIMULATION: 1})
    run_job(kinematic_job(make_job, head_on_trajectories, "warm-1"), worker_node, RecordingReport())  # the pool is up
    assert_nothing_left(k3d_cluster, worker_node)  # the warm-up run's pod has gone through its grace period
    w = worker_node.worker_node_id
    labels = {WORKER_NODE_LABEL: w, "scenegems.instance": "left-1", RUN_COMPONENT_LABEL: RUN_COMPONENT}
    image = k3d_cluster.images()["SIMULATION_IMAGE"]
    k3d_cluster.apply(
        [
            {
                "apiVersion": "v1",
                "kind": "Pod",
                "metadata": {"name": f"{w}-simulation-subsystem-left1", "namespace": k3d_cluster.namespace, "labels": labels},
                "spec": {"containers": [{"name": RUNNER_SERVICE, "image": image, "imagePullPolicy": "IfNotPresent", "command": ["sleep", "600"]}], "terminationGracePeriodSeconds": 0},
            },
            {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": f"gcs-{w}-simulation-subsystem-left1-0", "namespace": k3d_cluster.namespace, "labels": labels},
                "spec": {"type": "NodePort", "selector": labels, "ports": [{"port": 12200}]},
            },
        ]
    )
    pool = worker_node.pools.get(Subsystem.SIMULATION)
    [pool_pod] = k3d_cluster.pods(",".join(f"{key}={value}" for key, value in pool.names.labels.items()))
    name = pool_pod["metadata"]["name"]
    instances = "/app/assets/runtime_assets/instances"
    k3d_cluster.kubectl_run("exec", "-n", k3d_cluster.namespace, name, "--", "mkdir", "-p", f"{instances}/{w}-simulation-subsystem-left1/job", f"{instances}/{w}-simulation-subsystem")
    script = (
        "import json, os; from scenegems_tool.subsystems.simulation import simulation_service_main as m; "
        "print(json.dumps(m.remove_leftover_stacks(m.cluster_api(), os.environ['SCENEGEMS_CONTROL_NODE_ID'], os.environ['SCENEGEMS_WORKER_NODE_ID'])))"
    )
    removed = json.loads(k3d_cluster.kubectl_run("exec", "-n", k3d_cluster.namespace, name, "--", "python", "-c", script).stdout.strip().splitlines()[-1])
    assert removed == [f"{w}-simulation-subsystem-left1"]
    assert_nothing_left(k3d_cluster, worker_node)
    assert k3d_cluster.pods(",".join(f"{key}={value}" for key, value in pool.names.labels.items())), "the pool's own pod stays"
    listing = k3d_cluster.kubectl_run("exec", "-n", k3d_cluster.namespace, name, "--", "ls", instances).stdout.split()
    assert f"{w}-simulation-subsystem" in listing, "and its own folder"


def test_the_simulation_subsystems_service_account_has_exactly_the_rights_its_runs_need(k3d_cluster):
    allowed = [
        ("create", "pods"),
        ("get", "pods"),
        ("list", "pods"),
        ("delete", "pods"),
        ("get", "pods/log"),
        ("create", "services"),
        ("get", "services"),
        ("list", "services"),
        ("update", "services"),
        ("delete", "services"),
    ]
    denied = [("watch", "pods"), ("update", "pods"), ("patch", "pods"), ("create", "pods/exec"), ("create", "deployments"), ("get", "secrets"), ("get", "configmaps"), ("get", "nodes")]
    assert [right for right in allowed if not k3d_cluster.can_i("simulation-subsystem", *right)] == []
    assert [right for right in denied if k3d_cluster.can_i("simulation-subsystem", *right)] == []
    assert not k3d_cluster.can_i("simulation-subsystem", "create", "pods", namespace="default"), "its namespace only"


# A run with SITL: the first time SITL, its sidecars and the runner share one network namespace


@pytest.fixture(scope="module")
def sitl_image(k3d_cluster):
    """ArduPilot SITL of the tag, about 6 GB, imported into the cluster."""
    image = f"scenegems-ardupilot-sitl:{k3d_cluster.image_tag}"
    k3d_cluster.import_images([image])
    previous = os.environ.get("SITL_IMAGE")
    os.environ["SITL_IMAGE"] = image
    yield image
    if previous is None:
        os.environ.pop("SITL_IMAGE", None)
    else:
        os.environ["SITL_IMAGE"] = previous


@pytest.mark.slow
def test_an_ardupilot_sim_replay_runs_sitl_and_its_replay_in_one_pod(k3d_cluster, k3d_worker_node, sitl_image, make_job):
    worker_node = k3d_worker_node({JobType.SIMULATION: 1})
    scene = ConcreteScene({_vessel(0, True): ActorState(0.0, 0.0, 5.0, math.pi / 2), _vessel(1, False): ActorState(0.0, 1000.0, 5.0, math.pi / 2)})
    trajectories = TrajectoryBuilder.default_trajectory_from_scene(scene, 1, 30)
    job = make_job(
        JobType.SIMULATION, {"runner": "ardupilot", "simulation_layer": "ardupilot_sim", "trajectories": trajectories.to_dict(), "geofence": GEOFENCE, "include_trajectories": False}, job_id="sitl-1"
    )
    report = RecordingReport()
    with RunPods(k3d_cluster, worker_node.worker_node_id) as pods:
        result = run_job(job, worker_node, report)
    [pod] = pods.seen.values()
    assert {container["name"] for container in pod["spec"]["initContainers"]} == {"os", "os-asv-system", "ts1", "ts1-asv-system"}
    assert result["steps"] > 0 and result["state_digest"], sorted(result)
    assert_nothing_left(k3d_cluster, worker_node)
