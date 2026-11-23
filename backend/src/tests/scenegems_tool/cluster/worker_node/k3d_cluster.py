"""The k3d cluster of the tests marked kubernetes, created the way deploy/kubernetes/scripts/local_cluster.sh creates one.

What it needs on the machine: Docker, kubectl on the PATH, k3d and helm on the PATH or named by SCENEGEMS_K3D and
SCENEGEMS_HELM, and the images of the tag in SCENEGEMS_TEST_IMAGE_TAG (latest by default). It creates a cluster of
its own (one server, no load balancer, Traefik and the service load balancer off) with its API on 127.0.0.1 and a
block of node ports mapped to 127.0.0.1, which the API server is told to assign node ports from, as the script
does; and deletes it at the end. With SCENEGEMS_TEST_K3D_CLUSTER set, the cluster of that name is used, created
first when there is none, and kept, so a second run skips the start; its namespaces are still the run's own and
deleted at the end.

Every test of the run shares the cluster. The tests of pools and runs share one namespace of it as well: the chart's
service accounts, roles and network policy (rendered from deploy/kubernetes/chart with helm and applied, so the tests
run under exactly the rights and the policy the chart gives), the cluster broker as a Deployment beside them, and the
images of pools and runs imported by tag. The tests that install the whole chart (tests/scenegems_tool/assurance/
local_cluster.py) take a namespace of their own.

Every kubectl call names the cluster's kubeconfig: kubectl without one talks to 127.0.0.1:8080, which can be any
program on the machine. On a host with cgroup version 1 the kubelet needs fail-cgroupv1=false, which is passed when
Docker reports that version. The kubelet of a cluster created here rotates a container's log at CONTAINER_LOG_MAX_SIZE
(1 MiB, where Kubernetes' default is 10 MiB), so a test of a log followed across its rotation needs only a few MiB.

The tests run the launcher in the test process with a kubeconfig of the worker-node service account, so what the
launcher does is checked against those rights and nothing more; the simulation subsystem creates its runs from its
own pod, with its own account.
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
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import yaml

K3D_VARIABLE = "SCENEGEMS_K3D"
HELM_VARIABLE = "SCENEGEMS_HELM"
CLUSTER_VARIABLE = "SCENEGEMS_TEST_K3D_CLUSTER"
IMAGE_TAG_VARIABLE = "SCENEGEMS_TEST_IMAGE_TAG"
NODE_PORTS = (30000, 32767)  # Kubernetes' default node port range, which the mapped block is taken from
NODE_PORT_COUNT = 20  # node ports mapped to 127.0.0.1: the broker's and those of attended runs
BROKER = "cluster-broker"
BROKER_LABELS = {"app.kubernetes.io/name": BROKER}  # the chart's broker's, which its network policy lets runs reach
WORKER_NODE_ACCOUNT = "worker-node"
SIMULATION_ACCOUNT = "simulation-subsystem"
START_TIMEOUT_S = 300
CONTAINER_LOG_MAX_SIZE = "1Mi"  # the kubelet rotates a container's log at this size (containerLogMaxSize)
CHART = Path(__file__).resolve().parents[5].parent / "deploy" / "kubernetes" / "chart"


class K3dUnavailable(RuntimeError):
    pass


def _program(variable: str, name: str, why: str) -> str:
    named = os.environ.get(variable, "").strip()
    if named:
        if not Path(named).is_file():
            raise K3dUnavailable(f"{variable}={named} names no file")
        return named
    found = shutil.which(name)
    if found is None:
        raise K3dUnavailable(f"{name} is needed for {why}: put it on the PATH or name it with {variable}")
    return found


def k3d_executable() -> str:
    return _program(K3D_VARIABLE, "k3d", "the tests marked kubernetes (k3d 5.9.0 was used)")


def helm_executable() -> str:
    """Helm, for the chart's tests: named by SCENEGEMS_HELM or on the PATH."""
    return _program(HELM_VARIABLE, "helm", "the chart's tests (Helm 4.3.2, the version Machine Hub pins, was used)")


def kubectl_executable() -> str:
    found = shutil.which("kubectl")
    if found is None:
        raise K3dUnavailable("kubectl is needed for the tests marked kubernetes: put it on the PATH")
    return found


def _free(port: int) -> bool:
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True


def free_local_port(low: int = 1024, high: int = 65535) -> int:
    """A port free on 127.0.0.1 between low and high."""
    for _ in range(200):
        port = random.randint(low, high)
        if _free(port):
            return port
    raise RuntimeError(f"No free port between {low} and {high} on 127.0.0.1")


def free_node_ports(count: int = NODE_PORT_COUNT) -> Tuple[int, int]:
    """A block of count ports in the node port range, all free on 127.0.0.1: first and last."""
    for _ in range(200):
        first = random.randint(NODE_PORTS[0], NODE_PORTS[1] - count + 1)
        if all(_free(port) for port in range(first, first + count)):
            return first, first + count - 1
    raise RuntimeError(f"No {count} free ports in a row between {NODE_PORTS[0]} and {NODE_PORTS[1]} on 127.0.0.1")


def _run(arguments: List[str], *, input_text: Optional[str] = None, timeout_s: float = START_TIMEOUT_S, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(arguments, input=input_text, capture_output=True, text=True, timeout=timeout_s)
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(arguments[:3])} failed ({result.returncode}): {result.stderr.strip() or result.stdout.strip()}")
    return result


def create_cluster_arguments(k3d: str, name: str, api_port: int, node_ports: Tuple[int, int], cgroup_v1: bool, kubelet_args: Sequence[str] = ()) -> List[str]:
    """`k3d cluster create` as deploy/kubernetes/scripts/local_cluster.sh runs it: the node ports mapped to 127.0.0.1 straight onto
    the server node, and the API server told to assign node ports from that block only, since only ports mapped now reach this PC."""
    ports = f"{node_ports[0]}-{node_ports[1]}"
    arguments = [k3d, "cluster", "create", name, "--servers", "1", "--agents", "0", "--no-lb", "--api-port", f"127.0.0.1:{api_port}"]
    arguments += ["--port", f"127.0.0.1:{ports}:{ports}@server:0:direct", "--k3s-arg", f"--service-node-port-range={ports}@server:0"]
    arguments += ["--k3s-arg", "--disable=traefik@server:0", "--k3s-arg", "--disable=servicelb@server:0"]
    arguments += ["--kubeconfig-update-default=false", "--kubeconfig-switch-context=false", "--wait", "--timeout", f"{START_TIMEOUT_S}s"]
    if cgroup_v1:
        arguments += ["--k3s-arg", "--kubelet-arg=fail-cgroupv1=false@server:*"]
    for argument in kubelet_args:
        arguments += ["--k3s-arg", f"--kubelet-arg={argument}@server:*"]
    return arguments


def render_chart(helm: str, values: Mapping[str, Any], namespace: str, show_only: Sequence[str] = (), release: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    """The chart's objects rendered with helm template for a namespace, from a copy of the chart with release.json in it (an empty one when none is given)."""
    with tempfile.TemporaryDirectory(prefix="scenegems-chart-") as folder:
        chart = Path(folder) / "chart"
        shutil.copytree(CHART, chart)
        (chart / "release.json").write_text(json.dumps(release or {}), encoding="utf-8")
        (Path(folder) / "values.yaml").write_text(yaml.safe_dump(dict(values)), encoding="utf-8")
        arguments = [helm, "template", "scenegems", str(chart), "--namespace", namespace, "-f", str(Path(folder) / "values.yaml")]
        for template in show_only:
            arguments += ["--show-only", template]
        rendered = _run(arguments, timeout_s=120)
    return [document for document in yaml.safe_load_all(rendered.stdout) if document]


@dataclass
class K3dCluster:
    name: str
    k3d: str
    kubectl: str
    helm: str
    folder: Path  # holds the kubeconfigs
    namespace: str  # the namespace of the tests of pools and runs
    node_ports: Tuple[int, int]  # mapped to the same ports on 127.0.0.1; the API server assigns node ports from them
    image_tag: str
    keep: bool  # a named cluster is kept after the run
    node: str = ""
    imported: set = field(default_factory=set)  # the images this run imported into the node
    kubeconfig: Path = field(init=False)
    worker_node_kubeconfig: Path = field(init=False)

    def __post_init__(self) -> None:
        self.kubeconfig = self.folder / "admin.kubeconfig"
        self.worker_node_kubeconfig = self.folder / "worker-node.kubeconfig"

    @property
    def broker_port(self) -> int:
        """The broker's service port, node port and local port on 127.0.0.1: the first mapped node port."""
        return self.node_ports[0]

    # kubectl

    def kubectl_run(self, *arguments: str, input_text: Optional[str] = None, check: bool = True, timeout_s: float = 120) -> subprocess.CompletedProcess:
        return _run([self.kubectl, "--kubeconfig", str(self.kubeconfig), *arguments], input_text=input_text, check=check, timeout_s=timeout_s)

    def helm_run(self, *arguments: str, check: bool = True, timeout_s: float = 900) -> subprocess.CompletedProcess:
        return _run([self.helm, "--kubeconfig", str(self.kubeconfig), *arguments], check=check, timeout_s=timeout_s)

    def apply(self, documents: List[dict], namespace: Optional[str] = None) -> None:
        self.kubectl_run("apply", "-n", namespace or self.namespace, "-f", "-", input_text=yaml.safe_dump_all(documents))

    def json(self, *arguments: str) -> dict:
        return json.loads(self.kubectl_run("get", "-n", self.namespace, *arguments, "-o", "json").stdout)

    def can_i(self, account: str, verb: str, resource: str, namespace: Optional[str] = None) -> bool:
        """Whether the account may do verb on resource; a subresource is written resource/subresource (pods/log), which kubectl itself would read as a resource and an object's name."""
        kind, _, subresource = resource.partition("/")
        arguments = ["auth", "can-i", verb, kind, *(["--subresource", subresource] if subresource else [])]
        result = self.kubectl_run(*arguments, "-n", namespace or self.namespace, "--as", f"system:serviceaccount:{self.namespace}:{account}", check=False)
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
        self.add_broker(self.namespace, self.broker_port, node_port=self.broker_port)
        self._worker_node_kubeconfig()

    def _exists(self) -> bool:
        listing = json.loads(_run([self.k3d, "cluster", "list", "-o", "json"]).stdout or "[]")
        return any(cluster.get("name") == self.name for cluster in listing)

    def _create(self) -> None:
        cgroup_v1 = _run(["docker", "info", "--format", "{{.CgroupVersion}}"]).stdout.strip() == "1"
        _run(create_cluster_arguments(self.k3d, self.name, free_local_port(), self.node_ports, cgroup_v1, [f"container-log-max-size={CONTAINER_LOG_MAX_SIZE}"]), timeout_s=START_TIMEOUT_S + 60)

    def _namespace_and_rights(self) -> None:
        """The namespace with the chart's service accounts, roles and network policy, as the chart renders them for it."""
        self.kubectl_run("create", "namespace", self.namespace)
        values = {"controlNodeId": "k3d", "workerNodes": []}
        self.apply(render_chart(self.helm, values, self.namespace, ["templates/rbac.yaml", "templates/network-policy.yaml"]))

    def images(self) -> Dict[str, str]:
        """The images the tests of pools and runs need, by the variable the code reads each one from."""
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
        self.import_images(list(self.images().values()))

    def import_images(self, images: List[str]) -> None:
        """Import images of this machine's Docker into the cluster by tag; K3dUnavailable naming the ones that are missing.

        As local_cluster.sh does it: a pulled image (Postgres) is a multi-platform index of which Docker Desktop holds one
        platform, and containerd refuses an archive naming content it lacks, with every other image of the same import;
        so pulled images are saved for the node's platform first. k3d reports success even then, so the node is checked."""
        from scenegems_tool.cluster.release.roles import PULLED_IMAGES

        missing = [image for image in images if _run(["docker", "image", "inspect", image], check=False).returncode != 0]
        if missing:
            raise K3dUnavailable(f"Images missing for the tests marked kubernetes ({IMAGE_TAG_VARIABLE}={self.image_tag}): {', '.join(missing)}")
        wanted = [image for image in images if image not in self.imported]  # imported by this run already: the same build
        built, pulled = [image for image in wanted if image not in PULLED_IMAGES], [image for image in wanted if image in PULLED_IMAGES]
        if built:
            _run([self.k3d, "image", "import", *built, "--cluster", self.name], timeout_s=1800)
        if pulled:
            architecture = _run(["docker", "info", "--format", "{{.Architecture}}"]).stdout.strip().replace("x86_64", "amd64").replace("aarch64", "arm64")
            archive = self.folder / "pulled-images.tar"
            _run(["docker", "save", "--platform", f"linux/{architecture}", "-o", archive.as_posix(), *pulled], timeout_s=600)
            _run([self.k3d, "image", "import", archive.as_posix(), "--cluster", self.name], timeout_s=600)  # k3d takes a path with backslashes for an image name
            archive.unlink()
        refused = [image for image in images if not self._node_has(image)]
        if refused:
            raise RuntimeError(f"The cluster's node did not take these images: {', '.join(refused)}")
        self.imported.update(images)

    def _node_has(self, image: str) -> bool:
        """Whether the node's containerd holds the image by that name (docker.io/library/<name> for a short one)."""
        names = _run(["docker", "exec", self.node, "ctr", "-n", "k8s.io", "images", "ls", "-q"]).stdout.split()
        return any(name == image or name.endswith("/" + image) for name in names)

    def node_run(self, *command: str, check: bool = True) -> subprocess.CompletedProcess:
        """A command on the cluster's node (k3d's container of the server), such as a look at a host path."""
        return _run(["docker", "exec", self.node, *command], check=check, timeout_s=60)

    def add_broker(self, namespace: str, port: int = 1883, node_port: Optional[int] = None) -> None:
        """The cluster broker in a namespace, labelled as the chart labels its own: a Deployment and the Service cluster-broker on port, a
        NodePort Service when node_port is given (the pools dial cluster-broker on that port, the test process 127.0.0.1)."""
        service: Dict[str, Any] = {"type": "ClusterIP", "selector": BROKER_LABELS, "ports": [{"name": "mqtt", "port": port, "targetPort": 1883}]}
        if node_port is not None:
            service = {"type": "NodePort", "selector": BROKER_LABELS, "ports": [{"name": "mqtt", "port": port, "targetPort": 1883, "nodePort": node_port}]}
        self.apply(
            [
                {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "metadata": {"name": BROKER, "labels": BROKER_LABELS},
                    "spec": {
                        "replicas": 1,
                        "selector": {"matchLabels": BROKER_LABELS},
                        "template": {
                            "metadata": {"labels": BROKER_LABELS},
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
                {"apiVersion": "v1", "kind": "Service", "metadata": {"name": BROKER}, "spec": service},
            ],
            namespace,
        )
        self.kubectl_run("rollout", "status", f"deployment/{BROKER}", "-n", namespace, "--timeout=180s", timeout_s=200)

    def _worker_node_kubeconfig(self) -> None:
        """A kubeconfig of the daemon's service account: the cluster's server and certificate, the account's token."""
        self.account_kubeconfig(WORKER_NODE_ACCOUNT, self.worker_node_kubeconfig)

    def account_kubeconfig(self, account: str, path: Path) -> Path:
        """A kubeconfig of a service account of the namespace at path: the cluster's server and certificate, the account's token."""
        token = self.kubectl_run("create", "token", account, "-n", self.namespace, "--duration", "6h").stdout.strip()
        admin = yaml.safe_load(self.kubeconfig.read_text(encoding="utf-8"))
        cluster = admin["clusters"][0]
        document = {
            "apiVersion": "v1",
            "kind": "Config",
            "clusters": [cluster],
            "users": [{"name": account, "user": {"token": token}}],
            "contexts": [{"name": account, "context": {"cluster": cluster["name"], "user": account, "namespace": self.namespace}}],
            "current-context": account,
        }
        path.write_text(yaml.safe_dump(document), encoding="utf-8")
        return path

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
    k3d, kubectl, helm = k3d_executable(), kubectl_executable(), helm_executable()
    named = os.environ.get(CLUSTER_VARIABLE, "").strip()
    name = named or f"scenegems-test-{uuid.uuid4().hex[:6]}"
    folder = Path(tempfile.mkdtemp(prefix="scenegems-k3d-"))
    node_ports = _mapped_node_ports(k3d, name) if named else None
    cluster = K3dCluster(
        name=name,
        k3d=k3d,
        kubectl=kubectl,
        helm=helm,
        folder=folder,
        namespace=f"scenegems-test-{uuid.uuid4().hex[:6]}",
        node_ports=node_ports or free_node_ports(),
        image_tag=os.environ.get(IMAGE_TAG_VARIABLE, "").strip() or "latest",
        keep=bool(named),
    )
    try:
        cluster.start()
    except BaseException:
        cluster.stop()
        raise
    return cluster


def _mapped_node_ports(k3d: str, name: str) -> Optional[Tuple[int, int]]:
    """The block of node ports a kept cluster was created with: its server's port mappings in the node port range."""
    listing = json.loads(_run([k3d, "cluster", "list", "-o", "json"]).stdout or "[]")
    for cluster in listing:
        if cluster.get("name") != name:
            continue
        ports = sorted(
            int(str(container_port).split("/")[0])
            for node in cluster.get("nodes", [])
            for container_port in node.get("portMappings") or {}
            if NODE_PORTS[0] <= int(str(container_port).split("/")[0]) <= NODE_PORTS[1]
        )
        if ports:
            return ports[0], ports[-1]
    return None
