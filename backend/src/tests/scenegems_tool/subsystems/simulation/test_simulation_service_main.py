"""The simulation subsystem's start: the runs earlier processes left behind are removed, and nothing else of the worker node or the cluster."""

import pytest
from kubernetes.client.exceptions import ApiException

from scenegems_tool.cluster.worker_node.instance_scope import InstanceScope
from scenegems_tool.cluster.worker_node.launchers.kubernetes_api import Kind
from scenegems_tool.cluster.worker_node.launchers.per_job.run_pod import RUN_COMPONENT, RUN_COMPONENT_LABEL
from scenegems_tool.subsystems.simulation import simulation_service_main
from scenegems_tool.subsystems.simulation.simulation_service_main import remove_leftover_stacks
from tests.scenegems_tool.cluster.worker_node.fake_kubernetes import FakeCluster


def run_labels(worker_node_id: str, job_id: str) -> dict:
    return {**InstanceScope.per_job("m1", worker_node_id, "simulation", job_id).labels, RUN_COMPONENT_LABEL: RUN_COMPONENT}


@pytest.fixture
def cluster() -> FakeCluster:
    """Two runs of worker node n1 with a ground control service, the pods of its pools, and a run of worker node n2."""
    cluster = FakeCluster()
    for name, labels in {
        "n1-simulation-subsystem-joba": run_labels("n1", "job-a"),
        "n1-simulation-subsystem-jobb-2": run_labels("n1", "job-b"),
        "n1-simulation-subsystem-5d8f9-x2x7q": InstanceScope.pooled("m1", "n1", "simulation").labels,
        "n1-monitoring-subsystem-7c4b8-k9p2m": InstanceScope.pooled("m1", "n1", "monitoring").labels,
        "n2-simulation-subsystem-jobc": run_labels("n2", "job-c"),
    }.items():
        cluster.add(Kind.POD, {"metadata": {"name": name, "labels": labels}, "spec": {"containers": [{"name": "c"}]}})
    cluster.add(Kind.SERVICE, {"metadata": {"name": "gcs-n1-simulation-subsystem-joba-0", "labels": run_labels("n1", "job-a")}, "spec": {"ports": [{"port": 12200}]}})
    cluster.add(Kind.SERVICE, {"metadata": {"name": "cluster-broker", "labels": {"app.kubernetes.io/name": "cluster-broker"}}, "spec": {"ports": [{"port": 1883}]}})
    return cluster


def test_the_runs_of_earlier_processes_are_removed_by_their_labels_and_their_folders_by_their_names(cluster, tmp_path):
    for folder in (
        "n1-simulation-subsystem-joba",
        "n1-simulation-subsystem-jobb-2",
        "n1-simulation-subsystem",
        "n1-scene-generation-subsystem",
        "n2-simulation-subsystem-jobc",
    ):
        (tmp_path / folder / "gen").mkdir(parents=True)
    assert remove_leftover_stacks(cluster.api(), "m1", "n1", str(tmp_path)) == ["n1-simulation-subsystem-joba", "n1-simulation-subsystem-jobb-2"]
    assert cluster.names(Kind.POD) == [
        "n1-monitoring-subsystem-7c4b8-k9p2m",
        "n1-simulation-subsystem-5d8f9-x2x7q",
        "n2-simulation-subsystem-jobc",
    ], "its own pod, the pools and other worker nodes stay"
    assert cluster.names(Kind.SERVICE) == ["cluster-broker"]
    assert {folder.name for folder in tmp_path.iterdir()} == {
        "n2-simulation-subsystem-jobc",
        "n1-scene-generation-subsystem",
        "n1-simulation-subsystem",
    }, "its own folder, the other pools and other worker nodes stay"


def test_a_cluster_api_that_fails_leaves_the_runs_to_the_daemon_and_the_folders_still_go(cluster, tmp_path, caplog):
    (tmp_path / "n1-simulation-subsystem-joba").mkdir()
    cluster.fail_next["delete"] = ApiException(status=403, reason="Forbidden")
    assert remove_leftover_stacks(cluster.api(), "m1", "n1", str(tmp_path)) == []
    assert "Cannot remove the leftover runs of n1-simulation-subsystem" in caplog.text
    assert not any(tmp_path.iterdir())


def test_without_a_cluster_or_without_the_folder_there_is_nothing_to_remove(tmp_path):
    assert remove_leftover_stacks(None, "m1", "n1", str(tmp_path / "missing")) == []


def test_the_container_cleans_up_before_it_serves(monkeypatch):
    order = []
    monkeypatch.setenv("SCENEGEMS_CONTROL_NODE_ID", "m1")
    monkeypatch.setenv("SCENEGEMS_WORKER_NODE_ID", "n1")
    monkeypatch.setattr(simulation_service_main, "cluster_api", lambda: "api")
    monkeypatch.setattr(simulation_service_main, "remove_leftover_stacks", lambda api, control_node_id, worker_node_id: order.append(("clean", api, control_node_id, worker_node_id)))
    monkeypatch.setattr(simulation_service_main, "service_from_environment", lambda service_class, name: (service_class.__name__, name))
    monkeypatch.setattr(simulation_service_main, "serve", lambda service: order.append(("serve", *service)))
    simulation_service_main.main()
    assert order == [("clean", "api", "m1", "n1"), ("serve", "MqttSimulationService", "simulation-subsystem")]


def test_outside_a_pod_the_subsystem_has_no_cluster_api(monkeypatch, caplog):
    monkeypatch.delenv("KUBECONFIG", raising=False)
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    monkeypatch.setenv("SCENEGEMS_KUBERNETES_NAMESPACE", "scenegems")
    assert simulation_service_main.cluster_api() is None and "No cluster API for the simulation subsystem" in caplog.text
    monkeypatch.delenv("SCENEGEMS_KUBERNETES_NAMESPACE")
    assert simulation_service_main.cluster_api() is None
