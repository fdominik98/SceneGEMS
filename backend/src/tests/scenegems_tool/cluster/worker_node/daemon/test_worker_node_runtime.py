import pytest

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.daemon.configuration.worker_node_configuration import WorkerNodeConfiguration
from scenegems_tool.cluster.worker_node.daemon.worker_node_runtime import broker_connection, build_worker_node_context, leftover_selector, remove_leftover_instances
from scenegems_tool.cluster.worker_node.instance_scope import INSTANCE_LABEL, WORKER_NODE_LABEL, InstanceScope
from scenegems_tool.cluster.worker_node.launchers.kubernetes_api import Kind
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.messaging.mqtt_client import mqtt_container_environment
from tests.scenegems_tool.cluster.worker_node.fake_kubernetes import FakeCluster


def configuration(tmp_path, **changes) -> WorkerNodeConfiguration:
    values = {
        "SCENEGEMS_CONTROL_NODE_URL": "http://192.168.1.10:8443",
        "SCENEGEMS_CONTROL_NODE_ID": "lab-control-node",
        "SCENEGEMS_WORKER_NODE_NAME": "worker-1",
        "SCENEGEMS_WORKER_NODE_SLOTS": "scene_generation:3,simulation:2",
        "SCENEGEMS_WORKER_NODE_COMPONENTS": "asv_system/replay,control_layer/none,simulation_layer/kinematic,scene_generation",
        "SCENEGEMS_WORKER_NODE_STATE_DIR": str(tmp_path / "state"),
        "SCENEGEMS_WORKER_NODE_REFERENCE_GEOFENCE": "57.7,11.9,2000",
        "SCENEGEMS_KUBERNETES_NAMESPACE": "scenegems",
        "SCENEGEMS_KUBERNETES_NODE": "lab-pc-2",
        "SCENEGEMS_RUNTIME_HOST_PATH": "/var/lib/scenegems/worker-1/runtime",
        "SCENEGEMS_RELEASE_MANIFEST": str(tmp_path / "release.json"),
    }
    values.update(changes)
    return WorkerNodeConfiguration.from_values(values)


@pytest.fixture
def cluster() -> FakeCluster:
    """The namespace with the Deployment of worker-1's daemon, which the chart names worker-node-worker-1."""
    made = FakeCluster()
    made.add(Kind.DEPLOYMENT, {"metadata": {"name": "worker-node-worker-1", "labels": {"app.kubernetes.io/name": "worker-node", WORKER_NODE_LABEL: "worker-1"}}})
    return made


def test_the_broker_is_the_control_nodes_plain_anonymous_one_on_its_host(tmp_path):
    connection = broker_connection(configuration(tmp_path))
    assert (connection.user, connection.password) == ("", "")
    assert connection.client_broker == connection.agent_broker == "192.168.1.10" and connection.port == 1883
    assert not connection.tls_connection and connection.ca_certificate_path is None
    assert connection.topic_root == "scenegems", "the first level of the cluster's topics; a name tells its services apart"
    assert broker_connection(configuration(tmp_path, SCENEGEMS_BROKER_PORT="11883")).port == 11883


def test_in_the_cluster_the_broker_is_its_service(tmp_path):
    connection = broker_connection(configuration(tmp_path, SCENEGEMS_BROKER_HOST="cluster-broker"))
    assert connection.client_broker == connection.agent_broker == "cluster-broker", "the daemon and its pools dial the same service"


def test_the_worker_node_context_carries_ids_slots_and_its_place_in_the_cluster(tmp_path, cluster):
    worker_node = build_worker_node_context(configuration(tmp_path), cluster.api())
    assert (worker_node.control_node_id, worker_node.worker_node_id) == ("lab-control-node", "worker-1")
    assert worker_node.slots == {JobType.SCENE_GENERATION: 3, JobType.SIMULATION: 2}
    assert worker_node.pool_workers(Subsystem.SCENE_GENERATION) == 3
    assert (worker_node.reference_geofence.latitude, worker_node.reference_geofence.radius_meters) == (57.7, 2000.0)
    place = worker_node.cluster
    assert (place.namespace, place.node, place.runtime_host_path) == ("scenegems", "lab-pc-2", "/var/lib/scenegems/worker-1/runtime")
    assert place.owner.name == "worker-node-worker-1" and place.owner.uid == cluster.get(Kind.DEPLOYMENT, "worker-node-worker-1")["metadata"]["uid"], "the pools go with the worker node"
    assert worker_node.kubernetes.namespace == "scenegems"
    # A pool is named after its subsystem in the cluster, and on the broker by the number the control node gave the worker node.
    assert worker_node.pools.scope(Subsystem.SCENE_GENERATION).name == "worker-1-scene-generation-subsystem"
    assert worker_node.pools.service_name(Subsystem.SCENE_GENERATION) == "scene-generation-subsystem-1"
    worker_node.set_instance_number(4)
    assert worker_node.pools.service_name(Subsystem.TRAJECTORY_GENERATION) == "trajectory-generation-subsystem-4"


def test_a_daemon_without_its_deployment_does_not_start(tmp_path):
    """The owner is the daemon's Deployment; without it the pools would outlive the worker node."""
    with pytest.raises(RuntimeError, match="worker-node-worker-1"):
        build_worker_node_context(configuration(tmp_path), FakeCluster().api())


def test_the_worker_node_context_moves_artifacts_over_the_worker_node_api_with_a_cache_in_the_state_folder(tmp_path, cluster):
    worker_node = build_worker_node_context(configuration(tmp_path, SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_MAX_BYTES="1000"), cluster.api())
    assert worker_node.artifacts.client.control_node_url == "http://192.168.1.10:8443"
    assert worker_node.artifacts.cache.folder == tmp_path / "state" / "artifacts" and worker_node.artifacts.cache.max_bytes == 1000
    assert build_worker_node_context(configuration(tmp_path, SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_MAX_BYTES="0"), cluster.api()).artifacts.cache is None


def test_pools_dial_the_plain_broker_with_no_account_and_no_certificate(tmp_path, cluster):
    worker_node = build_worker_node_context(configuration(tmp_path, SCENEGEMS_BROKER_HOST="cluster-broker"), cluster.api())
    pool = worker_node.pools.get(Subsystem.SCENE_GENERATION)  # the folder's pools_without_docker keeps it from the cluster
    deployment = pool.build_deployment()
    assert deployment["metadata"]["name"] == "worker-1-scene-generation-subsystem"
    environment = {entry["name"]: entry["value"] for entry in deployment["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert environment["MQTT_TOPIC_ROOT"] == "scenegems" and environment["MQTT_SERVICE_NAME"] == "scene-generation-subsystem-1"
    assert pool.service_topic == "scenegems/service/virtual/real/scene-generation-subsystem-1", "the job's client and the pod agree on it"
    assert environment["MQTT_TLS"] == "0" and environment["MQTT_USER"] == "" and environment["MQTT_BROKER"] == "cluster-broker"
    assert "MQTT_CA_CERTIFICATE" not in environment and "volumes" not in deployment["spec"]["template"]["spec"]
    assert "MQTT_CA_CERTIFICATE" not in mqtt_container_environment(worker_node.mqtt_connection)
    assert deployment["metadata"]["ownerReferences"][0]["name"] == "worker-node-worker-1"
    assert deployment["spec"]["template"]["spec"]["nodeSelector"] == {"kubernetes.io/hostname": "lab-pc-2"}
    worker_node.shutdown()


def labelled(scope: InstanceScope) -> dict:
    return {"metadata": {"name": scope.name, "labels": dict(scope.labels)}}


def test_leftover_instances_of_this_worker_node_are_removed(tmp_path, cluster):
    pool = InstanceScope.pooled("lab-control-node", "worker-1", "scene_generation")
    run = InstanceScope.per_job("lab-control-node", "worker-1", "simulation", "job-7")
    other_worker_node = InstanceScope.per_job("lab-control-node", "worker-2", "simulation", "job-8")
    cluster.add(Kind.DEPLOYMENT, labelled(pool))
    cluster.add(Kind.POD, {"metadata": {"name": f"{pool.name}-7d9f8-x2x4z", "labels": dict(pool.labels)}})  # the pool's pod
    cluster.add(Kind.POD, labelled(run))
    cluster.add(Kind.SERVICE, {"metadata": {"name": f"{run.name}-gcs-0", "labels": dict(run.labels)}})  # a ground control port of an attended run
    cluster.add(Kind.DEPLOYMENT, labelled(other_worker_node))
    cluster.add(Kind.POD, {"metadata": {"name": "worker-node-worker-1-5c64e-abcde", "labels": {WORKER_NODE_LABEL: "worker-1"}}})  # the daemon's own pod: no instance label
    instances = tmp_path / "instances"
    for name in (run.name, f"{run.name}-2", other_worker_node.name, "worker-1-b-simulation-subsystem-job-9"):
        (instances / name).mkdir(parents=True)
    (instances / "worker-1-notes.txt").write_text("not a folder", encoding="utf-8")

    removed = remove_leftover_instances(cluster.api(), "worker-1", str(instances))
    assert removed == [
        f"Deployment {pool.name}",
        f"Pod {pool.name}-7d9f8-x2x4z",
        f"Pod {run.name}",
        f"Service {run.name}-gcs-0",
        f"folder {run.name}",
        f"folder {run.name}-2",
    ]
    assert cluster.names(Kind.DEPLOYMENT) == sorted(["worker-node-worker-1", other_worker_node.name]), "its own Deployment and another worker node's stay"
    assert cluster.names(Kind.POD) == ["worker-node-worker-1-5c64e-abcde"] and cluster.names(Kind.SERVICE) == []
    assert sorted(entry.name for entry in instances.iterdir()) == sorted(
        [other_worker_node.name, "worker-1-b-simulation-subsystem-job-9", "worker-1-notes.txt"]
    ), "worker node worker-1-b's is not worker-1's"
    assert all(deletion["propagation_policy"] == "Background" for deletion in cluster.deletions)
    assert remove_leftover_instances(cluster.api(), "worker-1", str(tmp_path / "missing")) == []


def test_the_leftover_selector_is_the_worker_node_with_any_instance():
    assert leftover_selector("worker-1") == f"{WORKER_NODE_LABEL}=worker-1,{INSTANCE_LABEL}"
