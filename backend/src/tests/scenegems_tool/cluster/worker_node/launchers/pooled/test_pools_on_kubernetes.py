"""Pools in a real cluster (k3d): the launcher runs in the test process with the daemon's service account, as the daemon's pod would run it.

Needs k3d, kubectl, Docker and the images (tests/.../worker_node/k3d_cluster.py says which). A pool's pod reaches
the broker by its service name, the test process by the node port on 127.0.0.1.
"""

import queue
import threading

import paho.mqtt.client as mqtt
import pytest

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.daemon.worker_node_runtime import remove_leftover_instances
from scenegems_tool.cluster.worker_node.instance_scope import INSTANCE_LABEL, WORKER_NODE_LABEL
from scenegems_tool.cluster.worker_node.launchers.kubernetes_api import label_selector
from scenegems_tool.cluster.worker_node.subsystem import Subsystem

pytestmark = pytest.mark.kubernetes

AVAILABLE_S = 240  # a pool's pod starts and gets ready


def heartbeats(cluster, topic: str):
    """The heartbeats published on a pool's topic from now on, and the client that receives them."""
    received: "queue.Queue[str]" = queue.Queue()
    connected = threading.Event()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = lambda client, userdata, flags, reason, properties: (client.subscribe(f"{topic}/heartbeat"), connected.set())
    client.on_message = lambda client, userdata, message: received.put(message.topic)
    client.connect("127.0.0.1", cluster.broker_port)
    client.loop_start()
    assert connected.wait(30), "the test process reaches the broker on its node port"
    return received, client


def pool_pods(cluster, pool):
    return cluster.pods(label_selector(dict(pool.names.labels)))


def test_a_pool_started_by_the_launcher_becomes_available_on_the_worker_nodes_node_and_heartbeats(k3d_cluster, k3d_worker_node):
    worker_node = k3d_worker_node({JobType.MONITORING_POST_HOC: 2})
    pool = worker_node.pools.get(Subsystem.MONITORING)
    received, client = heartbeats(k3d_cluster, pool.service_topic)
    try:
        k3d_cluster.wait_for(pool.is_available, AVAILABLE_S, "the monitoring pool available")
        assert received.get(timeout=60) == f"{pool.service_topic}/heartbeat", "under the name the launcher gave it"
    finally:
        client.loop_stop()
        client.disconnect()
    deployment = k3d_cluster.json("deployment", pool.names.deployment)
    assert deployment["metadata"]["ownerReferences"][0]["name"] == f"worker-node-{worker_node.worker_node_id}"
    assert deployment["metadata"]["labels"] == {INSTANCE_LABEL: "monitoring-subsystem", WORKER_NODE_LABEL: worker_node.worker_node_id}
    [pod] = pool_pods(k3d_cluster, pool)
    assert pod["spec"]["nodeName"] == k3d_cluster.node and pod["spec"]["containers"][0]["image"] == k3d_cluster.images()["MONITORING_IMAGE"]
    assert pod["spec"]["containers"][0]["resources"]["limits"]["cpu"] == "3"


def test_a_pool_whose_pod_is_killed_comes_back_without_the_launcher(k3d_cluster, k3d_worker_node):
    worker_node = k3d_worker_node({JobType.SCENE_GENERATION: 1})
    pool = worker_node.pools.get(Subsystem.SCENE_GENERATION)
    k3d_cluster.wait_for(pool.is_available, AVAILABLE_S, "the scene generation pool available")
    [first] = pool_pods(k3d_cluster, pool)
    k3d_cluster.kubectl_run("delete", "pod", first["metadata"]["name"], "-n", k3d_cluster.namespace, "--grace-period=0", "--force", "--wait=false")
    assert pool.is_running() and worker_node.check_pools() == [], "the Deployment is there: Kubernetes, not the launcher, starts the pod again"

    def replaced() -> bool:
        pods = [pod for pod in pool_pods(k3d_cluster, pool) if pod["metadata"]["name"] != first["metadata"]["name"] and not pod["metadata"].get("deletionTimestamp")]
        return bool(pods) and pool.is_available()

    k3d_cluster.wait_for(replaced, AVAILABLE_S, "a new pod of the pool")
    assert worker_node.pools.get(Subsystem.SCENE_GENERATION) is pool


def test_a_pool_whose_deployment_is_gone_is_applied_again_by_the_launcher(k3d_cluster, k3d_worker_node):
    worker_node = k3d_worker_node({JobType.SCENE_GENERATION: 1})
    pool = worker_node.pools.get(Subsystem.SCENE_GENERATION)
    k3d_cluster.wait_for(pool.is_available, AVAILABLE_S, "the scene generation pool available")
    k3d_cluster.kubectl_run("delete", "deployment", pool.names.deployment, "-n", k3d_cluster.namespace)
    assert worker_node.check_pools() == [Subsystem.SCENE_GENERATION]
    again = worker_node.pools.get(Subsystem.SCENE_GENERATION)
    assert again is not pool and again.names.deployment == pool.names.deployment
    k3d_cluster.wait_for(again.is_available, AVAILABLE_S, "the pool applied again available")


def test_removing_the_worker_nodes_deployment_removes_its_pools(k3d_cluster, k3d_worker_node):
    """The pools are owned by the daemon's Deployment: a worker node removed from the chart takes them with it."""
    worker_node = k3d_worker_node({JobType.DESIGN_SPACE_EXPLORATION: 1, JobType.MONITORING_POST_HOC: 1})
    worker_node.components = frozenset({"design_space_exploration", "monitoring"})
    worker_node.start_pools()
    exploration, monitoring = worker_node.pools.get(Subsystem.DESIGN_SPACE_EXPLORATION), worker_node.pools.get(Subsystem.MONITORING)
    k3d_cluster.wait_for(
        lambda: exploration.api.read_deployment(exploration.names.deployment) is not None and monitoring.api.read_deployment(monitoring.names.deployment) is not None, 60, "both Deployments applied"
    )
    k3d_cluster.kubectl_run("delete", "deployment", f"worker-node-{worker_node.worker_node_id}", "-n", k3d_cluster.namespace)
    selector = label_selector({WORKER_NODE_LABEL: worker_node.worker_node_id}, present=[INSTANCE_LABEL])
    k3d_cluster.wait_for(lambda: not k3d_cluster.json("deployments", "-l", selector)["items"], 120, "the pools' Deployments collected with their owner")
    k3d_cluster.wait_for(lambda: not k3d_cluster.pods(selector), 120, "the pools' pods gone")


def test_a_new_daemon_process_removes_what_an_earlier_one_left_and_nothing_else(k3d_cluster, k3d_worker_node):
    earlier = k3d_worker_node({JobType.SCENE_GENERATION: 1, JobType.MONITORING_POST_HOC: 1})
    other = k3d_worker_node({JobType.MONITORING_POST_HOC: 1})
    earlier.components = frozenset({"scene_generation", "monitoring"})
    earlier.start_pools()
    other_pool = other.pools.get(Subsystem.MONITORING)
    mine = label_selector({WORKER_NODE_LABEL: earlier.worker_node_id}, present=[INSTANCE_LABEL])
    k3d_cluster.wait_for(lambda: len(k3d_cluster.pods(mine)) == 2 and other_pool.api.read_deployment(other_pool.names.deployment) is not None, AVAILABLE_S, "the pools' pods created")
    # The earlier process is gone without a word: what it started stays in the cluster until its successor starts
    removed = remove_leftover_instances(earlier.kubernetes, earlier.worker_node_id, instances_folder="/nonexistent")
    assert sorted(entry for entry in removed if entry.startswith("Deployment")) == sorted(
        f"Deployment {earlier.worker_node_id}-{name}" for name in ("scene-generation-subsystem", "monitoring-subsystem")
    )
    assert any(entry.startswith("Pod ") for entry in removed), "its pods go at once, not only with their Deployments"
    k3d_cluster.wait_for(lambda: not k3d_cluster.pods(mine), 120, "the leftover pods gone")
    assert k3d_cluster.json("deployment", f"worker-node-{earlier.worker_node_id}")["metadata"]["name"], "the daemon's own Deployment stays"
    assert other_pool.api.read_deployment(other_pool.names.deployment) is not None, "another worker node's pool stays"


def test_the_daemons_service_account_has_exactly_the_rights_of_the_chart(k3d_cluster):
    allowed = [
        ("create", "deployments"),
        ("get", "deployments"),
        ("list", "deployments"),
        ("update", "deployments"),
        ("delete", "deployments"),
        ("list", "pods"),
        ("delete", "pods"),
        ("list", "services"),
        ("delete", "services"),
    ]
    denied = [("create", "pods"), ("get", "pods/log"), ("create", "services"), ("get", "secrets"), ("list", "configmaps"), ("patch", "deployments"), ("create", "roles")]
    assert [right for right in allowed if not k3d_cluster.can_i("worker-node", *right)] == []
    assert [right for right in denied if k3d_cluster.can_i("worker-node", *right)] == []
    assert not k3d_cluster.can_i("worker-node", "list", "deployments", namespace="default"), "its namespace only"
    assert k3d_cluster.can_i("simulation-subsystem", "create", "pods") and k3d_cluster.can_i("simulation-subsystem", "get", "pods/log")
    assert not k3d_cluster.can_i("simulation-subsystem", "create", "deployments")


def test_in_its_pod_the_daemon_reaches_the_cluster_api_with_its_service_account(k3d_cluster):
    """The worker node image without Docker: the client connects in the pod (no kubeconfig) and lists by label with the account's rights."""
    script = (
        "from scenegems_tool.cluster.worker_node.launchers.kubernetes_api import KubernetesApi, Kind\n"
        f"api = KubernetesApi.connect('{k3d_cluster.namespace}')\n"
        "print('deployments', api.names(Kind.DEPLOYMENT, 'app.kubernetes.io/name=cluster-broker'))\n"
        "import shutil; print('docker', shutil.which('docker'))\n"
    )
    pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": "daemon-in-a-pod", "namespace": k3d_cluster.namespace},
        "spec": {
            "serviceAccountName": "worker-node",
            "restartPolicy": "Never",
            "containers": [{"name": "daemon", "image": k3d_cluster.images()["WORKER_NODE"], "imagePullPolicy": "IfNotPresent", "command": ["python", "-c", script]}],
        },
    }
    k3d_cluster.apply([pod])

    def finished() -> bool:
        statuses = k3d_cluster.json("pod", "daemon-in-a-pod").get("status", {}).get("containerStatuses") or []
        return bool(statuses) and "terminated" in (statuses[0].get("state") or {})

    k3d_cluster.wait_for(finished, AVAILABLE_S, "the daemon's pod finished")
    status = k3d_cluster.json("pod", "daemon-in-a-pod")["status"]["containerStatuses"][0]["state"]["terminated"]
    log = k3d_cluster.kubectl_run("logs", "daemon-in-a-pod", "-n", k3d_cluster.namespace).stdout
    k3d_cluster.kubectl_run("delete", "pod", "daemon-in-a-pod", "-n", k3d_cluster.namespace, "--wait=false")
    assert status["exitCode"] == 0, log
    assert "deployments ['cluster-broker']" in log and "docker None" in log, log
