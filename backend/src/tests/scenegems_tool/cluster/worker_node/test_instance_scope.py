import re

import pytest

from scenegems_tool.cluster.worker_node.instance_scope import (
    INSTANCE_LABEL,
    InstanceScope,
    docker_word,
    pooled_service_name,
    safe_id,
    short_job_id,
    subsystem_name,
    worker_node_project,
)
from scenegems_tool.messaging.topic_scope import TopicScope

DOCKER_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]+$")
COMPOSE_PROJECT = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
JOB_ID = "265ca868-b95b-4baa-a53a-5dae157a3f5a"


def test_a_worker_node_is_one_compose_project_for_all_its_instances():
    assert worker_node_project("local-cluster", "worker-node-1") == "scenegems-local-cluster-worker-node-1"
    pool = InstanceScope.pooled("local-cluster", "worker-node-1", "scene_generation")
    job = InstanceScope.per_job("local-cluster", "worker-node-1", "simulation", JOB_ID)
    assert pool.compose_project == job.compose_project == "scenegems-local-cluster-worker-node-1"


def test_pooled_instance_names_follow_the_contract():
    scope = InstanceScope.pooled("m1", "n1", "scene_generation")
    assert scope.instance_id == "scene-generation-subsystem"
    assert scope.key == scope.instance_id
    assert scope.docker_name == "scenegems-m1-n1-scene-generation-subsystem"
    assert scope.container_name("runner") == "scenegems-m1-n1-scene-generation-subsystem-runner"
    assert scope.network_name("net") == "scenegems-m1-n1-scene-generation-subsystem-net"
    assert scope.labels == {INSTANCE_LABEL: "scene-generation-subsystem"}


def test_per_job_instance_names_follow_the_contract():
    scope = InstanceScope.per_job("m1", "n1", "simulation", JOB_ID)
    assert scope.instance_id == "simulation-subsystem-265ca868"
    assert scope.docker_name == "scenegems-m1-n1-simulation-subsystem-265ca868"
    assert scope.container_name("kinematic_sim") == "scenegems-m1-n1-simulation-subsystem-265ca868-kinematic-sim", "one spelling: hyphens"
    assert scope.service_key("vessel_0_asv_system") == "simulation-subsystem-265ca868-vessel-0-asv-system", "unique in the worker node's project"
    assert scope.key == f"{JOB_ID}-1", "found by the whole job id and attempt, which no two jobs share"


def test_a_retry_carries_its_attempt_and_the_first_attempt_none():
    first = InstanceScope.per_job("m1", "n1", "monitoring", JOB_ID, 1)
    retry = InstanceScope.per_job("m1", "n1", "monitoring", JOB_ID, 2)
    assert (first.instance_id, retry.instance_id) == ("monitoring-subsystem-265ca868", "monitoring-subsystem-265ca868-2")
    assert first.key != retry.key and first.folder != retry.folder
    with pytest.raises(ValueError):
        InstanceScope.per_job("m1", "n1", "monitoring", JOB_ID, 0)


def test_jobs_with_the_same_short_id_still_have_their_own_label():
    first = InstanceScope.per_job("m1", "n1", "simulation", "265ca868-aaaa")
    second = InstanceScope.per_job("m1", "n1", "simulation", "265ca868-bbbb")
    assert first.instance_id == second.instance_id, "the readable name is only the start of the job id"
    assert first.labels != second.labels, "so one job's teardown never removes the other's containers"


def test_subsystem_and_pool_names():
    assert subsystem_name("design_space_exploration") == "design-space-exploration-subsystem"
    assert pooled_service_name("scene_generation", 1) == "scene-generation-subsystem-1"
    assert pooled_service_name("trajectory_generation", 12) == "trajectory-generation-subsystem-12"
    with pytest.raises(ValueError):
        pooled_service_name("scene_generation", 0)


def test_short_job_ids_and_docker_words():
    assert short_job_id(JOB_ID) == "265ca868"
    assert short_job_id("Job_42") == "job-42"
    assert short_job_id("abc-def-ghi") == "abc-def", "no hyphen at the end"
    assert docker_word("kinematic_sim") == "kinematic-sim"


def test_every_derived_name_is_valid_for_docker_and_compose():
    scope = InstanceScope.per_job("control-node-a", "3f2b8c1e-6d1a-4b7e-9f00-1234567890ab", "simulation", "8d1c2e3f-aaaa-bbbb-cccc-0123456789ab", 2)
    for name in (scope.docker_name, scope.container_name("vessel_1"), scope.network_name("net"), scope.service_key("vessel_1")):
        assert DOCKER_NAME.match(name), name
    assert COMPOSE_PROJECT.match(scope.compose_project)


def test_two_worker_nodes_and_two_instances_never_share_a_name():
    scopes = [
        InstanceScope.pooled("m1", "n1", "scene_generation"),
        InstanceScope.pooled("m1", "n2", "scene_generation"),
        InstanceScope.pooled("m1", "n1", "trajectory_generation"),
        InstanceScope.pooled("m2", "n1", "scene_generation"),
        InstanceScope.per_job("m1", "n1", "simulation", "a"),
        InstanceScope.per_job("m1", "n1", "monitoring", "a"),
    ]
    assert len({scope.docker_name for scope in scopes}) == len(scopes)
    assert len({scope.folder for scope in scopes}) == len(scopes)
    assert len({(scope.compose_project, scope.service_key("runner")) for scope in scopes}) == len(scopes)


@pytest.mark.parametrize("control_node_id, worker_node_id, instance_id", [("M1", "n1", "x"), ("m1", "n/1", "x"), ("m1", "n1", "+"), ("m1", "", "x"), ("-m", "n1", "x")])
def test_invalid_ids_are_rejected(control_node_id, worker_node_id, instance_id):
    with pytest.raises(ValueError):
        InstanceScope(control_node_id, worker_node_id, instance_id)


def test_overlong_scope_is_rejected():
    with pytest.raises(ValueError):
        InstanceScope("m1", "n1", "x" * 200)


def test_safe_id_maps_any_string_to_scope_characters():
    assert safe_id("Job 7/Attempt#2") == "job-7-attempt-2"
    with pytest.raises(ValueError):
        safe_id("///")


def test_instance_folders_are_separate_per_scope():
    first = InstanceScope.pooled("m1", "n1", "scene_generation")
    assert first.folder.endswith("/instances/scenegems-m1-n1-scene-generation-subsystem")


def test_a_live_session_keeps_a_project_and_a_topic_prefix_of_its_own():
    scope = InstanceScope.live_session("m1", "ab12cd34")
    assert scope.compose_project == scope.docker_name == "scenegems-m1-workbench-live-ab12cd34"
    assert scope.container_name("simulation") == "scenegems-m1-workbench-live-ab12cd34-simulation"
    assert scope.network_name("simulation_net") == "scenegems-m1-workbench-live-ab12cd34-simulation_net"
    assert scope.service_key("simulation") == "simulation"
    assert scope.topic_prefix == "scenegems/m1/workbench/live-ab12cd34/"
    TopicScope(scope.topic_prefix)  # a valid prefix: no wildcards, ends with '/'
