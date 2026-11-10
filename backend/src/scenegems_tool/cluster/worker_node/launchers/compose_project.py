"""One Docker Compose project: its compose file on disk and the CLI calls that run it."""

import os
import subprocess
from typing import Optional

import yaml

from scenegems_tool.cluster.worker_node.launchers.docker_cli import force_remove_compose_project, remove_compose_project_networks

COMPOSE_COMMAND = ["docker-compose"]


def dump_compose(compose: dict) -> str:
    """The compose file text, formatted as every launcher has always written it."""
    return yaml.dump(compose, default_flow_style=False, sort_keys=False, width=10000)


class ComposeProject:
    def __init__(self, name: str, compose_filename: str):
        self.name = name
        self.compose_filename = compose_filename

    def write(self, compose: dict) -> None:
        folder = os.path.dirname(self.compose_filename)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(self.compose_filename, "w", encoding="utf-8") as file:
            file.write(dump_compose(compose))

    def _compose(self, *arguments: str, check: bool = False, capture: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run([*COMPOSE_COMMAND, "-f", self.compose_filename, "--project-name", self.name, *arguments], check=check, capture_output=capture, text=capture)

    def up(self, *options: str) -> subprocess.CompletedProcess:
        """Start detached from local images only, as the workbench always has."""
        return self._compose("up", "-d", "--no-build", *options)

    def published_port(self, service: str, container_port: int) -> Optional[int]:
        """The host port Docker published a service's container port on, None while it has none."""
        result = self._compose("port", service, str(container_port), capture=True)
        address = (result.stdout or "").strip().splitlines()
        if result.returncode != 0 or not address or ":" not in address[0]:
            return None
        port = address[0].rsplit(":", 1)[1]
        return int(port) if port.isdigit() and int(port) > 0 else None

    def create(self) -> None:
        """Create every container without starting one, so files can be copied in first."""
        self._compose("create", "--no-build", check=True)

    def start(self) -> None:
        self._compose("start", check=True)

    def force_remove(self, *, networks: bool = False) -> None:
        force_remove_compose_project(self.name)
        if networks:
            remove_compose_project_networks(self.name)
