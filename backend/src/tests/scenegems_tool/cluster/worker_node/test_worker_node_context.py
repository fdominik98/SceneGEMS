from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.launchers.pooled.pooled_service import PooledService
from scenegems_tool.cluster.worker_node.launchers.pooled.scene_generation_pool import SceneGenerationPool
from scenegems_tool.cluster.worker_node.subsystem import Subsystem


def test_job_scope_is_per_attempt(worker_node, make_job):
    first = worker_node.job_scope(make_job(JobType.SIMULATION, {}, job_id="abc", attempt=1))
    second = worker_node.job_scope(make_job(JobType.SIMULATION, {}, job_id="abc", attempt=2))
    assert first.instance_id == "job-abc-1"
    assert first.docker_name != second.docker_name


def test_pool_workers_come_from_the_slots(worker_node):
    assert worker_node.pool_workers(Subsystem.SCENE_GENERATION) == 3
    assert worker_node.pool_workers(Subsystem.TRAJECTORY_GENERATION) == 1  # no slots offered: the minimum


def test_pools_start_once_with_scoped_names(monkeypatch, worker_node):
    monkeypatch.setattr(PooledService, "_run_container_lifecycle_startup", lambda self, compose: None)
    destroyed = []
    monkeypatch.setattr(PooledService, "destroy", lambda self: destroyed.append(self))
    pool = worker_node.pools.get(Subsystem.SCENE_GENERATION)
    assert isinstance(pool, SceneGenerationPool)
    assert worker_node.pools.get(Subsystem.SCENE_GENERATION) is pool
    assert pool.workers == 3
    assert pool.names.container_name == "scenegems-m1-n1-scene_generation-0"
    assert pool.mqtt_connection.topic_prefix == "scenegems/m1/n1/scene_generation-0/"
    worker_node.shutdown()
    assert destroyed == [pool]


def test_a_worker_node_lacks_the_components_of_a_job_it_does_not_offer(worker_node, make_job):
    from dataclasses import replace

    from scenegems_tool.cluster.protocol.jobs import JobRequirements

    job = make_job(JobType.SIMULATION, {}).model_copy(update={"requirements": JobRequirements(components=["asv_software/replay", "simulation_layer/gazebo"])})
    assert worker_node.lacks(job) == [], "a worker node that names no components (the workbench) runs anything"
    kinematic = replace(worker_node, components=frozenset({"asv_software/replay", "control_layer/none", "simulation_layer/kinematic"}))
    assert kinematic.lacks(job) == ["simulation_layer/gazebo"]
