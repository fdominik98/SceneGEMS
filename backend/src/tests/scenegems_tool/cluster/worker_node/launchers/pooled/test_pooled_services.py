"""Compose content of a worker node's pooled services: each is named by its scope and found by its label in the worker node's project."""

import pytest

from scenegems_tool.cluster.worker_node.instance_scope import INSTANCE_LABEL, InstanceScope
from scenegems_tool.cluster.worker_node.launchers.pooled import pooled_service
from scenegems_tool.cluster.worker_node.launchers.pooled.monitor_service import MonitorService
from scenegems_tool.cluster.worker_node.launchers.pooled.scene_generation_pool import SceneGenerationPool
from scenegems_tool.cluster.worker_node.launchers.pooled.service_pools import ServicePools
from scenegems_tool.cluster.worker_node.launchers.pooled.trajectory_generation_pool import TrajectoryGenerationPool
from scenegems_tool.cluster.worker_node.subsystem import Subsystem


def test_scoped_pool_is_sized_by_slots_and_named_by_scope(no_docker, mqtt_connection, geofence):
    scope = InstanceScope.pooled("m1", "n1", "scene_generation")
    cluster_broker = mqtt_connection.with_topic_root("scenegems")
    pool = SceneGenerationPool.for_scope(scope, cluster_broker, geofence, workers=3, broker_network="worker_node_broker_net", service_name="scene-generation-subsystem-2")
    compose = pool.labelled(pool.build_compose())
    service = compose["services"]["scene-generation-subsystem"]
    assert service["container_name"] == service["hostname"] == "scenegems-m1-n1-scene-generation-subsystem"
    assert service["labels"] == {INSTANCE_LABEL: "scene-generation-subsystem"}, "what the pool is removed by in the worker node's project"
    assert service["cpus"] == 4
    assert service["environment"]["WORKER_COUNT"] == "3"
    assert "MQTT_TOPIC_PREFIX" not in service["environment"], "no level for the worker node or the instance"
    assert service["environment"]["MQTT_TOPIC_ROOT"] == "scenegems" and service["environment"]["MQTT_SERVICE_NAME"] == "scene-generation-subsystem-2"
    assert compose["networks"]["scene_generation_net"] == {"name": "scenegems-m1-n1-scene-generation-subsystem-net", "driver": "bridge", "labels": {INSTANCE_LABEL: "scene-generation-subsystem"}}
    assert compose["networks"]["scenegems_broker"] == {"external": True, "name": "worker_node_broker_net"}
    assert pool.project.name == scope.compose_project == "scenegems-m1-n1" and pool.project.instance == scope.key
    assert pool.compose_filename == f"{scope.folder}/docker-compose.yml"
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
        return {pool.project.name, service["container_name"], compose["networks"]["trajectory_generation_net"]["name"], pool.compose_filename}

    assert not names(first) & names(second)


def test_image_override_applies_to_pools(no_docker, monkeypatch, mqtt_connection, geofence):
    monkeypatch.setenv("SCENE_GENERATION_IMAGE", "scenegems-scene-generation-subsystem:branch")
    pool = SceneGenerationPool.for_scope(InstanceScope.pooled("m1", "n1", "scene_generation"), mqtt_connection, geofence, workers=1, broker_network="worker_node_broker_net")
    assert pool.build_compose()["services"]["scene-generation-subsystem"]["image"] == "scenegems-scene-generation-subsystem:branch"


def test_scoped_monitor_is_named_by_scope(no_docker, mqtt_connection, geofence):
    scope = InstanceScope.pooled("m1", "n1", "monitoring")
    monitor = MonitorService.for_scope(scope, mqtt_connection, geofence, "scenario_monitor", "waraps/service/virtual/real/scenario_monitor", "rules: []\n")
    service = monitor.labelled(monitor.build_compose())["services"]["monitoring"]
    assert service["container_name"] == "scenegems-m1-n1-monitoring-subsystem"
    assert "MQTT_TOPIC_PREFIX" not in service["environment"] and service["labels"] == {INSTANCE_LABEL: "monitoring-subsystem"}
    assert service["environment"]["MONITOR_AGENT_NAME"] == "scenario_monitor" and service["environment"]["MONITOR_TOPIC"] == "waraps/service/virtual/real/scenario_monitor"
    assert service["environment"]["COLREGS_CONSTRAINTS_YAML_B64"] == "cnVsZXM6IFtdCg==" and service["networks"] == ["scenegems_broker"]
    assert monitor.project.name == "scenegems-m1-n1" and monitor.names.instance == scope.key, "in the worker node's project, found by its label"


def test_a_monitor_is_a_worker_nodes_alone():
    """The control node starts none: the workbench has its previews and runs judged by jobs on a worker node."""
    assert not hasattr(MonitorService, "for_workbench")


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
    pools.start([Subsystem.SCENE_GENERATION, Subsystem.TRAJECTORY_GENERATION, Subsystem.SIMULATION])
    scene = pools.get(Subsystem.SCENE_GENERATION)
    assert scene.service_name == "scene-generation-subsystem-4" and scene.workers == 2
    assert pools.get(Subsystem.TRAJECTORY_GENERATION).service_name == "trajectory-generation-subsystem-4"
    pools.start([Subsystem.SCENE_GENERATION])
    assert pools.get(Subsystem.SCENE_GENERATION) is scene, "a pool that is there is left alone; a subsystem without a pool yet is skipped"


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
