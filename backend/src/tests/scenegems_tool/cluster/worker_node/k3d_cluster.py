"""A k3d cluster for the tests marked kubernetes: the namespace, the service accounts and roles of the chart, the cluster broker and the images.

What it needs on the machine: Docker, kubectl on the PATH, k3d on the PATH or named by SCENEGEMS_K3D, and the images
of the tag in SCENEGEMS_TEST_IMAGE_TAG (latest by default): the broker, the subsystems the tests start and the worker
node image. It creates a cluster of its own (one server, no load balancer, Traefik and the service load balancer
off), with its API and the broker's node port on 127.0.0.1 only, imports the images by tag, and deletes the cluster
at the end. With SCENEGEMS_TEST_K3D_CLUSTER set, the cluster of that name is used, created first when there is none,
and kept, so a second run skips the start; its namespace is still the run's own and deleted at the end.

Every kubectl call names the cluster's kubeconfig: kubectl without one talks to 127.0.0.1:8080, which can be any
program on the machine. On a host with cgroup version 1 the kubelet needs fail-cgroupv1=false, which is passed when
Docker reports that version.

The rights are the ones the chart has to give (written down in the design log, K3 results): the daemon's service
account worker-node, and the simulation subsystem's simulation-subsystem. The tests run the launcher in the test
process with a kubeconfig of the worker-node service account, so what the launcher does is checked against those
rights and nothing more.
"""

import json
import os
import random
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

K3D_VARIABLE = "SCENEGEMS_K3D"
CLUSTER_VARIABLE = "SCENEGEMS_TEST_K3D_CLUSTER"
IMAGE_TAG_VARIABLE = "SCENEGEMS_TEST_IMAGE_TAG"
NODE_PORTS = (30000, 32767)  # Kubernetes' default node port range
BROKER = "cluster-broker"
WORKER_NODE_ACCOUNT = "worker-node"
SIMULATION_ACCOUNT = "simulation-subsystem"
START_TIMEOUT_S = 300

# The rules of the chart's two roles (K5 copies them into rbac.yaml)
WORKER_NODE_RULES = [
    {"apiGroups": ["apps"], "resources": ["deployments"], "verbs": ["get", "list", "create", "update", "delete"]},
    {"apiGroups": [""], "resources": ["pods", "services"], "verbs": ["list", "delete"]},
]
SIMULATION_RULES = [
    {"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list", "watch", "create", "delete"]},
    {"apiGroups": [""], "resources": ["pods/log"], "verbs": ["get"]},
    {"apiGroups": [""], "resources": ["services"], "verbs": ["get", "list", "create", "update", "delete"]},
]


class K3dUnavailable(RuntimeError):
    pass


def k3d_executable() -> str:
    named = os.environ.get(K3D_VARIABLE, "").strip()
    if named:
        if not Path(named).is_file():
            raise K3dUnavailable(f"{K3D_VARIABLE}={named} names no file")
        return named
    found = shutil.which("k3d")
    if found is None:
        raise K3dUnavailable(f"k3d is needed for the tests marked kubernetes: put it on the PATH or name it with {K3D_VARIABLE} (k3d 5.9.0 was used)")
    return found


def kubectl_executable() -> str:
    found = shutil.which("kubectl")
    if found is None:
        raise K3dUnavailable("kubectl is needed for the tests marked kubernetes: put it on the PATH")
    return found


def free_local_port(low: int = 1024, high: int = 65535) -> int:
    """A port free on 127.0.0.1 between low and high."""
    for _ in range(200):
        port = random.randint(low, high)
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No free port between {low} and {high} on 127.0.0.1")


def _run(arguments: List[str], *, input_text: Optional[str] = None, timeout_s: float = START_TIMEOUT_S, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(arguments, input=input_text, capture_output=True, text=True, timeout=timeout_s)
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(arguments[:3])} failed ({result.returncode}): {result.stderr.strip() or result.stdout.strip()}")
    return result


@dataclass
class K3dCluster:
    name: str
    k3d: str
    kubectl: str
    folder: Path  # holds the kubeconfigs
    namespace: str
    broker_port: int  # the broker's service port, node port and local port on 127.0.0.1
    image_tag: str
    keep: bool  # a named cluster is kept after the run
    node: str = ""
    kubeconfig: Path = field(init=False)
    worker_node_kubeconfig: Path = field(init=False)

    def __post_init__(self) -> None:
        self.kubeconfig = self.folder / "admin.kubeconfig"
        self.worker_node_kubeconfig = self.folder / "worker-node.kubeconfig"

    # kubectl

    def kubectl_run(self, *arguments: str, input_text: Optional[str] = None, check: bool = True, timeout_s: float = 120) -> subprocess.CompletedProcess:
        return _run([self.kubectl, "--kubeconfig", str(self.kubeconfig), *arguments], input_text=input_text, check=check, timeout_s=timeout_s)

    def apply(self, documents: List[dict]) -> None:
        self.kubectl_run("apply", "-f", "-", input_text=yaml.safe_dump_all(documents))

    def json(self, *arguments: str) -> dict:
        return json.loads(self.kubectl_run("get", "-n", self.namespace, *arguments, "-o", "json").stdout)

    def can_i(self, account: str, verb: str, resource: str, namespace: Optional[str] = None) -> bool:
        result = self.kubectl_run("auth", "can-i", verb, resource, "-n", namespace or self.namespace, "--as", f"system:serviceaccount:{self.namespace}:{account}", check=False)
        return result.stdout.strip() == "yes"

    # Setting up

    def start(self) -> None:
        if not self._exists():
            self._create()
        self.kubeconfig.write_text(_run([self.k3d, "kubeconfig", "get", self.name]).stdout, encoding="utf-8")
        nodes = json.loads(self.kubectl_run("get", "nodes", "-o", "json").stdout)["items"]
        self.node = nodes[0]["metadata"]["name"]
        self._namespace_and_rights()
        self._import_images()
        self._broker()
        self._worker_node_kubeconfig()

    def _exists(self) -> bool:
        listing = json.loads(_run([self.k3d, "cluster", "list", "-o", "json"]).stdout or "[]")
        return any(cluster.get("name") == self.name for cluster in listing)

    def _create(self) -> None:
        arguments = [
            self.k3d,
            "cluster",
            "create",
            self.name,
            "--servers",
            "1",
            "--agents",
            "0",
            "--no-lb",
            "--api-port",
            f"127.0.0.1:{free_local_port()}",
            "--port",
            f"127.0.0.1:{self.broker_port}:{self.broker_port}@server:0:direct",  # no load balancer: straight onto the server node
            "--k3s-arg",
            "--disable=traefik@server:0",
            "--k3s-arg",
            "--disable=servicelb@server:0",
            "--kubeconfig-update-default=false",
            "--kubeconfig-switch-context=false",
            "--wait",
            "--timeout",
            f"{START_TIMEOUT_S}s",
        ]
        if _run(["docker", "info", "--format", "{{.CgroupVersion}}"]).stdout.strip() == "1":
            arguments += ["--k3s-arg", "--kubelet-arg=fail-cgroupv1=false@server:*"]
        _run(arguments, timeout_s=START_TIMEOUT_S + 60)

    def _namespace_and_rights(self) -> None:
        documents: List[dict] = [{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": self.namespace}}]
        for account, rules in ((WORKER_NODE_ACCOUNT, WORKER_NODE_RULES), (SIMULATION_ACCOUNT, SIMULATION_RULES)):
            metadata = {"name": account, "namespace": self.namespace}
            documents += [
                {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": metadata},
                {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "Role", "metadata": metadata, "rules": rules},
                {
                    "apiVersion": "rbac.authorization.k8s.io/v1",
                    "kind": "RoleBinding",
                    "metadata": metadata,
                    "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": account},
                    "subjects": [{"kind": "ServiceAccount", "name": account, "namespace": self.namespace}],
                },
            ]
        self.apply(documents)

    def images(self) -> Dict[str, str]:
        """The images the tests need, by the variable the code reads each one from."""
        tag = self.image_tag
        return {
            "BROKER": f"scenegems-mqtt-broker:{tag}",
            "WORKER_NODE": f"scenegems-worker-node:{tag}",
            "DESIGN_SPACE_EXPLORATION_IMAGE": f"scenegems-design-space-exploration-subsystem:{tag}",
            "SCENE_GENERATION_IMAGE": f"scenegems-scene-generation-subsystem:{tag}",
            "MONITORING_IMAGE": f"scenegems-monitoring-subsystem:{tag}",
            "SIMULATION_IMAGE": f"scenegems-simulation-subsystem:{tag}",
        }

    def _import_images(self) -> None:
        images = list(self.images().values())
        missing = [image for image in images if _run(["docker", "image", "inspect", image], check=False).returncode != 0]
        if missing:
            raise K3dUnavailable(f"Images missing for the tests marked kubernetes ({IMAGE_TAG_VARIABLE}={self.image_tag}): {', '.join(missing)}")
        _run([self.k3d, "image", "import", *images, "--cluster", self.name], timeout_s=1800)

    def _broker(self) -> None:
        labels = {"app.kubernetes.io/name": BROKER}
        self.apply(
            [
                {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "metadata": {"name": BROKER, "namespace": self.namespace, "labels": labels},
                    "spec": {
                        "replicas": 1,
                        "selector": {"matchLabels": labels},
                        "template": {
                            "metadata": {"labels": labels},
                            "spec": {
                                "containers": [
                                    {
                                        "name": "broker",
                                        "image": self.images()["BROKER"],
                                        "imagePullPolicy": "IfNotPresent",
                                        "ports": [{"containerPort": 1883}],
                                        "volumeMounts": [{"name": "data", "mountPath": "/data/broker"}],
                                    }
                                ],
                                "volumes": [{"name": "data", "emptyDir": {}}],
                            },
                        },
                    },
                },
                {
                    "apiVersion": "v1",
                    "kind": "Service",
                    "metadata": {"name": BROKER, "namespace": self.namespace},
                    # One port number everywhere: the pools dial cluster-broker on it, the test process 127.0.0.1
                    "spec": {"type": "NodePort", "selector": labels, "ports": [{"port": self.broker_port, "targetPort": 1883, "nodePort": self.broker_port}]},
                },
            ]
        )
        self.kubectl_run("rollout", "status", f"deployment/{BROKER}", "-n", self.namespace, "--timeout=180s", timeout_s=200)

    def _worker_node_kubeconfig(self) -> None:
        """A kubeconfig of the daemon's service account: the cluster's server and certificate, the account's token."""
        token = self.kubectl_run("create", "token", WORKER_NODE_ACCOUNT, "-n", self.namespace, "--duration", "6h").stdout.strip()
        admin = yaml.safe_load(self.kubeconfig.read_text(encoding="utf-8"))
        cluster = admin["clusters"][0]
        document = {
            "apiVersion": "v1",
            "kind": "Config",
            "clusters": [cluster],
            "users": [{"name": WORKER_NODE_ACCOUNT, "user": {"token": token}}],
            "contexts": [{"name": WORKER_NODE_ACCOUNT, "context": {"cluster": cluster["name"], "user": WORKER_NODE_ACCOUNT, "namespace": self.namespace}}],
            "current-context": WORKER_NODE_ACCOUNT,
        }
        self.worker_node_kubeconfig.write_text(yaml.safe_dump(document), encoding="utf-8")

    # Waiting

    def wait_for(self, condition, timeout_s: float = 180, what: str = "condition") -> None:
        deadline = time.monotonic() + timeout_s
        while not condition():
            if time.monotonic() > deadline:
                raise AssertionError(f"{what} not met within {timeout_s:g} s; pods: {self.kubectl_run('get', 'pods', '-n', self.namespace, '-o', 'wide', check=False).stdout}")
            time.sleep(1.0)

    def pods(self, selector: str) -> List[dict]:
        return self.json("pods", "-l", selector)["items"]

    # Removing

    def stop(self) -> None:
        try:
            self.kubectl_run("delete", "namespace", self.namespace, "--wait=false", check=False)
        finally:
            if not self.keep:
                _run([self.k3d, "cluster", "delete", self.name], check=False, timeout_s=300)


def start_test_cluster() -> K3dCluster:
    """The cluster of the run, started; K3dUnavailable when a tool or an image is missing."""
    k3d, kubectl = k3d_executable(), kubectl_executable()
    named = os.environ.get(CLUSTER_VARIABLE, "").strip()
    name = named or f"scenegems-test-{uuid.uuid4().hex[:6]}"
    folder = Path(tempfile.mkdtemp(prefix="scenegems-k3d-"))
    broker_port = _mapped_broker_port(k3d, name) if named else None
    cluster = K3dCluster(
        name=name,
        k3d=k3d,
        kubectl=kubectl,
        folder=folder,
        namespace=f"scenegems-test-{uuid.uuid4().hex[:6]}",
        broker_port=broker_port or free_local_port(*NODE_PORTS),
        image_tag=os.environ.get(IMAGE_TAG_VARIABLE, "").strip() or "latest",
        keep=bool(named),
    )
    try:
        cluster.start()
    except BaseException:
        cluster.stop()
        raise
    return cluster


def _mapped_broker_port(k3d: str, name: str) -> Optional[int]:
    """The broker port a kept cluster was created with: its server's one port mapping in the node port range."""
    listing = json.loads(_run([k3d, "cluster", "list", "-o", "json"]).stdout or "[]")
    for cluster in listing:
        if cluster.get("name") != name:
            continue
        for node in cluster.get("nodes", []):
            for container_port in node.get("portMappings") or {}:
                port = int(str(container_port).split("/")[0])
                if NODE_PORTS[0] <= port <= NODE_PORTS[1]:
                    return port
    return None
