"""The cluster API client against a fake of the client's API groups: what it sends, and how it reads the answers."""

import pytest
from kubernetes.client.exceptions import ApiException

from scenegems_tool.cluster.worker_node.launchers import kubernetes_api
from scenegems_tool.cluster.worker_node.launchers.kubernetes_api import ContainerState, Kind, KubernetesApi, KubernetesUnavailable, OwnerReference, label_selector
from tests.scenegems_tool.cluster.worker_node.fake_kubernetes import FakeCluster


def deployment(name: str, labels=None) -> dict:
    labels = labels or {"app": name}
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "labels": labels},
        "spec": {"replicas": 1, "selector": {"matchLabels": labels}, "template": {"metadata": {"labels": labels}, "spec": {"containers": [{"name": "c", "image": "busybox:1.37"}]}}},
    }


def service(name: str, port: int = 1883) -> dict:
    return {"apiVersion": "v1", "kind": "Service", "metadata": {"name": name}, "spec": {"type": "NodePort", "selector": {"app": name}, "ports": [{"port": port, "targetPort": 1883}]}}


@pytest.fixture
def cluster() -> FakeCluster:
    return FakeCluster()


@pytest.fixture
def api(cluster) -> KubernetesApi:
    return cluster.api("lab")


def test_a_deployment_is_created_and_then_replaced_under_its_name(cluster, api):
    api.apply_deployment(deployment("pool"))
    assert cluster.get(Kind.DEPLOYMENT, "pool", "lab")["spec"]["replicas"] == 1
    uid = cluster.get(Kind.DEPLOYMENT, "pool", "lab")["metadata"]["uid"]
    changed = deployment("pool")
    changed["spec"]["template"]["spec"]["containers"][0]["image"] = "busybox:1.38"
    api.apply_deployment(changed)
    held = cluster.get(Kind.DEPLOYMENT, "pool", "lab")
    assert held["spec"]["template"]["spec"]["containers"][0]["image"] == "busybox:1.38" and held["metadata"]["uid"] == uid, "the same object, replaced"
    assert [verb for kind, verb, name in cluster.calls] == ["create", "create", "read", "replace"]
    assert cluster.names(Kind.DEPLOYMENT, "default") == [], "everything in the client's namespace"


def test_a_failure_other_than_a_name_in_use_is_not_hidden(cluster, api):
    cluster.fail_next["create"] = ApiException(status=403, reason="Forbidden")
    with pytest.raises(ApiException) as failure:
        api.apply_deployment(deployment("pool"))
    assert failure.value.status == 403 and cluster.get(Kind.DEPLOYMENT, "pool", "lab") is None


def test_a_deployment_is_read_its_availability_comes_from_its_status_and_absence_is_none(cluster, api):
    assert api.read_deployment("pool") is None and not api.deployment_available("pool")
    api.apply_deployment(deployment("pool"))
    assert api.read_deployment("pool").metadata.name == "pool"
    assert not api.deployment_available("pool"), "no status yet: its pod is not ready"
    cluster.set_available("pool", namespace="lab")
    assert api.deployment_available("pool")
    cluster.fail_next["read"] = ApiException(status=500, reason="boom")
    with pytest.raises(ApiException):
        api.read_deployment("pool")


def test_a_deployment_is_deleted_in_the_background_and_a_missing_one_is_no_error(cluster, api):
    api.apply_deployment(deployment("pool"))
    assert api.delete_deployment("pool") and cluster.get(Kind.DEPLOYMENT, "pool", "lab") is None
    assert cluster.deletions[-1] == {"kind": "Deployment", "name": "pool", "propagation_policy": "Background"}, "its replica sets and pods go after it"
    assert not api.delete_deployment("pool")


def test_an_owner_reference_names_the_deployment_by_its_uid(cluster, api):
    held = cluster.add(Kind.DEPLOYMENT, deployment("worker-node-n1"), "lab")
    reference = api.owner_reference("worker-node-n1")
    assert reference == OwnerReference("apps/v1", "Deployment", "worker-node-n1", held["metadata"]["uid"])
    assert reference.to_manifest() == {"apiVersion": "apps/v1", "kind": "Deployment", "name": "worker-node-n1", "uid": held["metadata"]["uid"]}, "not blocking: that would need a right on the owner"
    with pytest.raises(LookupError, match="worker-node-n2"):
        api.owner_reference("worker-node-n2")


def test_pods_are_created_and_deleted_with_a_grace_period(cluster, api):
    api.create_pod({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "run"}, "spec": {"containers": [{"name": "c", "image": "busybox:1.37"}]}})
    assert cluster.names(Kind.POD, "lab") == ["run"]
    assert api.delete_pod("run", grace_period_s=3)
    assert cluster.deletions[-1] == {"kind": "Pod", "name": "run", "propagation_policy": "Background", "grace_period_seconds": 3}
    assert not api.delete_pod("run")


def test_a_service_is_applied_keeping_its_cluster_ip_and_gives_its_node_port(cluster, api):
    api.apply_service(service("broker"))
    ip = cluster.get(Kind.SERVICE, "broker", "lab")["spec"]["clusterIP"]
    assert api.node_port("broker", 1883) is None, "none given yet"
    cluster.set_node_port("broker", 1883, 31883, namespace="lab")
    assert api.node_port("broker", 1883) == 31883 and api.node_port("broker", 8443) is None and api.node_port("other", 1883) is None
    api.apply_service(service("broker"))
    assert cluster.get(Kind.SERVICE, "broker", "lab")["spec"]["clusterIP"] == ip, "the cluster IP of a service cannot change"
    assert api.delete_service("broker") and not api.delete_service("broker")


def test_objects_are_found_and_deleted_by_label(cluster, api):
    for name, labels in (("a", {"scenegems.instance": "x", "scenegems.worker-node": "n1"}), ("b", {"scenegems.worker-node": "n1"}), ("c", {"scenegems.instance": "y", "scenegems.worker-node": "n2"})):
        api.apply_deployment(deployment(name, labels))
    selector = label_selector({"scenegems.worker-node": "n1"}, present=["scenegems.instance"])
    assert selector == "scenegems.worker-node=n1,scenegems.instance"
    assert api.names(Kind.DEPLOYMENT, selector) == ["a"]
    assert api.names(Kind.DEPLOYMENT, label_selector({"scenegems.worker-node": "n1"})) == ["a", "b"]
    assert api.delete_labelled(Kind.DEPLOYMENT, selector) == ["a"] and cluster.names(Kind.DEPLOYMENT, "lab") == ["b", "c"]
    assert api.delete_labelled(Kind.POD, selector) == [] and api.delete_labelled(Kind.SERVICE, selector) == []


def test_without_a_pod_or_a_kubeconfig_there_is_no_cluster_to_talk_to():
    """kubectl without a kubeconfig talks to 127.0.0.1:8080, which may be any program: the client never guesses."""
    with pytest.raises(KubernetesUnavailable, match="KUBECONFIG"):
        KubernetesApi.connect("lab", environ={})


def test_a_kubeconfig_names_the_cluster_and_the_namespace_is_the_clients(tmp_path):
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text(
        "apiVersion: v1\nkind: Config\ncurrent-context: lab\n"
        "clusters: [{name: lab, cluster: {server: 'https://127.0.0.1:6550', insecure-skip-tls-verify: true}}]\n"
        "users: [{name: lab, user: {token: abc}}]\n"
        "contexts: [{name: lab, context: {cluster: lab, user: lab}}]\n",
        encoding="utf-8",
    )
    by_variable = KubernetesApi.connect("scenegems", environ={"KUBECONFIG": str(kubeconfig), "KUBERNETES_SERVICE_HOST": "10.43.0.1"})
    assert by_variable.namespace == "scenegems"
    assert by_variable._apps.api_client.configuration.host == "https://127.0.0.1:6550", "a named kubeconfig wins, also in a pod"
    assert KubernetesApi.connect("scenegems", kubeconfig=str(kubeconfig), environ={})._core.api_client.configuration.host == "https://127.0.0.1:6550"


def test_in_a_pod_the_pods_service_account_is_used(monkeypatch):
    from kubernetes import config

    loaded = []

    def load_incluster_config(client_configuration):
        client_configuration.host = "https://10.43.0.1:443"
        loaded.append(True)

    monkeypatch.setattr(config, "load_incluster_config", load_incluster_config)
    api = KubernetesApi.connect("scenegems", environ={"KUBERNETES_SERVICE_HOST": "10.43.0.1"})
    assert loaded and api._apps.api_client.configuration.host == "https://10.43.0.1:443"
    assert kubernetes_api.IN_CLUSTER_VARIABLE == "KUBERNETES_SERVICE_HOST"


# Pods: their state and their log (a run's pod)


def run_pod_manifest(name: str = "run") -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": name},
        "spec": {"initContainers": [{"name": "sim", "image": "sim", "restartPolicy": "Always"}], "containers": [{"name": "runner", "image": "runner"}]},
    }


def test_a_pod_is_created_with_its_uid_read_and_referenced_as_an_owner(cluster, api):
    created = api.create_pod(run_pod_manifest())
    assert created.metadata.uid and api.read_pod("run").metadata.uid == created.metadata.uid
    assert api.read_pod("other") is None
    assert api.pod_owner_reference("run") == OwnerReference("v1", "Pod", "run", created.metadata.uid)
    with pytest.raises(LookupError, match="There is no pod other in namespace lab"):
        api.pod_owner_reference("other")


def test_the_state_of_a_regular_container_and_of_a_sidecar_is_read_from_the_pods_status(cluster, api):
    api.create_pod(run_pod_manifest())
    assert kubernetes_api.container_state(api.read_pod("run"), "runner") is None, "no status yet"
    cluster.set_container_state("run", "sim", "running", namespace="lab", restarts=2)
    cluster.set_container_state("run", "runner", "waiting", namespace="lab", reason="PodInitializing")
    states = kubernetes_api.container_states(api.read_pod("run"))
    assert states == {"sim": ContainerState("running", restarts=2), "runner": ContainerState("waiting", "PodInitializing")}
    assert states["sim"].started and not states["runner"].started
    cluster.set_container_state("run", "runner", "terminated", namespace="lab", exitCode=3, reason="Error", message="boom")
    runner = kubernetes_api.container_state(api.read_pod("run"), "runner")
    assert runner == ContainerState("terminated", "Error", "boom", 3) and runner.started


def test_a_containers_log_is_followed_line_by_line_across_its_chunks(cluster, api):
    api.create_pod(run_pod_manifest())
    cluster.add_log("run", "runner", ["first line, longer than a chunk", "", "third\r", "ünïcode"])
    assert list(api.follow_log("run", "runner", timestamps=True, since_seconds=12.7)) == ["first line, longer than a chunk", "", "third", "ünïcode"]
    assert cluster.log_calls == [{"name": "run", "container": "runner", "follow": True, "timestamps": True, "since_seconds": 12, "_preload_content": False}]


def test_a_log_whose_connection_breaks_gives_its_lines_then_the_error_and_lets_go_of_the_connection(cluster, api, monkeypatch):
    api.create_pod(run_pod_manifest())
    cluster.add_log("run", "runner", ["one", "two"], ConnectionResetError("gone"))
    responses = []
    original = cluster.read_log
    monkeypatch.setattr(cluster, "read_log", lambda *args, **options: responses.append(original(*args, **options)) or responses[-1])
    lines = []
    with pytest.raises(ConnectionResetError):
        for line in api.follow_log("run", "runner"):
            lines.append(line)
    assert lines == ["one", "two"] and responses[0].released


def test_an_api_error_is_told_from_any_other_error():
    assert kubernetes_api.api_error(ApiException(status=403, reason="Forbidden")) == "403 Forbidden"
    assert kubernetes_api.api_error(ConnectionResetError("gone")) is None
