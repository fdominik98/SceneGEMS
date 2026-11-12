"""Compose content of a worker node's pooled services: each is named by its scope and found by its label in the worker node's project."""

import pytest

from scenegems_tool.cluster.worker_node.instance_scope import INSTANCE_LABEL, InstanceScope
from scenegems_tool.cluster.worker_node.launchers.pooled import pooled_service
from scenegems_tool.cluster.worker_node.launchers.pooled.design_space_exploration_pool import DesignSpaceExplorationPool
from scenegems_tool.cluster.worker_node.launchers.pooled.monitoring_pool import MonitoringPool
from scenegems_tool.cluster.worker_node.launchers.pooled.scene_generation_pool import SceneGenerationPool
from scenegems_tool.cluster.worker_node.launchers.pooled.service_pools import ServicePools
from scenegems_tool.cluster.worker_node.launchers.pooled.simulation_pool import SimulationPool, image_overrides
from scenegems_tool.cluster.worker_node.launchers.pooled.trajectory_generation_pool import TrajectoryGenerationPool
from scenegems_tool.cluster.worker_node.subsystem import Subsystem


def test_scoped_pool_is_sized_by_slots_and_named_by_scope(no_docker, mqtt_connection, geofence):
    scope = InstanceScope.pooled("m1", "n1", "scene_generation")
    cluster_broker = mqtt_connection.with_topic_root("scenegems")
    pool = SceneGenerationPool.for_scope(scope, cluster_broker, geofence, workers=3, broker_network="worker_node_broker_net", service_name="scene-generation-subsystem-2")
    compose = pool.labelled(pool.build_compose())
    service = compose["services"]["scene-generation-subsystem"]
    assert (service["container_name"], service["hostname"]) == ("scenegems-m1-n1-scene-generation-subsystem", "scene-generation-subsystem")
    assert service["labels"] == {INSTANCE_LABEL: "scene-generation-subsystem"}, "what the pool is removed by in the worker node's project"
    assert service["cpus"] == 4
    assert service["environment"]["WORKER_COUNT"] == "3"
    assert "MQTT_TOPIC_PREFIX" not in service["environment"], "no level for the worker node or the instance"
    assert service["environment"]["MQTT_TOPIC_ROOT"] == "scenegems" and service["environment"]["MQTT_SERVICE_NAME"] == "scene-generation-subsystem-2"
    assert compose["networks"]["scene_generation_net"] == {"name": "scenegems-m1-n1-scene-generation-subsystem-net", "driver": "bridge", "labels": {INSTANCE_LABEL: "scene-generation-subsystem"}}
    assert compose["networks"]["scenegems_broker"] == {"external": True, "name": "worker_node_broker_net"}
    assert pool.project.name == scope.compose_project == "scenegems-m1-n1" and pool.project.instance == scope.key
    assert pool.project.compose_filename == f"{scope.folder}/docker-compose.yml"
    # Clients of the pool address it by the name and the topic its container was given.
    assert (pool.service_name, pool.service_topic) == ("scene-generation-subsystem-2", "scenegems/service/virtual/real/scene-generation-subsystem-2")
    assert pool.mqtt_connection is cluster_broker, "the connection as it was given: nothing is put in front of its topics"


def test_a_pool_on_its_own_keeps_the_subsystems_name_on_a_waraps_topic(no_docker, mqtt_connection, geofence):
    pool = SceneGenerationPool.for_scope(InstanceScope.pooled("m1", "n1", "scene_generation"), mqtt_connection, geofence, workers=1)
    assert (pool.service_name, pool.service_topic) == ("scene-generation-subsystem", "waraps/service/virtual/real/scene-generation-subsystem")
    environment = pool.build_compose()["services"]["scene-generation-subsystem"]["environment"]
    assert environment["MQTT_SERVICE_NAME"] == "scene-generation-subsystem" and "MQTT_TOPIC_ROOT" not in environment


def test_two_scoped_pools_share_no_docker_name(no_docker, mqtt_connection, geofence):
    first = TrajectoryGenerationPool.for_scope(InstanceScope.pooled("m1", "n1", "trajectory_generation"), mqtt_connection, geofence, workers=1)
    second = TrajectoryGenerationPool.for_scope(InstanceScope.pooled("m1", "n2", "trajectory_generation"), mqtt_connection, geofence, workers=1)

    def names(pool):
        compose = pool.build_compose()
        service = compose["services"]["trajectory-generation-subsystem"]
        return {pool.project.name, service["container_name"], compose["networks"]["trajectory_generation_net"]["name"], pool.project.compose_filename}

    assert not names(first) & names(second)


@pytest.mark.parametrize(
    "pool_class, subsystem",
    [
        (DesignSpaceExplorationPool, "design_space_exploration"),
        (SceneGenerationPool, "scene_generation"),
        (TrajectoryGenerationPool, "trajectory_generation"),
        (MonitoringPool, "monitoring"),
        (SimulationPool, "simulation"),
    ],
)
def test_a_pool_s_hostname_fits_docker_s_limit_whatever_the_cluster_is_called(no_docker, mqtt_connection, geofence, pool_class, subsystem):
    """Docker refuses a hostname over 64 bytes: with the container name as hostname, a cluster called local-cluster lost two of its pools."""
    scope = InstanceScope.pooled("a-cluster-with-quite-a-long-name", "worker-node-12", subsystem)
    pool = pool_class.for_scope(scope, mqtt_connection, geofence, workers=1)
    service = pool.build_compose()["services"][scope.instance_id]
    assert len(service["container_name"]) > 64, "the case: a container name that is no hostname"
    assert service["hostname"] == scope.instance_id and len(service["hostname"]) <= 63


def test_image_override_applies_to_pools(no_docker, monkeypatch, mqtt_connection, geofence):
    monkeypatch.setenv("SCENE_GENERATION_IMAGE", "scenegems-scene-generation-subsystem:branch")
    pool = SceneGenerationPool.for_scope(InstanceScope.pooled("m1", "n1", "scene_generation"), mqtt_connection, geofence, workers=1, broker_network="worker_node_broker_net")
    assert pool.build_compose()["services"]["scene-generation-subsystem"]["image"] == "scenegems-scene-generation-subsystem:branch"


def test_the_monitoring_pool_is_sized_by_slots_and_named_by_scope(no_docker, mqtt_connection, geofence):
    scope = InstanceScope.pooled("m1", "n1", "monitoring")
    pool = MonitoringPool.for_scope(scope, mqtt_connection.with_topic_root("scenegems"), geofence, workers=2, broker_network="worker_node_broker_net", service_name="monitoring-subsystem-2")
    service = pool.labelled(pool.build_compose())["services"]["monitoring-subsystem"]
    assert (service["container_name"], service["hostname"]) == ("scenegems-m1-n1-monitoring-subsystem", "monitoring-subsystem")
    assert service["labels"] == {INSTANCE_LABEL: "monitoring-subsystem"} and service["cpus"] == 3, "a core per series it judges at once, and one for the service"
    environment = service["environment"]
    assert (environment["WORKER_COUNT"], environment["MQTT_SERVICE_NAME"], environment["MQTT_TOPIC_ROOT"]) == ("2", "monitoring-subsystem-2", "scenegems")
    # The COLREGS constants come with every request, and the name and the topic with the launcher's variables
    assert not {"MONITOR_AGENT_NAME", "MONITOR_TOPIC", "COLREGS_CONSTRAINTS_YAML_B64", "MQTT_TOPIC_PREFIX"} & set(environment)
    assert (pool.service_name, pool.service_topic) == ("monitoring-subsystem-2", "scenegems/service/virtual/real/monitoring-subsystem-2")
    assert pool.project.name == "scenegems-m1-n1" and pool.names.instance == scope.key, "in the worker node's project, found by its label"


def test_the_design_space_exploration_pool_is_sized_by_slots_and_reaches_the_broker(no_docker, mqtt_connection, geofence):
    scope = InstanceScope.pooled("m1", "n1", "design_space_exploration")
    pool = DesignSpaceExplorationPool.for_scope(
        scope, mqtt_connection.with_topic_root("scenegems"), geofence, workers=2, broker_network="worker_node_broker_net", service_name="design-space-exploration-subsystem-2"
    )
    compose = pool.labelled(pool.build_compose())
    service = compose["services"]["design-space-exploration-subsystem"]
    assert service["container_name"] == "scenegems-m1-n1-design-space-exploration-subsystem" and service["labels"] == {INSTANCE_LABEL: "design-space-exploration-subsystem"}
    assert service["cpus"] == 3, "a core per generator it runs at once, and one for the service"
    assert "command" not in service and "network_mode" not in service, "the image's own service, on the broker's network: the generator alone had none"
    assert "scenegems_broker" in service["networks"] and compose["networks"]["scenegems_broker"] == {"external": True, "name": "worker_node_broker_net"}
    assert (service["environment"]["WORKER_COUNT"], service["environment"]["MQTT_SERVICE_NAME"]) == (
        "2",
        "design-space-exploration-subsystem-2",
    ), "the pool size is also what the generators share the memory by"
    assert (pool.service_name, pool.service_topic) == ("design-space-exploration-subsystem-2", "scenegems/service/virtual/real/design-space-exploration-subsystem-2")
    assert DesignSpaceExplorationPool.default_service_name == "design-space-exploration-subsystem" and DesignSpaceExplorationPool.subsystem is Subsystem.DESIGN_SPACE_EXPLORATION


def test_the_simulation_pool_gets_what_it_needs_to_start_the_stacks_of_its_tasks(no_docker, monkeypatch, mqtt_connection, geofence):
    """The one pool that starts containers: the Docker socket, the runtime volume its stacks' files are on, and the names its stacks are built with."""
    monkeypatch.setenv("SITL_IMAGE", "scenegems-ardupilot-sitl:branch")
    monkeypatch.setenv("SCENEGEMS_IMAGE_TAG", "release-7")
    scope = InstanceScope.pooled("m1", "n1", "simulation")
    pool = SimulationPool.for_scope(scope, mqtt_connection.with_topic_root("scenegems"), geofence, workers=2, broker_network="scenegems-m1-n1", service_name="simulation-subsystem-2")
    compose = pool.labelled(pool.build_compose())
    service = compose["services"]["simulation-subsystem"]
    assert service["container_name"] == "scenegems-m1-n1-simulation-subsystem" and service["labels"] == {INSTANCE_LABEL: "simulation-subsystem"}
    assert service["image"].startswith("scenegems-simulation-subsystem:") and "command" not in service, "the image's own service"
    assert service["volumes"][0] == "/var/run/docker.sock:/var/run/docker.sock"
    volume, _, mounted_at = service["volumes"][1].partition(":")
    assert volume in compose["volumes"] and compose["volumes"][volume] == {"external": True}
    assert mounted_at == "/app/assets/runtime_assets", "where the image has the folder, also when the launcher runs from a Windows checkout"
    environment = service["environment"]
    assert (environment["SCENEGEMS_CONTROL_NODE_ID"], environment["SCENEGEMS_WORKER_NODE_ID"]) == ("m1", "n1"), "its stacks are named after the worker node, as the daemon named them"
    assert (environment["SCENEGEMS_DOCKER_NETWORK"], environment["SCENEGEMS_RUNTIME_VOLUME"]) == ("scenegems-m1-n1", volume)
    assert (environment["SITL_IMAGE"], environment["SCENEGEMS_IMAGE_TAG"]) == ("scenegems-ardupilot-sitl:branch", "release-7"), "its stacks run the images the daemon would have run"
    assert (environment["WORKER_COUNT"], environment["MQTT_SERVICE_NAME"], service["cpus"]) == ("2", "simulation-subsystem-2", 3)
    assert "scenegems_broker" in service["networks"]
    assert (pool.service_name, pool.service_topic) == ("simulation-subsystem-2", "scenegems/service/virtual/real/simulation-subsystem-2")


def test_only_set_image_overrides_and_the_tag_are_passed_on():
    environment = {"SITL_IMAGE": "sitl:branch", "GAZEBO_IMAGE": " ", "SCENEGEMS_IMAGE_TAG": "r7", "PATH": "/bin", "IMAGE_CACHE": "x"}
    assert image_overrides(environment) == {"SITL_IMAGE": "sitl:branch", "SCENEGEMS_IMAGE_TAG": "r7"}
    assert image_overrides({"PATH": "/bin"}) == {}


def test_a_monitoring_pool_on_its_own_keeps_the_subsystems_name():
    assert MonitoringPool.default_service_name == "monitoring-subsystem" and MonitoringPool.subsystem is Subsystem.MONITORING


# The pools of a worker node: started together, looked after, removed together


@pytest.fixture
def pools(no_docker, monkeypatch, mqtt_connection, geofence):
    """A worker node's pools without containers; pools.running says which containers are there, pools.destroyed which were removed."""
    made = ServicePools("m1", "n1", mqtt_connection, geofence, workers=lambda subsystem: 2, instance_number=lambda: 4)
    made.running = set()
    made.destroyed = []
    monkeypatch.setattr(pooled_service, "is_container_running", lambda name: name in made.running)
    monkeypatch.setattr(pooled_service.PooledService, "destroy", lambda self: made.destroyed.append(self.service_name))
    return made


def container_of(pool) -> str:
    return pool.names.container_name


def test_the_pools_of_the_subsystems_start_together_each_once(pools):
    pools.start([Subsystem.DESIGN_SPACE_EXPLORATION, Subsystem.SCENE_GENERATION, Subsystem.TRAJECTORY_GENERATION, Subsystem.MONITORING, Subsystem.SIMULATION])
    scene = pools.get(Subsystem.SCENE_GENERATION)
    assert scene.service_name == "scene-generation-subsystem-4" and scene.workers == 2
    assert pools.get(Subsystem.TRAJECTORY_GENERATION).service_name == "trajectory-generation-subsystem-4"
    monitoring = pools.get(Subsystem.MONITORING)
    assert isinstance(monitoring, MonitoringPool) and (monitoring.service_name, monitoring.workers) == ("monitoring-subsystem-4", 2)
    exploration = pools.get(Subsystem.DESIGN_SPACE_EXPLORATION)
    assert isinstance(exploration, DesignSpaceExplorationPool) and (exploration.service_name, exploration.workers) == ("design-space-exploration-subsystem-4", 2)
    simulation = pools.get(Subsystem.SIMULATION)
    assert isinstance(simulation, SimulationPool) and (simulation.service_name, simulation.workers, simulation.worker_node_id) == ("simulation-subsystem-4", 2, "n1")
    pools.start([Subsystem.SCENE_GENERATION])
    assert pools.get(Subsystem.SCENE_GENERATION) is scene, "a pool that is there is left alone"


def test_a_pool_whose_container_is_gone_is_started_again(pools):
    pools.start([Subsystem.SCENE_GENERATION, Subsystem.TRAJECTORY_GENERATION])
    scene, trajectory = pools.get(Subsystem.SCENE_GENERATION), pools.get(Subsystem.TRAJECTORY_GENERATION)
    pools.running = {container_of(scene)}
    assert pools.ensure_running() == [Subsystem.TRAJECTORY_GENERATION]
    assert pools.destroyed == ["trajectory-generation-subsystem-4"], "what is left of it is removed first"
    assert pools.get(Subsystem.SCENE_GENERATION) is scene and pools.get(Subsystem.TRAJECTORY_GENERATION) is not trajectory
    pools.running.add(container_of(trajectory))
    assert pools.ensure_running() == []


def test_a_pool_that_is_still_starting_counts_as_running(no_docker, monkeypatch, mqtt_connection, geofence):
    pool = SceneGenerationPool.for_scope(InstanceScope.pooled("m1", "n1", "scene_generation"), mqtt_connection, geofence, workers=1)
    monkeypatch.setattr(pooled_service, "is_container_running", lambda name: False)
    pool._lifecycle_thread.join(5.0)
    assert not pool.is_running(), "its start is over and no container is there"

    class Starting:
        def is_alive(self) -> bool:
            return True

    pool._lifecycle_thread = Starting()
    assert pool.is_running()
