from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.launchers.pooled.pooled_service import PooledService
from scenegems_tool.cluster.worker_node.launchers.pooled.scene_generation_pool import SceneGenerationPool
from scenegems_tool.cluster.worker_node.subsystem import Subsystem


def test_job_scope_is_per_attempt(worker_node, make_job):
    first = worker_node.job_scope(make_job(JobType.SIMULATION, {}, job_id="abc", attempt=1))
    second = worker_node.job_scope(make_job(JobType.SIMULATION, {}, job_id="abc", attempt=2))
    assert (first.instance_id, second.instance_id) == ("simulation-subsystem-abc", "simulation-subsystem-abc-2"), "named after the job's subsystem"
    assert worker_node.job_scope(make_job(JobType.MONITORING_POST_HOC, {}, job_id="abc")).instance_id == "monitoring-subsystem-abc"
    assert worker_node.job_scope(make_job(JobType.CALIBRATION_DEVIATION, {}, job_id="abc")).instance_id == "simulation-subsystem-abc", "repeats of a simulation"
    assert first.docker_name != second.docker_name


def test_pool_workers_come_from_the_slots(worker_node):
    assert worker_node.pool_workers(Subsystem.SCENE_GENERATION) == 3
    assert worker_node.pool_workers(Subsystem.TRAJECTORY_GENERATION) == 1  # no slots offered: the minimum
    worker_node.slots[JobType.MONITORING_POST_HOC] = 4
    assert worker_node.pool_workers(Subsystem.MONITORING) == 4, "as many series at once as the worker node has monitoring slots"
    assert worker_node.pool_workers(Subsystem.SIMULATION) == 2, "as many runs at once as the worker node has simulation slots"


def test_a_worker_node_offers_the_pools_of_its_components(worker_node):
    assert worker_node.pool_subsystems() == [], "a worker node that names no components starts a pool when a job first asks for it"
    worker_node.components = frozenset({"scene_generation", "monitoring", "asv_system/replay", "control_layer/none"})
    assert worker_node.pool_subsystems() == [Subsystem.SCENE_GENERATION, Subsystem.MONITORING]
    # A simulation has no component of its own: a worker node with a simulation layer runs simulations, so it runs the simulation subsystem
    worker_node.components = frozenset({"monitoring", "asv_system/replay", "control_layer/none", "simulation_layer/kinematic"})
    assert worker_node.pool_subsystems() == [Subsystem.MONITORING, Subsystem.SIMULATION]
    worker_node.components = frozenset({"simulation_layer/real_vessel"})
    assert worker_node.pool_subsystems() == [Subsystem.SIMULATION], "a run with only real vessels is a run of the subsystem too"
    worker_node.components = frozenset({"design_space_exploration"})
    worker_node.slots[JobType.DESIGN_SPACE_EXPLORATION] = 2
    assert worker_node.pool_subsystems() == [Subsystem.DESIGN_SPACE_EXPLORATION] and worker_node.pool_workers(Subsystem.DESIGN_SPACE_EXPLORATION) == 2


def test_pools_start_once_with_scoped_names(monkeypatch, worker_node):
    monkeypatch.setattr(PooledService, "_run_container_lifecycle_startup", lambda self, compose: None)
    destroyed = []
    monkeypatch.setattr(PooledService, "destroy", lambda self: destroyed.append(self))
    pool = worker_node.pools.get(Subsystem.SCENE_GENERATION)
    assert isinstance(pool, SceneGenerationPool)
    assert worker_node.pools.get(Subsystem.SCENE_GENERATION) is pool
    assert pool.workers == 3
    assert pool.names.container_name == "scenegems-m1-n1-scene-generation-subsystem"
    assert pool.service_name == "scene-generation-subsystem-1" and pool.service_topic.endswith("/service/virtual/real/scene-generation-subsystem-1")
    worker_node.shutdown()
    assert destroyed == [pool]


def test_another_instance_number_renames_the_pools(monkeypatch, worker_node):
    monkeypatch.setattr(PooledService, "_run_container_lifecycle_startup", lambda self, compose: None)
    destroyed = []
    monkeypatch.setattr(PooledService, "destroy", lambda self: destroyed.append(self))
    first = worker_node.pools.get(Subsystem.SCENE_GENERATION)
    worker_node.set_instance_number(worker_node.instance_number)
    assert destroyed == [], "the number the worker node already has changes nothing"
    worker_node.set_instance_number(3)
    assert destroyed == [first], "a pool under the old name would never hear its tasks"
    renamed = worker_node.pools.get(Subsystem.SCENE_GENERATION)
    assert renamed is not first and renamed.service_name == "scene-generation-subsystem-3"


def test_a_worker_node_lacks_the_components_of_a_job_it_does_not_offer(worker_node, make_job):
    from dataclasses import replace

    from scenegems_tool.cluster.protocol.jobs import JobRequirements

    job = make_job(JobType.SIMULATION, {}).model_copy(update={"requirements": JobRequirements(components=["asv_system/replay", "simulation_layer/gazebo"])})
    assert worker_node.lacks(job) == [], "a worker node that names no components (the workbench) runs anything"
    kinematic = replace(worker_node, components=frozenset({"asv_system/replay", "control_layer/none", "simulation_layer/kinematic"}))
    assert kinematic.lacks(job) == ["simulation_layer/gazebo"]
