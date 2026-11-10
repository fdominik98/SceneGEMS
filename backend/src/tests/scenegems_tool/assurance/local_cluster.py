"""A control node and a worker node of one cluster on this host, deployed from a release bundle the way the
deployment tool deploys them (cluster/release/roles.py).

Each role gets a folder of its own with its stack and release.json, and a .env made of the
role's values, its parameters and secrets generated here. There is no pairing: the worker node's .env
holds the control node's address and ports ({control-node.vpn_ip} and {control-node.<parameter>} of its role),
and each compose project is started and waited for until the role's ready services are up.
Worker nodes reach the control node through host.docker.internal, which stands in for the control node's VPN address.
"""

import json
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from scenegems_tool.cluster.release.manifest import Release

CONTROL_NODE_ADDRESS = "host.docker.internal"


def render(text: str, context: Mapping[str, str]) -> str:
    for placeholder, value in context.items():
        text = text.replace("{" + placeholder + "}", value)
    return text


def run(command: List[str], cwd: Path, timeout_s: float = 600) -> str:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout_s)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed in {cwd} ({result.returncode}): {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


@dataclass
class LocalRole:
    """One deployed role: its folder, compose project and ready services."""

    name: str
    folder: Path
    ready: Mapping[str, List[str]]

    def compose(self, *arguments: str, timeout_s: float = 600) -> str:
        return run(["docker", "compose", *arguments], self.folder, timeout_s)

    def services(self) -> Dict[str, Dict[str, Any]]:
        output = self.compose("ps", "--all", "--format", "json")
        lines = [json.loads(line) for line in output.splitlines() if line.strip()]
        return {line["Service"]: line for line in lines}

    def is_ready(self) -> bool:
        services = self.services()
        running = all(services.get(service, {}).get("State") == "running" for service in self.ready.get("running", []))
        healthy = all(services.get(service, {}).get("Health") == "healthy" for service in self.ready.get("healthy", []))
        return running and healthy

    def wait_ready(self, timeout_s: float = 300) -> None:
        deadline = time.monotonic() + timeout_s
        while not self.is_ready():
            if time.monotonic() > deadline:
                raise TimeoutError(f"{self.name} is not ready after {timeout_s:.0f} s: {self.services()}")
            time.sleep(2)

    def down(self) -> None:
        try:
            self.compose("down", "--volumes", "--remove-orphans", timeout_s=300)
        except RuntimeError:
            pass


def _install(release_dir: Path, role: Mapping[str, Any], folder: Path) -> None:
    if folder.exists():
        shutil.rmtree(folder)
    shutil.copytree(release_dir / "stacks" / role["stack"], folder)
    shutil.copy(release_dir / "release.json", folder / "release.json")


def _write_env(folder: Path, values: Mapping[str, str]) -> None:
    (folder / ".env").write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8", newline="\n")


def _role_env(role: Mapping[str, Any], context: Mapping[str, str], parameters: Optional[Mapping[str, str]]) -> Dict[str, str]:
    values = {key: render(value, context) for key, value in role["env"].items()}
    values.update({key: definition["default"] for key, definition in role["parameters"].items()})
    values.update(parameters or {})
    values.update({key: secrets.token_urlsafe(32) for key in role["secrets"]})
    return values


def deploy_control_node(release_dir: Path, release: Release, work_dir: Path, cluster: str, parameters: Optional[Mapping[str, str]] = None) -> LocalRole:
    role = release.roles["control-node"]
    context = {"cluster": cluster, "name": cluster, "machine.vpn_ip": CONTROL_NODE_ADDRESS, "machine.name": "local", "release.revision": release.revision}
    folder = work_dir / f"control node-{cluster}"
    _install(release_dir, role, folder)
    _write_env(folder, _role_env(role, context, parameters))
    control_node = LocalRole(name=f"control node {cluster}", folder=folder, ready=role["ready"])
    for command in role["setup"]:
        run([render(part, context) for part in command], folder)
    control_node.compose("up", "--detach")
    control_node.wait_ready()
    return control_node


def deploy_worker_node(
    release_dir: Path,
    release: Release,
    work_dir: Path,
    cluster: str,
    name: str,
    parameters: Optional[Mapping[str, str]] = None,
    control_node_parameters: Optional[Mapping[str, str]] = None,
) -> LocalRole:
    """A worker node of the cluster. It needs no deployed control node, only the control node's address and parameters, as Machine Hub passes them."""
    role = release.roles["worker-node"]
    control_node_values = {key: definition["default"] for key, definition in release.roles["control-node"]["parameters"].items()}
    control_node_values.update(control_node_parameters or {})
    context = {"cluster": cluster, "name": name, "machine.vpn_ip": CONTROL_NODE_ADDRESS, "machine.name": "local", "release.revision": release.revision, "control-node.vpn_ip": CONTROL_NODE_ADDRESS}
    context.update({f"control-node.{key}": value for key, value in control_node_values.items()})
    folder = work_dir / f"worker node-{cluster}-{name}"
    _install(release_dir, role, folder)
    _write_env(folder, _role_env(role, context, parameters))
    worker_node = LocalRole(name=f"worker node {name}", folder=folder, ready=role["ready"])
    worker_node.compose("up", "--detach")
    worker_node.wait_ready()
    return worker_node


def remove_cluster_containers(cluster: str) -> None:
    """Subsystem containers a worker node started for this cluster and left behind."""
    names = subprocess.run(["docker", "ps", "--all", "--quiet", "--filter", f"name=scenegems-{cluster}-"], capture_output=True, text=True).stdout.split()
    if names:
        subprocess.run(["docker", "rm", "--force", *names], capture_output=True)
