"""A SceneGEMS cluster in the k3d cluster of the tests, deployed from a release bundle the way the deployment tool deploys it.

The bundle (release.json and the chart) is built from the images of the test's tag (bundle.build_bundle with
built_tag and image_tag). The values file is built from the roles of release.json with the reference builder
(tests/scenegems_tool/cluster/release/chart_values_builder.py), as Machine Hub builds it: one member per role on the
cluster's node. Machine Hub pushes the images a cluster needs to the cluster's registry and writes each as
registry/repository@sha256:<digest>; here they are imported into the node by tag, and the values name each one by
that tag, which the chart takes as it is too. The chart is installed with helm into a namespace of its own and waited
for until the workloads of the roles' `ready` are available. deploy/kubernetes/scripts/local_cluster.sh does the
same on an operator's PC with a hand-written values file.

The control node and the worker nodes reach each other by service name inside the cluster. The operator API is reached
through a port forward to the service the control node role's `forwards` names, as the console reaches it.
"""

import json
import subprocess
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple

import yaml

from scenegems_tool.cluster.release.__main__ import checkout_revision
from scenegems_tool.cluster.release.bundle import build_bundle
from scenegems_tool.cluster.release.manifest import Release
from tests.scenegems_tool.cluster.release.chart_values_builder import Member, build_values, member_context, needed_images, render
from tests.scenegems_tool.cluster.worker_node.k3d_cluster import K3dCluster, free_local_port

REPO_ROOT = Path(__file__).resolve().parents[5]
INSTALL_TIMEOUT = "10m"


def bundle_release(folder: Path, image_tag: str) -> Tuple[Path, Release]:
    """A release bundle of this checkout whose images are the ones built under image_tag, named by that tag."""
    revision, dirty = checkout_revision(REPO_ROOT)
    release_dir = folder / "release"
    return release_dir, build_bundle(release_dir, REPO_ROOT, revision, dirty, image_tag=image_tag, built_tag=image_tag)


def control_node(node: str, **parameters: str) -> Member:
    return Member("control-node", "control-node", node=node, machine="operator-pc", parameters=parameters)


def worker_node(name: str, node: str, **parameters: str) -> Member:
    return Member("worker-node", name, node=node, machine="operator-pc", parameters=parameters)


@dataclass
class LocalCluster:
    """One install of the chart in a namespace of the test's k3d cluster."""

    k3d: K3dCluster
    namespace: str
    cluster_id: str
    helm_release: str
    release: Dict[str, Any]  # release.json as the deployment tool reads it
    members: List[Member]
    values: Dict[str, Any]
    folder: Path
    forwards: List[subprocess.Popen] = field(default_factory=list)

    def kubectl(self, *arguments: str, check: bool = True, timeout_s: float = 120, input_text: Optional[str] = None) -> str:
        return self.k3d.kubectl_run("-n", self.namespace, *arguments, check=check, timeout_s=timeout_s, input_text=input_text).stdout

    def ready_workloads(self) -> List[str]:
        """kind/name of every workload the roles' `ready` names for the members, rendered as the deployment tool renders them."""
        workloads = []
        for member in self.members:
            ready = self.release["roles"][member.role]["ready"]
            context = member_context(self.release, self.cluster_id, member)
            workloads += [f"deployment/{render(name, context, 'ready')}" for name in ready.get("deployments", [])]
            workloads += [f"statefulset/{render(name, context, 'ready')}" for name in ready.get("stateful_sets", [])]
        return workloads

    def wait_ready(self, timeout_s: float = 600) -> None:
        """Every workload of `ready` available, as the deployment tool's ready check reads it."""
        for workload in self.ready_workloads():
            self.kubectl("rollout", "status", workload, f"--timeout={int(timeout_s)}s", timeout_s=timeout_s + 30)

    def logs(self, workload: str, tail: int = 200) -> str:
        return self.kubectl("logs", workload, f"--tail={tail}", "--all-containers", check=False)

    @contextmanager
    def forward(self, forward_name: str = "operator-api") -> Iterator[int]:
        """The forward of a role's `forwards` opened as kubectl port-forward on a free local port; yields the port."""
        (forward,) = [item for role in self.release["roles"].values() for item in role["forwards"] if item["name"] == forward_name]
        port = free_local_port(20000, 29999)
        process = subprocess.Popen(
            [self.k3d.kubectl, "--kubeconfig", str(self.k3d.kubeconfig), "-n", self.namespace, "port-forward", f"service/{forward['service']}", f"{port}:{forward['port']}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.forwards.append(process)
        try:
            _wait_listening(port, process)
            yield port
        finally:
            process.terminate()
            process.wait(timeout=30)

    def uninstall(self) -> None:
        for process in self.forwards:
            if process.poll() is None:
                process.terminate()
        self.k3d.helm_run("uninstall", self.helm_release, "--namespace", self.namespace, "--wait", "--timeout", "5m", check=False)
        self.k3d.kubectl_run("delete", "namespace", self.namespace, "--wait=false", check=False)


def _wait_listening(port: int, process: subprocess.Popen, timeout_s: float = 30) -> None:
    import socket

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"kubectl port-forward ended: {process.stderr.read() if process.stderr else ''}")
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.3)
    raise TimeoutError(f"the port forward on 127.0.0.1:{port} did not open within {timeout_s:g} s")


def deploy(
    k3d: K3dCluster,
    release_dir: Path,
    release: Release,
    members: Iterable[Member],
    *,
    cluster_id: str,
    namespace: Optional[str] = None,
    extra_values: Optional[Mapping[str, Any]] = None,
    wait: bool = True,
) -> LocalCluster:
    """The chart of the bundle installed into a namespace of the k3d cluster, with the values the roles give for the members.

    The images the members need are imported by tag first. With wait, the install waits (helm --wait) and the
    roles' ready workloads are checked."""
    release_json = json.loads((release_dir / "release.json").read_text(encoding="utf-8"))
    members = list(members)
    images = sorted(needed_images(release_json, cluster_id, members))
    k3d.import_images(images)
    values = build_values(release_json, cluster_id, members, {image: image for image in images})  # imported by tag: the reference is the tag
    values.update(extra_values or {})
    namespace = namespace or f"scenegems-{cluster_id}-{uuid.uuid4().hex[:6]}"
    folder = Path(k3d.folder) / namespace
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "values.yaml").write_text(yaml.safe_dump(values, sort_keys=True), encoding="utf-8")
    chart = release_json["chart"]
    local = LocalCluster(k3d, namespace, cluster_id, chart["helm_release"], release_json, members, values, folder)
    arguments = ["upgrade", "--install", chart["helm_release"], str(release_dir / chart["folder"]), "--namespace", namespace, "--create-namespace", "-f", str(folder / "values.yaml")]
    if wait:
        arguments += ["--wait", "--timeout", INSTALL_TIMEOUT]
    try:
        k3d.helm_run(*arguments)
        if wait:
            local.wait_ready()
    except BaseException:
        print(local.kubectl("get", "pods", "-o", "wide", check=False))
        local.uninstall()
        raise
    return local
