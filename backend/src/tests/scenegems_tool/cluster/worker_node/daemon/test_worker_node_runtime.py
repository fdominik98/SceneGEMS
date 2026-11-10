from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.daemon import worker_node_runtime
from scenegems_tool.cluster.worker_node.daemon.configuration.worker_node_configuration import WorkerNodeConfiguration
from scenegems_tool.cluster.worker_node.daemon.worker_node_runtime import broker_connection, build_worker_node_context, instance_prefix, remove_leftover_instances
from scenegems_tool.cluster.worker_node.instance_scope import InstanceScope
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.messaging.mqtt_client import mqtt_container_environment


def configuration(tmp_path, **changes) -> WorkerNodeConfiguration:
    values = {
        "SCENEGEMS_CONTROL_NODE_URL": "http://192.168.1.10:8443",
        "SCENEGEMS_CONTROL_NODE_ID": "lab-control-node",
        "SCENEGEMS_WORKER_NODE_NAME": "worker-1",
        "SCENEGEMS_WORKER_NODE_SLOTS": "scene_generation:3,simulation:2",
        "SCENEGEMS_WORKER_NODE_COMPONENTS": "asv_software/replay,control_layer/none,simulation_layer/kinematic,scene_generation",
        "SCENEGEMS_WORKER_NODE_STATE_DIR": str(tmp_path / "state"),
        "SCENEGEMS_DOCKER_NETWORK": "scenegems-worker-node-lab-control-node-worker-1",
        "SCENEGEMS_WORKER_NODE_REFERENCE_GEOFENCE": "57.7,11.9,2000",
    }
    values.update(changes)
    return WorkerNodeConfiguration.from_values(values)


def test_the_broker_is_the_control_nodes_plain_anonymous_one_on_its_host(tmp_path):
    connection = broker_connection(configuration(tmp_path))
    assert (connection.user, connection.password) == ("", "")
    assert connection.client_broker == connection.agent_broker == "192.168.1.10" and connection.port == 1883
    assert not connection.tls_connection and connection.ca_certificate_path is None
    assert connection.topic_prefix == ""  # every instance adds its own
    assert broker_connection(configuration(tmp_path, SCENEGEMS_BROKER_PORT="11883")).port == 11883


def test_the_worker_node_context_carries_ids_slots_and_network(tmp_path):
    worker_node = build_worker_node_context(configuration(tmp_path))
    assert (worker_node.control_node_id, worker_node.worker_node_id) == ("lab-control-node", "worker-1")
    assert worker_node.slots == {JobType.SCENE_GENERATION: 3, JobType.SIMULATION: 2}
    assert worker_node.pool_workers(Subsystem.SCENE_GENERATION) == 3
    assert worker_node.broker_network == "scenegems-worker-node-lab-control-node-worker-1"
    assert (worker_node.reference_geofence.latitude, worker_node.reference_geofence.radius_meters) == (57.7, 2000.0)
    # Pool instances live under the worker node's own topic scope on the control node's broker.
    assert worker_node.pools.scope(Subsystem.SCENE_GENERATION).topic_prefix.startswith("scenegems/lab-control-node/worker-1/")


def test_the_worker_node_context_moves_artifacts_over_the_worker_node_api_with_a_cache_in_the_state_folder(tmp_path):
    worker_node = build_worker_node_context(configuration(tmp_path, SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_MAX_BYTES="1000"))
    assert worker_node.artifacts.client.control_node_url == "http://192.168.1.10:8443"
    assert worker_node.artifacts.cache.folder == tmp_path / "state" / "artifacts" and worker_node.artifacts.cache.max_bytes == 1000
    assert build_worker_node_context(configuration(tmp_path, SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_MAX_BYTES="0")).artifacts.cache is None


def test_pool_containers_dial_the_plain_broker_with_no_account_and_no_certificate(tmp_path, monkeypatch):
    from scenegems_tool.cluster.worker_node.launchers.pooled.pooled_service import PooledService

    monkeypatch.setattr(PooledService, "_run_container_lifecycle_startup", lambda self, compose: None)
    worker_node = build_worker_node_context(configuration(tmp_path))
    pool = worker_node.pools.get(Subsystem.SCENE_GENERATION)
    compose = pool.build_compose()
    service = compose["services"]["scene_generation"]
    assert service["environment"]["MQTT_TLS"] == "0" and service["environment"]["MQTT_USER"] == "" and service["environment"]["MQTT_BROKER"] == "192.168.1.10"
    assert "MQTT_CA_CERTIFICATE" not in service["environment"] and not service.get("volumes")
    assert "MQTT_CA_CERTIFICATE" not in mqtt_container_environment(worker_node.mqtt_connection)
    worker_node.shutdown()


def test_leftover_instances_of_this_worker_node_are_removed(tmp_path, monkeypatch):
    removed = []

    class RecordingProject:
        def __init__(self, name, compose_filename):
            self.name = name

        def force_remove(self, networks=False):
            removed.append((self.name, networks))

    monkeypatch.setattr(worker_node_runtime, "ComposeProject", RecordingProject)
    instances = tmp_path / "instances"
    mine = InstanceScope.per_job("lab-control-node", "worker-1", "job-7-1").docker_name
    pool = InstanceScope.pooled("lab-control-node", "worker-1", "scene_generation").docker_name
    other_worker_node = InstanceScope.per_job("lab-control-node", "worker-2", "job-8-1").docker_name
    for name in (mine, pool, other_worker_node):
        (instances / name).mkdir(parents=True)

    assert remove_leftover_instances("lab-control-node", "worker-1", str(instances)) == sorted([mine, pool])
    assert sorted(removed) == sorted([(mine, True), (pool, True)])
    assert [folder.name for folder in instances.iterdir()] == [other_worker_node]
    assert remove_leftover_instances("lab-control-node", "worker-1", str(tmp_path / "missing")) == []
    assert instance_prefix("lab-control-node", "worker-1") == "scenegems-lab-control-node-worker-1-"
