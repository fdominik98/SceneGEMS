"""Thin wrappers around the Docker CLI that every launcher uses.

The launchers call the CLI rather than the Docker SDK because the worker node daemon runs it
next to the compose CLI, against the host's Docker socket.
"""

import subprocess
from typing import List

from scenegems_tool.cluster.worker_node.instance_scope import INSTANCE_LABEL

COMPOSE_PROJECT_LABEL = "com.docker.compose.project"


def container_ids_for_compose_project(project: str) -> List[str]:
    result = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label={COMPOSE_PROJECT_LABEL}={project}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return [container_id for container_id in result.stdout.split() if container_id]


def is_container_running(container_name: str) -> bool:
    result = subprocess.run(
        ["docker", "ps", "-q", "-f", f"name=^{container_name}$"],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip())


def force_remove_containers(container_ids: List[str]) -> None:
    if container_ids:
        subprocess.run(["docker", "rm", "-f", *container_ids], check=False, capture_output=True)


def force_remove_compose_project(project: str) -> None:
    """Fast teardown: force-remove a project's containers by label, without a blocking compose down."""
    force_remove_containers(container_ids_for_compose_project(project))


def remove_compose_project_networks(project: str) -> None:
    result = subprocess.run(
        ["docker", "network", "ls", "-q", "--filter", f"label={COMPOSE_PROJECT_LABEL}={project}"],
        capture_output=True,
        text=True,
        check=False,
    )
    _remove_networks(result.stdout.split())


def _instance_filters(project: str, instance: str) -> List[str]:
    return ["--filter", f"label={COMPOSE_PROJECT_LABEL}={project}", "--filter", f"label={INSTANCE_LABEL}={instance}"]


def container_ids_for_instance(project: str, instance: str) -> List[str]:
    """The containers of one instance of a worker node's project, found by the instance's label (instance_scope.py)."""
    result = subprocess.run(["docker", "ps", "-aq", *_instance_filters(project, instance)], capture_output=True, text=True, check=False)
    return [container_id for container_id in result.stdout.split() if container_id]


def force_remove_instance(project: str, instance: str) -> None:
    """Fast teardown of one instance; the project's other containers stay."""
    force_remove_containers(container_ids_for_instance(project, instance))


def remove_instance_networks(project: str, instance: str) -> None:
    result = subprocess.run(["docker", "network", "ls", "-q", *_instance_filters(project, instance)], capture_output=True, text=True, check=False)
    _remove_networks(result.stdout.split())


def instance_keys_of_project(project: str) -> List[str]:
    """The instances that have a container or a network in a worker node's project, by their label values."""
    label = f'{{{{.Label "{INSTANCE_LABEL}"}}}}'
    project_filter = ["--filter", f"label={COMPOSE_PROJECT_LABEL}={project}", "--filter", f"label={INSTANCE_LABEL}"]
    containers = subprocess.run(["docker", "ps", "-a", "--format", label, *project_filter], capture_output=True, text=True, check=False)
    networks = subprocess.run(["docker", "network", "ls", "--format", label, *project_filter], capture_output=True, text=True, check=False)
    return sorted({key for key in (containers.stdout + "\n" + networks.stdout).split() if key})


def _remove_networks(network_ids: List[str]) -> None:
    network_ids = [network_id for network_id in network_ids if network_id]
    if network_ids:
        subprocess.run(["docker", "network", "rm", *network_ids], check=False, capture_output=True)


def copy_into_container(source: str, container: str, destination: str) -> None:
    subprocess.run(["docker", "cp", source, f"{container}:{destination}"], check=True, capture_output=True, text=True)


def copy_from_container(container: str, source: str, destination: str) -> bool:
    """Copy a file out of a container; False when the container has no such file."""
    result = subprocess.run(["docker", "cp", f"{container}:{source}", destination], check=False, capture_output=True, text=True)
    return result.returncode == 0
