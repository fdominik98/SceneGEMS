"""The Deployments of a worker node's pooled services, against a fake cluster API: named and labelled by their scope, pinned to the worker node's node, owned by its daemon."""

import pytest
from kubernetes.client.exceptions import ApiException

from scenegems_tool.cluster.scope_names import WORKER_NODE_NAME_MAX
from scenegems_tool.cluster.worker_node.instance_scope import INSTANCE_LABEL, KUBERNETES_NAME_MAX, WORKER_NODE_LABEL, InstanceScope
from scenegems_tool.cluster.worker_node.launchers.kubernetes_api import Kind
from scenegems_tool.cluster.worker_node.launchers.pooled.design_space_exploration_pool import DesignSpaceExplorationPool
from scenegems_tool.cluster.worker_node.launchers.pooled.monitoring_pool import MonitoringPool
from scenegems_tool.cluster.worker_node.launchers.pooled.scene_generation_pool import SceneGenerationPool
from scenegems_tool.cluster.worker_node.launchers.pooled.service_pools import ServicePools
from scenegems_tool.cluster.worker_node.launchers.pooled.simulation_pool import SimulationPool, image_overrides
from scenegems_tool.cluster.worker_node.launchers.pooled.trajectory_generation_pool import TrajectoryGenerationPool
from scenegems_tool.cluster.worker_node.subsystem import Subsystem

POOL_CLASSES = [
    (DesignSpaceExplorationPool, "design_space_exploration"),
    (SceneGenerationPool, "scene_generation"),
    (TrajectoryGenerationPool, "trajectory_generation"),
    (MonitoringPool, "monitoring"),
    (SimulationPool, "simulation"),
]


def applied(pool, fake_cluster) -> dict:
    """The Deployment the pool's start applied, once the start is over."""
    pool._lifecycle_thread.join(5.0)
    return fake_cluster.get(Kind.DEPLOYMENT, pool.names.deployment)


def environment_of(deployment: dict) -> dict:
    return {entry["name"]: entry["value"] for entry in deployment["spec"]["template"]["spec"]["containers"][0]["env"]}


def test_a_pool_is_a_deployment_of_one_pod_on_the_worker_nodes_node_owned_by_its_daemon(release_images, fake_cluster, cluster_place, mqtt_connection, geofence):
    scope = InstanceScope.pooled("m1", "n1", "scene_generation")
    cluster_broker = mqtt_connection.with_topic_root("scenegems")
    pool = SceneGenerationPool.for_scope(scope, cluster_broker, geofence, 3, cluster_place, fake_cluster.api(), "scene-generation-subsystem-2")
    deployment = applied(pool, fake_cluster)
    labels = {INSTANCE_LABEL: "scene-generation-subsystem", WORKER_NODE_LABEL: "n1"}
    assert deployment["metadata"]["name"] == "n1-scene-generation-subsystem" and deployment["metadata"]["namespace"] == "scenegems"
    assert deployment["metadata"]["labels"] == labels, "what a later daemon process finds it by"
    assert deployment["metadata"]["ownerReferences"] == [
        {"apiVersion": "apps/v1", "kind": "Deployment", "name": "worker-node-n1", "uid": fake_cluster.get(Kind.DEPLOYMENT, "worker-node-n1")["metadata"]["uid"]}
    ]
    spec = deployment["spec"]
    assert spec["replicas"] == 1 and spec["strategy"] == {"type": "Recreate"}, "never two pods under one name on the broker"
    assert spec["selector"] == {"matchLabels": labels} and spec["template"]["metadata"]["labels"] == labels
    pod = spec["template"]["spec"]
    assert pod["nodeSelector"] == {"kubernetes.io/hostname": "k3d-lab-agent-0"}
    assert pod["automountServiceAccountToken"] is False and "serviceAccountName" not in pod and "volumes" not in pod, "it never talks to the cluster API"
    [container] = pod["containers"]
    assert container["name"] == "scene-generation-subsystem" and container["image"].startswith("scenegems-scene-generation-subsystem:")
    assert container["imagePullPolicy"] == "IfNotPresent"
    assert container["resources"] == {"limits": {"cpu": "4"}, "requests": {"cpu": "100m"}}, "a core per worker and one for the service, as a limit"
    environment = environment_of(deployment)
    assert environment["WORKER_COUNT"] == "3" and environment["MQTT_BROKER"] == "broker"
    assert "MQTT_TOPIC_PREFIX" not in environment, "no level for the worker node or the instance"
    assert environment["MQTT_TOPIC_ROOT"] == "scenegems" and environment["MQTT_SERVICE_NAME"] == "scene-generation-subsystem-2"
    # Clients of the pool address it by the name and the topic its pod was given.
    assert (pool.service_name, pool.service_topic) == ("scene-generation-subsystem-2", "scenegems/service/virtual/real/scene-generation-subsystem-2")
    assert pool.mqtt_connection is cluster_broker, "the connection as it was given: nothing is put in front of its topics"


def test_a_pool_on_its_own_keeps_the_subsystems_name_on_a_waraps_topic(release_images, fake_cluster, cluster_place, mqtt_connection, geofence):
    pool = SceneGenerationPool.for_scope(InstanceScope.pooled("m1", "n1", "scene_generation"), mqtt_connection, geofence, 1, cluster_place, fake_cluster.api())
    assert (pool.service_name, pool.service_topic) == ("scene-generation-subsystem", "waraps/service/virtual/real/scene-generation-subsystem")
    environment = environment_of(pool.build_deployment())
    assert environment["MQTT_SERVICE_NAME"] == "scene-generation-subsystem" and "MQTT_TOPIC_ROOT" not in environment


def test_without_an_owner_the_pool_is_owned_by_nobody(release_images, fake_cluster, cluster_place, mqtt_connection, geofence):
    from dataclasses import replace

    pool = MonitoringPool.for_scope(InstanceScope.pooled("m1", "n1", "monitoring"), mqtt_connection, geofence, 1, replace(cluster_place, owner=None), fake_cluster.api())
    assert "ownerReferences" not in pool.build_deployment()["metadata"]


def test_the_pools_of_two_worker_nodes_share_no_name_and_no_labels(release_images, fake_cluster, cluster_place, mqtt_connection, geofence):
    first = TrajectoryGenerationPool.for_scope(InstanceScope.pooled("m1", "n1", "trajectory_generation"), mqtt_connection, geofence, 1, cluster_place, fake_cluster.api())
    second = TrajectoryGenerationPool.for_scope(InstanceScope.pooled("m1", "n2", "trajectory_generation"), mqtt_connection, geofence, 1, cluster_place, fake_cluster.api())
    assert first.names.deployment != second.names.deployment and first.names.labels != second.names.labels
    assert (first.names.deployment, second.names.deployment) == ("n1-trajectory-generation-subsystem", "n2-trajectory-generation-subsystem")


@pytest.mark.parametrize("pool_class, subsystem", POOL_CLASSES)
def test_the_name_of_every_pool_fits_kubernetes_whole_with_the_longest_worker_node_name(release_images, fake_cluster, cluster_place, mqtt_connection, geofence, pool_class, subsystem):
    """The bound is on the worker node's name (28): with it every pool's Deployment has its whole name, and its container the subsystem's."""
    worker_node = "w" * WORKER_NODE_NAME_MAX
    scope = InstanceScope.pooled("a-cluster-with-quite-a-long-name", worker_node, subsystem)
    pool = pool_class.for_scope(scope, mqtt_connection, geofence, 1, cluster_place, fake_cluster.api())
    deployment = pool.build_deployment()
    assert deployment["metadata"]["name"] == f"{worker_node}-{scope.instance_id}" and len(deployment["metadata"]["name"]) <= KUBERNETES_NAME_MAX
    assert deployment["spec"]["template"]["spec"]["containers"][0]["name"] == scope.instance_id
    assert all(len(value) <= KUBERNETES_NAME_MAX for value in deployment["metadata"]["labels"].values())


@pytest.mark.parametrize(
    "reference",
    [
        "scenegems-scene-generation-subsystem:branch",
        "registry.lab:5000/scenegems-scene-generation-subsystem@sha256:4f61a86c1d5e1c0a8c2b5e0f0c9a7e6d5c4b3a291807f6e5d4c3b2a1908f7e6d",
    ],
)
def test_an_image_override_is_the_pools_image_as_given_by_tag_or_by_digest(release_images, monkeypatch, fake_cluster, cluster_place, mqtt_connection, geofence, reference):
    """The chart gives every workerNodeImages entry to the daemon; a deploy names images by digest, the test cluster by tag."""
    monkeypatch.setenv("SCENE_GENERATION_IMAGE", reference)
    pool = SceneGenerationPool.for_scope(InstanceScope.pooled("m1", "n1", "scene_generation"), mqtt_connection, geofence, 1, cluster_place, fake_cluster.api())
    assert pool.build_deployment()["spec"]["template"]["spec"]["containers"][0]["image"] == reference


def test_the_monitoring_pool_is_sized_by_slots_and_named_by_scope(release_images, fake_cluster, cluster_place, mqtt_connection, geofence):
    scope = InstanceScope.pooled("m1", "n1", "monitoring")
    pool = MonitoringPool.for_scope(scope, mqtt_connection.with_topic_root("scenegems"), geofence, 2, cluster_place, fake_cluster.api(), "monitoring-subsystem-2")
    deployment = applied(pool, fake_cluster)
    assert deployment["metadata"]["name"] == "n1-monitoring-subsystem" and deployment["metadata"]["labels"][INSTANCE_LABEL] == "monitoring-subsystem"
    assert deployment["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"] == {"cpu": "3"}, "a core per series it judges at once, and one for the service"
    environment = environment_of(deployment)
    assert (environment["WORKER_COUNT"], environment["MQTT_SERVICE_NAME"], environment["MQTT_TOPIC_ROOT"]) == ("2", "monitoring-subsystem-2", "scenegems")
    # The COLREGS constants come with every request, and the name and the topic with the launcher's variables
    assert not {"MONITOR_AGENT_NAME", "MONITOR_TOPIC", "COLREGS_CONSTRAINTS_YAML_B64", "MQTT_TOPIC_PREFIX"} & set(environment)
    assert (pool.service_name, pool.service_topic) == ("monitoring-subsystem-2", "scenegems/service/virtual/real/monitoring-subsystem-2")


def test_the_design_space_exploration_pool_is_sized_by_slots(release_images, fake_cluster, cluster_place, mqtt_connection, geofence):
    scope = InstanceScope.pooled("m1", "n1", "design_space_exploration")
    pool = DesignSpaceExplorationPool.for_scope(scope, mqtt_connection.with_topic_root("scenegems"), geofence, 2, cluster_place, fake_cluster.api(), "design-space-exploration-subsystem-2")
    deployment = pool.build_deployment()
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert deployment["metadata"]["name"] == "n1-design-space-exploration-subsystem" and container["resources"]["limits"] == {
        "cpu": "3"
    }, "a core per generator it runs at once, and one for the service"
    assert "command" not in container and "args" not in container, "the image's own service"
    assert (environment_of(deployment)["WORKER_COUNT"], environment_of(deployment)["MQTT_SERVICE_NAME"]) == (
        "2",
        "design-space-exploration-subsystem-2",
    ), "the pool size is also what the generators share the memory by"
    assert DesignSpaceExplorationPool.default_service_name == "design-space-exploration-subsystem" and DesignSpaceExplorationPool.subsystem is Subsystem.DESIGN_SPACE_EXPLORATION


def test_the_simulation_pool_gets_what_it_needs_to_create_the_pods_of_its_runs(release_images, monkeypatch, fake_cluster, cluster_place, mqtt_connection, geofence):
    """The one pool that creates objects: its service account, the node's runtime folder at the image's folder, and the place its runs go to."""
    monkeypatch.setenv("SITL_IMAGE", "registry.lab:5000/scenegems-ardupilot-sitl@sha256:" + "a" * 64)
    monkeypatch.setenv("SCENEGEMS_IMAGE_TAG", "release-7")
    scope = InstanceScope.pooled("m1", "n1", "simulation")
    pool = SimulationPool.for_scope(scope, mqtt_connection.with_topic_root("scenegems"), geofence, 2, cluster_place, fake_cluster.api(), "simulation-subsystem-2")
    deployment = applied(pool, fake_cluster)
    assert deployment["metadata"]["name"] == "n1-simulation-subsystem" and deployment["metadata"]["labels"][INSTANCE_LABEL] == "simulation-subsystem"
    pod = deployment["spec"]["template"]["spec"]
    assert pod["serviceAccountName"] == "simulation-subsystem" and pod["automountServiceAccountToken"] is True
    assert pod["volumes"] == [{"name": "runtime", "hostPath": {"path": "/var/lib/scenegems/n1/runtime", "type": "DirectoryOrCreate"}}]
    [container] = pod["containers"]
    assert container["volumeMounts"] == [{"name": "runtime", "mountPath": "/app/assets/runtime_assets"}], "where the image has the folder, also when the launcher runs from a Windows checkout"
    assert container["image"].startswith("scenegems-simulation-subsystem:") and "command" not in container, "the image's own service"
    assert "docker.sock" not in str(deployment), "no Docker socket"
    environment = environment_of(deployment)
    assert (environment["SCENEGEMS_CONTROL_NODE_ID"], environment["SCENEGEMS_WORKER_NODE_ID"]) == ("m1", "n1"), "its runs are named after the worker node, as the daemon named them"
    assert (environment["SCENEGEMS_KUBERNETES_NAMESPACE"], environment["SCENEGEMS_KUBERNETES_NODE"], environment["SCENEGEMS_RUNTIME_HOST_PATH"]) == (
        "scenegems",
        "k3d-lab-agent-0",
        "/var/lib/scenegems/n1/runtime",
    ), "where its runs' pods go"
    assert not {"SCENEGEMS_DOCKER_NETWORK", "SCENEGEMS_RUNTIME_VOLUME"} & set(environment)
    assert (environment["SITL_IMAGE"], environment["SCENEGEMS_IMAGE_TAG"]) == (
        "registry.lab:5000/scenegems-ardupilot-sitl@sha256:" + "a" * 64,
        "release-7",
    ), "its runs use the images the daemon was given"
    assert (environment["WORKER_COUNT"], environment["MQTT_SERVICE_NAME"], container["resources"]["limits"]["cpu"]) == ("2", "simulation-subsystem-2", "3")
    assert (pool.service_name, pool.service_topic) == ("simulation-subsystem-2", "scenegems/service/virtual/real/simulation-subsystem-2")


def test_only_set_image_overrides_and_the_tag_are_passed_on():
    environment = {"SITL_IMAGE": "sitl:branch", "GAZEBO_IMAGE": " ", "SCENEGEMS_IMAGE_TAG": "r7", "PATH": "/bin", "IMAGE_CACHE": "x"}
    assert image_overrides(environment) == {"SITL_IMAGE": "sitl:branch", "SCENEGEMS_IMAGE_TAG": "r7"}
    assert image_overrides({"PATH": "/bin"}) == {}


def test_a_monitoring_pool_on_its_own_keeps_the_subsystems_name():
    assert MonitoringPool.default_service_name == "monitoring-subsystem" and MonitoringPool.subsystem is Subsystem.MONITORING


# The lifecycle of one pool


def test_a_pool_is_there_while_its_deployment_is_whether_or_not_its_pod_is_ready(release_images, fake_cluster, cluster_place, mqtt_connection, geofence):
    pool = SceneGenerationPool.for_scope(InstanceScope.pooled("m1", "n1", "scene_generation"), mqtt_connection, geofence, 1, cluster_place, fake_cluster.api())
    applied(pool, fake_cluster)
    assert pool.is_running() and not pool.is_available(), "Kubernetes starts its pod; a pod being pulled or restarted is no reason to apply it again"
    fake_cluster.set_available(pool.names.deployment)
    assert pool.is_available()
    fake_cluster.fail_next["read"] = ApiException(status=503, reason="unavailable")
    assert pool.is_running(), "a cluster API that cannot be read just now is no reason either"
    fake_cluster.objects.pop(("scenegems", Kind.DEPLOYMENT, pool.names.deployment))
    assert not pool.is_running(), "a Deployment that is gone is"


def test_a_pool_that_is_still_starting_counts_as_running(release_images, fake_cluster, cluster_place, mqtt_connection, geofence):
    pool = SceneGenerationPool.for_scope(InstanceScope.pooled("m1", "n1", "scene_generation"), mqtt_connection, geofence, 1, cluster_place, fake_cluster.api())
    applied(pool, fake_cluster)

    class Starting:
        def is_alive(self) -> bool:
            return True

    fake_cluster.objects.clear()
    pool._lifecycle_thread = Starting()
    assert pool.is_running()


def test_a_pool_applies_its_deployment_again_over_one_of_its_name_and_destroy_deletes_it(release_images, fake_cluster, cluster_place, mqtt_connection, geofence):
    scope = InstanceScope.pooled("m1", "n1", "scene_generation")
    first = SceneGenerationPool.for_scope(scope, mqtt_connection, geofence, 1, cluster_place, fake_cluster.api())
    uid = applied(first, fake_cluster)["metadata"]["uid"]
    second = SceneGenerationPool.for_scope(scope, mqtt_connection, geofence, 2, cluster_place, fake_cluster.api())
    replaced = applied(second, fake_cluster)
    assert replaced["metadata"]["uid"] == uid and environment_of(replaced)["WORKER_COUNT"] == "2", "replaced in place"
    second.destroy()
    assert fake_cluster.get(Kind.DEPLOYMENT, scope.name) is None
    assert fake_cluster.deletions[-1]["propagation_policy"] == "Background"
    second.destroy()  # nothing left to delete: no error


def test_a_failed_start_or_delete_is_logged_and_not_raised(release_images, fake_cluster, cluster_place, mqtt_connection, geofence, caplog):
    fake_cluster.fail_next["create"] = ApiException(status=403, reason="Forbidden")
    pool = SceneGenerationPool.for_scope(InstanceScope.pooled("m1", "n1", "scene_generation"), mqtt_connection, geofence, 1, cluster_place, fake_cluster.api())
    assert applied(pool, fake_cluster) is None and "could not apply its Deployment" in caplog.text
    fake_cluster.fail_next["delete"] = ApiException(status=500, reason="boom")
    pool.destroy()
    assert "Cannot delete the Deployment" in caplog.text


# The pools of a worker node: started together, looked after, removed together


@pytest.fixture
def pools(release_images, fake_cluster, cluster_place, mqtt_connection, geofence):
    """A worker node's pools in the fake cluster."""
    made = ServicePools("m1", "n1", mqtt_connection, geofence, workers=lambda subsystem: 2, cluster=cluster_place, api=fake_cluster.api(), instance_number=lambda: 4)
    yield made
    made.shutdown()


def settled(pools) -> None:
    for pool in pools._pools.values():
        if pool._lifecycle_thread is not None:
            pool._lifecycle_thread.join(5.0)


def test_the_pools_of_the_subsystems_start_together_each_once(pools, fake_cluster):
    pools.start([Subsystem.DESIGN_SPACE_EXPLORATION, Subsystem.SCENE_GENERATION, Subsystem.TRAJECTORY_GENERATION, Subsystem.MONITORING, Subsystem.SIMULATION])
    settled(pools)
    scene = pools.get(Subsystem.SCENE_GENERATION)
    assert scene.service_name == "scene-generation-subsystem-4" and scene.workers == 2
    assert pools.get(Subsystem.TRAJECTORY_GENERATION).service_name == "trajectory-generation-subsystem-4"
    monitoring = pools.get(Subsystem.MONITORING)
    assert isinstance(monitoring, MonitoringPool) and (monitoring.service_name, monitoring.workers) == ("monitoring-subsystem-4", 2)
    exploration = pools.get(Subsystem.DESIGN_SPACE_EXPLORATION)
    assert isinstance(exploration, DesignSpaceExplorationPool) and (exploration.service_name, exploration.workers) == ("design-space-exploration-subsystem-4", 2)
    simulation = pools.get(Subsystem.SIMULATION)
    assert isinstance(simulation, SimulationPool) and (simulation.service_name, simulation.workers, simulation.worker_node_id) == ("simulation-subsystem-4", 2, "n1")
    assert fake_cluster.names(Kind.DEPLOYMENT) == sorted(
        ["worker-node-n1", "n1-design-space-exploration-subsystem", "n1-scene-generation-subsystem", "n1-trajectory-generation-subsystem", "n1-monitoring-subsystem", "n1-simulation-subsystem"]
    )
    pools.start([Subsystem.SCENE_GENERATION])
    assert pools.get(Subsystem.SCENE_GENERATION) is scene, "a pool that is there is left alone"


def test_a_pool_whose_deployment_is_gone_is_applied_again(pools, fake_cluster):
    pools.start([Subsystem.SCENE_GENERATION, Subsystem.TRAJECTORY_GENERATION])
    settled(pools)
    scene, trajectory = pools.get(Subsystem.SCENE_GENERATION), pools.get(Subsystem.TRAJECTORY_GENERATION)
    fake_cluster.objects.pop(("scenegems", Kind.DEPLOYMENT, trajectory.names.deployment))
    assert pools.ensure_running() == [Subsystem.TRAJECTORY_GENERATION]
    settled(pools)
    assert pools.get(Subsystem.SCENE_GENERATION) is scene and pools.get(Subsystem.TRAJECTORY_GENERATION) is not trajectory
    assert fake_cluster.get(Kind.DEPLOYMENT, trajectory.names.deployment) is not None
    assert pools.ensure_running() == []


def test_the_pools_are_deleted_together(pools, fake_cluster):
    pools.start([Subsystem.SCENE_GENERATION, Subsystem.MONITORING])
    settled(pools)
    pools.shutdown()
    assert fake_cluster.names(Kind.DEPLOYMENT) == ["worker-node-n1"], "the daemon's own Deployment stays"


def test_a_worker_node_without_a_place_in_a_cluster_names_its_pools_but_starts_none(mqtt_connection, geofence):
    pools = ServicePools("m1", "n1", mqtt_connection, geofence, workers=lambda subsystem: 1, instance_number=lambda: 3)
    assert pools.service_name(Subsystem.MONITORING) == "monitoring-subsystem-3"
    with pytest.raises(RuntimeError, match="no place in a Kubernetes cluster"):
        pools.get(Subsystem.MONITORING)
