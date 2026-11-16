import itertools
import math
import os
import random
import uuid
from typing import Callable, Dict, Iterator, List, Optional

import pytest

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.cluster.protocol.jobs import JobSpec, JobType
from scenegems_tool.cluster.worker_node.instance_scope import daemon_deployment_name
from scenegems_tool.cluster.worker_node.launchers.kubernetes_api import ClusterPlace, Kind, KubernetesApi
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext
from scenegems_tool.messaging.mqtt_client import CLUSTER_TOPIC_ROOT, MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from tests.scenegems_tool.cluster.worker_node.fake_kubernetes import FakeCluster
from tests.scenegems_tool.cluster.worker_node.k3d_cluster import BROKER, K3dCluster, K3dUnavailable, start_test_cluster


def _vessel(vessel_id: int, is_os: bool, length: float = 30.0) -> ConcreteActor:
    return ConcreteActor.from_dict(
        {
            "id": vessel_id,
            "type": "OSPassengerShip" if is_os else "PassengerShip",
            "length": length,
            "breadth": length / 3,
            "safety_radius": 4 * length,
            "is_vessel": True,
            "_is_os": is_os,
            "_max_speed": 20.57778,
            "_max_angular_speed": 0.05,
            "_max_acceleration": 0.4,
        }
    )


@pytest.fixture
def head_on_trajectories() -> Trajectories:
    """Two vessels on reciprocal straight courses, 3 km apart, 120 s at 1 s steps."""
    scene = ConcreteScene({_vessel(0, True): ActorState(0.0, 0.0, 8.0, 0.0), _vessel(1, False): ActorState(3000.0, 0.0, 8.0, math.pi)})
    return TrajectoryBuilder.default_trajectory_from_scene(scene, 1, 120)


@pytest.fixture
def worker_node() -> WorkerNodeContext:
    return WorkerNodeContext(
        control_node_id="m1",
        worker_node_id="n1",
        mqtt_connection=MQttConnectionInfo("worker-node", "secret", "broker", "localhost", 1883, False, False),
        reference_geofence=Geofence(57.7, 11.9, 2000.0),
        slots={JobType.SCENE_GENERATION: 3, JobType.SIMULATION: 2},
    )


@pytest.fixture
def fake_cluster() -> FakeCluster:
    """A fake cluster API holding the Deployment of worker node n1's daemon, which owns its pools."""
    cluster = FakeCluster()
    cluster.add(Kind.DEPLOYMENT, {"metadata": {"name": "worker-node-n1", "labels": {"app.kubernetes.io/name": "worker-node"}}})
    return cluster


@pytest.fixture
def cluster_place(fake_cluster) -> ClusterPlace:
    """Worker node n1's place in the fake cluster, owned by its daemon's Deployment."""
    return ClusterPlace("scenegems", "k3d-lab-agent-0", "/var/lib/scenegems/n1/runtime", fake_cluster.api().owner_reference("worker-node-n1"))


@pytest.fixture
def placed_worker_node(fake_cluster, cluster_place) -> WorkerNodeContext:
    """Worker node n1 of control node m1 with its place in the fake cluster, so it can start pools."""
    return WorkerNodeContext(
        control_node_id="m1",
        worker_node_id="n1",
        mqtt_connection=MQttConnectionInfo("", "", "cluster-broker", "cluster-broker", 1883, False, False, topic_root="scenegems"),
        reference_geofence=Geofence(57.7, 11.9, 2000.0),
        slots={JobType.SCENE_GENERATION: 3, JobType.SIMULATION: 2},
        cluster=cluster_place,
        kubernetes=fake_cluster.api(),
    )


# A real cluster (tests marked kubernetes): k3d_cluster.py


@pytest.fixture(scope="session")
def k3d_cluster() -> Iterator[K3dCluster]:
    """The run's k3d cluster with the namespace, the rights, the broker and the images; it fails clearly when k3d, kubectl or an image is missing."""
    try:
        cluster = start_test_cluster()
    except K3dUnavailable as error:
        pytest.fail(str(error), pytrace=False)
    yield cluster
    cluster.stop()


@pytest.fixture(scope="session")
def k3d_images(k3d_cluster) -> Iterator[Dict[str, str]]:
    """The pools run the images imported into the cluster: their tag, as the daemon is given them (workerNodeImages)."""
    images = {variable: image for variable, image in k3d_cluster.images().items() if variable.endswith("_IMAGE")}
    previous = {variable: os.environ.get(variable) for variable in images}
    os.environ.update(images)
    yield images
    for variable, value in previous.items():
        if value is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = value


_instance_numbers = itertools.count(random.randint(100, 800))


@pytest.fixture
def k3d_worker_node(k3d_cluster, k3d_images) -> Iterator[Callable[..., WorkerNodeContext]]:
    """make(slots) is a worker node in the cluster as its daemon has it after the Welcome: its Deployment owns its pools, its
    launcher talks to the cluster as the daemon's service account, and its instance number is the test's own, so no pool of
    an earlier test answers on the broker. Its pools are deleted at the end, and its Deployment."""
    made: List[WorkerNodeContext] = []

    def make(slots: Dict[JobType, int], worker_node_id: Optional[str] = None) -> WorkerNodeContext:
        worker_node_id = worker_node_id or f"k3-{uuid.uuid4().hex[:6]}"
        owner = daemon_deployment_name(worker_node_id)
        k3d_cluster.apply([daemon_stand_in(owner, k3d_cluster.namespace, k3d_cluster.images()["WORKER_NODE"])])
        api = KubernetesApi.connect(k3d_cluster.namespace, kubeconfig=str(k3d_cluster.worker_node_kubeconfig))
        place = ClusterPlace(k3d_cluster.namespace, k3d_cluster.node, f"/var/lib/scenegems/{worker_node_id}/runtime", api.owner_reference(owner))
        connection = MQttConnectionInfo("", "", BROKER, "127.0.0.1", k3d_cluster.broker_port, False, False, topic_root=CLUSTER_TOPIC_ROOT)
        worker_node = WorkerNodeContext(
            control_node_id="k3d",
            worker_node_id=worker_node_id,
            mqtt_connection=connection,
            reference_geofence=Geofence(57.7, 11.9, 2000.0),
            slots=dict(slots),
            cluster=place,
            kubernetes=api,
        )
        worker_node.set_instance_number(next(_instance_numbers))
        made.append(worker_node)
        return worker_node

    yield make
    for worker_node in made:
        worker_node.shutdown()
        k3d_cluster.kubectl_run("delete", "deployment", daemon_deployment_name(worker_node.worker_node_id), "-n", k3d_cluster.namespace, "--ignore-not-found", "--wait=false", check=False)


def daemon_stand_in(name: str, namespace: str, image: str) -> dict:
    """The daemon's Deployment as the owner of a worker node's pools; no replica, since the launcher runs in the test process."""
    labels = {"app.kubernetes.io/name": "worker-node", "app.kubernetes.io/instance": name}
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": namespace, "labels": labels},
        "spec": {"replicas": 0, "selector": {"matchLabels": labels}, "template": {"metadata": {"labels": labels}, "spec": {"containers": [{"name": "daemon", "image": image}]}}},
    }


@pytest.fixture
def make_job():
    """Build a leased job of a type with a payload."""

    def make(job_type: JobType, payload: dict, job_id: str = "job-1", attempt: int = 1) -> JobSpec:
        return JobSpec(job_id=job_id, job_type=job_type, payload=payload, attempt=attempt, idempotency_key=f"{job_id}/key")

    return make
