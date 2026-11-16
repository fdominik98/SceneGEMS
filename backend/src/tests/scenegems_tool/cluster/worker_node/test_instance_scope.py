import re

import pytest

from scenegems_tool.cluster.worker_node.instance_scope import (
    INSTANCE_LABEL,
    KUBERNETES_NAME_MAX,
    WORKER_NODE_LABEL,
    WORKER_NODE_NAME_MAX,
    InstanceScope,
    daemon_deployment_name,
    docker_word,
    is_instance_folder,
    kubernetes_name,
    label_value,
    pooled_service_name,
    safe_id,
    short_job_id,
    subsystem_name,
    worker_node_project,
    worker_node_selector_labels,
)
from scenegems_tool.cluster.worker_node.subsystem import Subsystem

DNS_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")  # a Kubernetes object name
LABEL_VALUE = re.compile(r"^(([A-Za-z0-9][-A-Za-z0-9_.]*)?[A-Za-z0-9])?$")
DOCKER_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]+$")
JOB_ID = "265ca868-b95b-4baa-a53a-5dae157a3f5a"


def test_a_pool_is_named_after_its_worker_node_and_subsystem_without_the_control_node():
    """The namespace is the SceneGEMS cluster's, so it scopes the control node; the worker nodes of a cluster share it."""
    scope = InstanceScope.pooled("m1", "n1", "scene_generation")
    assert scope.instance_id == scope.key == "scene-generation-subsystem"
    assert scope.name == "n1-scene-generation-subsystem"
    assert scope.labels == {INSTANCE_LABEL: "scene-generation-subsystem", WORKER_NODE_LABEL: "n1"}
    assert scope.folder.endswith("/instances/n1-scene-generation-subsystem")


def test_a_run_is_named_after_its_job_and_found_by_the_whole_job_id_and_attempt():
    scope = InstanceScope.per_job("m1", "n1", "simulation", JOB_ID)
    assert scope.instance_id == "simulation-subsystem-265ca868" and scope.name == "n1-simulation-subsystem-265ca868"
    assert scope.key == f"{JOB_ID}-1" and scope.labels[INSTANCE_LABEL] == f"{JOB_ID}-1", "which no two jobs share"


def test_a_retry_carries_its_attempt_and_the_first_attempt_none():
    first = InstanceScope.per_job("m1", "n1", "monitoring", JOB_ID, 1)
    retry = InstanceScope.per_job("m1", "n1", "monitoring", JOB_ID, 2)
    assert (first.instance_id, retry.instance_id) == ("monitoring-subsystem-265ca868", "monitoring-subsystem-265ca868-2")
    assert first.key != retry.key and first.folder != retry.folder and first.name != retry.name
    with pytest.raises(ValueError):
        InstanceScope.per_job("m1", "n1", "monitoring", JOB_ID, 0)


def test_jobs_with_the_same_short_id_still_have_their_own_label():
    first = InstanceScope.per_job("m1", "n1", "simulation", "265ca868-aaaa")
    second = InstanceScope.per_job("m1", "n1", "simulation", "265ca868-bbbb")
    assert first.instance_id == second.instance_id, "the readable name is only the start of the job id"
    assert first.labels != second.labels, "so one job's teardown never removes the other's objects"


def test_the_bound_is_on_the_worker_node_name_so_every_pool_and_the_daemon_fit_whole():
    """K2's ready.deployments names worker-node-<name>; the longest pool name is the design space exploration's."""
    assert WORKER_NODE_NAME_MAX == 28 == KUBERNETES_NAME_MAX - 1 - len("design-space-exploration-subsystem")
    longest = "w" * WORKER_NODE_NAME_MAX
    assert daemon_deployment_name(longest) == f"worker-node-{longest}" and len(daemon_deployment_name(longest)) <= KUBERNETES_NAME_MAX
    for subsystem in Subsystem:
        scope = InstanceScope.pooled("a-control-node-with-a-name-of-sixty-three-characters-0123456789", longest, subsystem.value)
        assert scope.name == f"{longest}-{subsystem_name(subsystem.value)}", "whole, not cut"
        assert DNS_LABEL.match(scope.name)
    run = InstanceScope.per_job("m1", longest, "simulation", JOB_ID, 9999)
    assert run.name == f"{longest}-simulation-subsystem-265ca868-9999", "a run fits whole up to its 9999th attempt"


def test_a_name_past_the_bound_is_cut_and_keeps_a_hash_of_the_whole():
    long_worker_node = "worker-node-with-a-name-far-past-the-bound-of-twenty-eight"
    first = InstanceScope.pooled("m1", long_worker_node, "design_space_exploration")
    second = InstanceScope.pooled("m1", f"{long_worker_node}x", "design_space_exploration")
    assert len(first.name) == KUBERNETES_NAME_MAX and DNS_LABEL.match(first.name)
    assert first.name != second.name, "the hash keeps two long names apart"
    assert kubernetes_name("a" * 100) == kubernetes_name("a" * 100) and kubernetes_name("a" * 100) != kubernetes_name("a" * 101)
    assert kubernetes_name("Kinematic_Sim") == "kinematic-sim" and kubernetes_name("short") == "short"


def test_label_values_keep_their_characters_and_are_cut_like_names():
    assert label_value("job_42-1") == "job_42-1", "an underscore is valid in a label value, so the Docker stack's key stays the same"
    long_key = "j" * 80 + "-1"
    assert len(label_value(long_key)) == KUBERNETES_NAME_MAX and LABEL_VALUE.match(label_value(long_key))
    assert worker_node_selector_labels("n1") == {WORKER_NODE_LABEL: "n1"}


def test_every_derived_name_and_label_is_valid_in_kubernetes():
    scope = InstanceScope.per_job("control-node-a", "3f2b8c1e-6d1a-4b7e-9f00-1234567890ab", "simulation", "8d1c2e3f-aaaa-bbbb-cccc-0123456789ab", 2)
    assert DNS_LABEL.match(scope.name) and len(scope.name) <= KUBERNETES_NAME_MAX
    assert all(LABEL_VALUE.match(value) and len(value) <= KUBERNETES_NAME_MAX for value in scope.labels.values())
    for key in scope.labels:
        assert re.match(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$", key), "label keys without a prefix: letters, digits, dots and hyphens"


def test_a_folder_of_this_worker_nodes_instances_is_told_from_another_worker_nodes():
    assert is_instance_folder("n1-simulation-subsystem-265ca868", "n1")
    assert is_instance_folder("n1-scene-generation-subsystem", "n1")
    assert not is_instance_folder("n1-b-simulation-subsystem-265ca868", "n1"), "worker node n1-b's, though it starts with n1-"
    assert not is_instance_folder("n2-simulation-subsystem-265ca868", "n1") and not is_instance_folder("n1-something-else", "n1")


def test_two_worker_nodes_and_two_instances_never_share_a_name():
    scopes = [
        InstanceScope.pooled("m1", "n1", "scene_generation"),
        InstanceScope.pooled("m1", "n2", "scene_generation"),
        InstanceScope.pooled("m1", "n1", "trajectory_generation"),
        InstanceScope.per_job("m1", "n1", "simulation", "a"),
        InstanceScope.per_job("m1", "n1", "monitoring", "a"),
    ]
    assert len({scope.name for scope in scopes}) == len(scopes)
    assert len({scope.folder for scope in scopes}) == len(scopes)
    assert len({tuple(sorted(scope.labels.items())) for scope in scopes[:3]}) == 3, "a pool's labels are its own; a job's are its job's, whichever subsystem runs it"


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


@pytest.mark.parametrize("control_node_id, worker_node_id, instance_id", [("M1", "n1", "x"), ("m1", "n/1", "x"), ("m1", "n1", "+"), ("m1", "", "x"), ("-m", "n1", "x")])
def test_invalid_ids_are_rejected(control_node_id, worker_node_id, instance_id):
    with pytest.raises(ValueError):
        InstanceScope(control_node_id, worker_node_id, instance_id)


def test_an_overlong_scope_still_has_a_valid_name_and_label():
    scope = InstanceScope("m1", "n1", "x" * 200)
    assert len(scope.name) == KUBERNETES_NAME_MAX and DNS_LABEL.match(scope.name)
    assert len(scope.labels[INSTANCE_LABEL]) == KUBERNETES_NAME_MAX and LABEL_VALUE.match(scope.labels[INSTANCE_LABEL])


def test_safe_id_maps_any_string_to_scope_characters():
    assert safe_id("Job 7/Attempt#2") == "job-7-attempt-2"
    with pytest.raises(ValueError):
        safe_id("///")


# The Docker names of a run's compose stack (launchers/per_job/job_stack.py), until a run is a pod


def test_a_runs_compose_stack_keeps_its_docker_names():
    scope = InstanceScope.per_job("m1", "n1", "simulation", JOB_ID)
    assert worker_node_project("m1", "n1") == scope.compose_project == "scenegems-m1-n1"
    assert scope.docker_name == "scenegems-m1-n1-simulation-subsystem-265ca868"
    assert scope.container_name("kinematic_sim") == "scenegems-m1-n1-simulation-subsystem-265ca868-kinematic-sim", "one spelling: hyphens"
    assert scope.service_key("vessel_0_asv_system") == "simulation-subsystem-265ca868-vessel-0-asv-system", "unique in the worker node's project"
    assert scope.network_name("net") == "scenegems-m1-n1-simulation-subsystem-265ca868-net"
    for name in (scope.docker_name, scope.container_name("vessel_1"), scope.network_name("net"), scope.service_key("vessel_1")):
        assert DOCKER_NAME.match(name), name


def test_every_instance_belongs_to_a_worker_node():
    """The control node runs no instance: there is no live session scope with a topic prefix of its own."""
    assert not hasattr(InstanceScope, "live_session")
    for scope in (InstanceScope.pooled("m1", "n1", "monitoring"), InstanceScope.per_job("m1", "n1", "simulation", JOB_ID)):
        assert scope.labels[WORKER_NODE_LABEL] == "n1" and not hasattr(scope, "topic_prefix")
