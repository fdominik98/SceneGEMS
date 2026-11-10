import re

import pytest

from scenegems_tool.cluster.worker_node.instance_scope import InstanceScope, safe_id, worker_node_topic_scope
from scenegems_tool.messaging.topic_scope import TopicScope

DOCKER_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]+$")
COMPOSE_PROJECT = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def test_pooled_instance_names_follow_the_contract():
    scope = InstanceScope.pooled("m1", "n1", "scene_generation")
    assert scope.instance_id == "scene_generation-0"
    assert scope.topic_prefix == "scenegems/m1/n1/scene_generation-0/"
    assert scope.docker_name == "scenegems-m1-n1-scene_generation-0"
    assert scope.compose_project == scope.docker_name
    assert scope.container_name("runner") == "scenegems-m1-n1-scene_generation-0-runner"
    assert scope.network_name("net") == "scenegems-m1-n1-scene_generation-0-net"


def test_per_job_instance_names_follow_the_contract():
    scope = InstanceScope.per_job("m1", "n1", "Job_42")
    assert scope.instance_id == "job-job_42"
    assert scope.topic_prefix == "scenegems/m1/n1/job-job_42/"


def test_every_derived_name_is_valid_for_docker_compose_and_mqtt():
    scope = InstanceScope.per_job("control-node-a", "3f2b8c1e-6d1a-4b7e-9f00-1234567890ab", "8d1c2e3f-aaaa-bbbb-cccc-0123456789ab-2")
    for name in (scope.docker_name, scope.container_name("vessel_1"), scope.network_name("net")):
        assert DOCKER_NAME.match(name), name
    assert COMPOSE_PROJECT.match(scope.compose_project)
    TopicScope(scope.topic_prefix)  # a valid prefix: no wildcards, ends with '/'


def test_instance_prefixes_lie_under_the_worker_node_and_control_node_scopes():
    scope = InstanceScope.pooled("m1", "n1", "trajectory_generation", 2)
    assert scope.topic_prefix.startswith(worker_node_topic_scope("m1", "n1"))
    assert worker_node_topic_scope("m1", "n1").startswith("scenegems/m1/")


def test_two_worker_nodes_and_two_pools_never_share_a_name():
    scopes = [
        InstanceScope.pooled("m1", "n1", "scene_generation"),
        InstanceScope.pooled("m1", "n2", "scene_generation"),
        InstanceScope.pooled("m1", "n1", "scene_generation", 1),
        InstanceScope.pooled("m2", "n1", "scene_generation"),
        InstanceScope.per_job("m1", "n1", "a"),
    ]
    assert len({scope.topic_prefix for scope in scopes}) == len(scopes)
    assert len({scope.docker_name for scope in scopes}) == len(scopes)
    assert len({scope.folder for scope in scopes}) == len(scopes)


@pytest.mark.parametrize("control_node_id, worker_node_id, instance_id", [("M1", "n1", "x"), ("m1", "n/1", "x"), ("m1", "n1", "+"), ("m1", "", "x"), ("-m", "n1", "x")])
def test_invalid_ids_are_rejected(control_node_id, worker_node_id, instance_id):
    with pytest.raises(ValueError):
        InstanceScope(control_node_id, worker_node_id, instance_id)


def test_negative_pool_index_is_rejected():
    with pytest.raises(ValueError):
        InstanceScope.pooled("m1", "n1", "monitoring", -1)


def test_overlong_scope_is_rejected():
    with pytest.raises(ValueError):
        InstanceScope("m1", "n1", "x" * 200)


def test_safe_id_maps_any_string_to_scope_characters():
    assert safe_id("Job 7/Attempt#2") == "job-7-attempt-2"
    with pytest.raises(ValueError):
        safe_id("///")


def test_instance_folders_are_separate_per_scope():
    first = InstanceScope.pooled("m1", "n1", "scene_generation")
    assert first.folder.endswith("/instances/scenegems-m1-n1-scene_generation-0")
