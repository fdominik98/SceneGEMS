from scenegems_tool.cluster.node.daemon import node_runtime
from scenegems_tool.cluster.node.daemon.configuration.node_configuration import NodeConfiguration
from scenegems_tool.cluster.node.daemon.node_runtime import broker_connection, build_node_context, instance_prefix, remove_leftover_instances
from scenegems_tool.cluster.node.instance_scope import InstanceScope
from scenegems_tool.cluster.node.subsystem import Subsystem
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.messaging.mqtt_client import mqtt_container_environment


def configuration(tmp_path, **changes) -> NodeConfiguration:
    values = {
        "SCENEGEMS_MASTER_URL": "http://192.168.1.10:8443",
        "SCENEGEMS_MASTER_ID": "lab-master",
        "SCENEGEMS_NODE_NAME": "worker-1",
        "SCENEGEMS_NODE_SLOTS": "scene_generation:3,simulation:2",
        "SCENEGEMS_NODE_COMPONENTS": "asv_software/replay,control_layer/none,simulation_layer/kinematic,scene_generation",
        "SCENEGEMS_NODE_STATE_DIR": str(tmp_path / "state"),
        "SCENEGEMS_DOCKER_NETWORK": "scenegems-node-lab-master-worker-1",
        "SCENEGEMS_NODE_REFERENCE_GEOFENCE": "57.7,11.9,2000",
    }
    values.update(changes)
    return NodeConfiguration.from_values(values)


def test_the_broker_is_the_masters_plain_anonymous_one_on_its_host(tmp_path):
    connection = broker_connection(configuration(tmp_path))
    assert (connection.user, connection.password) == ("", "")
    assert connection.client_broker == connection.agent_broker == "192.168.1.10" and connection.port == 1883
    assert not connection.tls_connection and connection.ca_certificate_path is None
    assert connection.topic_prefix == ""  # every instance adds its own
    assert broker_connection(configuration(tmp_path, SCENEGEMS_BROKER_PORT="11883")).port == 11883


def test_the_node_context_carries_ids_slots_and_network(tmp_path):
    node = build_node_context(configuration(tmp_path))
    assert (node.master_id, node.node_id) == ("lab-master", "worker-1")
    assert node.slots == {JobType.SCENE_GENERATION: 3, JobType.SIMULATION: 2}
    assert node.pool_workers(Subsystem.SCENE_GENERATION) == 3
    assert node.broker_network == "scenegems-node-lab-master-worker-1"
    assert (node.reference_geofence.latitude, node.reference_geofence.radius_meters) == (57.7, 2000.0)
    # Pool instances live under the node's own topic scope on the master's broker.
    assert node.pools.scope(Subsystem.SCENE_GENERATION).topic_prefix.startswith("scenegems/lab-master/worker-1/")


def test_the_node_context_moves_artifacts_over_the_node_api_with_a_cache_in_the_state_folder(tmp_path):
    node = build_node_context(configuration(tmp_path, SCENEGEMS_NODE_ARTIFACT_CACHE_MAX_BYTES="1000"))
    assert node.artifacts.client.master_url == "http://192.168.1.10:8443"
    assert node.artifacts.cache.folder == tmp_path / "state" / "artifacts" and node.artifacts.cache.max_bytes == 1000
    assert build_node_context(configuration(tmp_path, SCENEGEMS_NODE_ARTIFACT_CACHE_MAX_BYTES="0")).artifacts.cache is None


def test_pool_containers_dial_the_plain_broker_with_no_account_and_no_certificate(tmp_path, monkeypatch):
    from scenegems_tool.cluster.node.launchers.pooled.pooled_service import PooledService

    monkeypatch.setattr(PooledService, "_run_container_lifecycle_startup", lambda self, compose: None)
    node = build_node_context(configuration(tmp_path))
    pool = node.pools.get(Subsystem.SCENE_GENERATION)
    compose = pool.build_compose()
    service = compose["services"]["scene_generation"]
    assert service["environment"]["MQTT_TLS"] == "0" and service["environment"]["MQTT_USER"] == "" and service["environment"]["MQTT_BROKER"] == "192.168.1.10"
    assert "MQTT_CA_CERTIFICATE" not in service["environment"] and not service.get("volumes")
    assert "MQTT_CA_CERTIFICATE" not in mqtt_container_environment(node.mqtt_connection)
    node.shutdown()


def test_leftover_instances_of_this_node_are_removed(tmp_path, monkeypatch):
    removed = []

    class RecordingProject:
        def __init__(self, name, compose_filename):
            self.name = name

        def force_remove(self, networks=False):
            removed.append((self.name, networks))

    monkeypatch.setattr(node_runtime, "ComposeProject", RecordingProject)
    instances = tmp_path / "instances"
    mine = InstanceScope.per_job("lab-master", "worker-1", "job-7-1").docker_name
    pool = InstanceScope.pooled("lab-master", "worker-1", "scene_generation").docker_name
    other_node = InstanceScope.per_job("lab-master", "worker-2", "job-8-1").docker_name
    for name in (mine, pool, other_node):
        (instances / name).mkdir(parents=True)

    assert remove_leftover_instances("lab-master", "worker-1", str(instances)) == sorted([mine, pool])
    assert sorted(removed) == sorted([(mine, True), (pool, True)])
    assert [folder.name for folder in instances.iterdir()] == [other_node]
    assert remove_leftover_instances("lab-master", "worker-1", str(tmp_path / "missing")) == []
    assert instance_prefix("lab-master", "worker-1") == "scenegems-lab-master-worker-1-"
