"""Thin wrappers around the Docker CLI that every launcher uses.

The launchers call the CLI rather than the Docker SDK because the workbench backend and
the node daemon both run it next to the compose CLI, against the host's Docker socket.
"""

import subprocess
from typing import List

COMPOSE_PROJECT_LABEL = "com.docker.compose.project"


def container_ids_for_compose_project(project: str) -> List[str]:
    result = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label={COMPOSE_PROJECT_LABEL}={project}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return [container_id for container_id in result.stdout.split() if container_id]


def container_ids_for_compose_project_prefix(prefix: str) -> List[str]:
    """Containers of every compose project whose name starts with prefix."""
    result = subprocess.run(
        ["docker", "ps", "-a", "--format", f'{{{{.ID}}}}\t{{{{.Label "{COMPOSE_PROJECT_LABEL}"}}}}'],
        capture_output=True,
        text=True,
        check=False,
    )
    container_ids: List[str] = []
    for line in result.stdout.splitlines():
        container_id, _, project = line.partition("\t")
        if container_id and project.startswith(prefix):
            container_ids.append(container_id)
    return container_ids


def compose_projects_with_prefix(prefix: str) -> List[str]:
    """Names of the compose projects with a container whose project name starts with prefix."""
    result = subprocess.run(
        ["docker", "ps", "-a", "--format", f'{{{{.Label "{COMPOSE_PROJECT_LABEL}"}}}}'],
        capture_output=True,
        text=True,
        check=False,
    )
    return sorted({project for project in result.stdout.split() if project.startswith(prefix)})


def container_names_and_ids() -> List[tuple]:
    result = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{.ID}}\t{{.Names}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    pairs = []
    for line in result.stdout.splitlines():
        container_id, _, name = line.partition("\t")
        if container_id:
            pairs.append((container_id, name))
    return pairs


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
    network_ids = [network_id for network_id in result.stdout.split() if network_id]
    if network_ids:
        subprocess.run(["docker", "network", "rm", *network_ids], check=False, capture_output=True)


def copy_into_container(source: str, container: str, destination: str) -> None:
    subprocess.run(["docker", "cp", source, f"{container}:{destination}"], check=True, capture_output=True, text=True)


def copy_from_container(container: str, source: str, destination: str) -> bool:
    """Copy a file out of a container; False when the container has no such file."""
    result = subprocess.run(["docker", "cp", f"{container}:{source}", destination], check=False, capture_output=True, text=True)
    return result.returncode == 0
