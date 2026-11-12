"""One Docker Compose file run in a project: the file on disk and the CLI calls that run it.

An instance of a worker node (instance_scope.py) shares the worker node's project with the daemon
and every other instance. Such a ComposeProject names its instance: compose is told to ignore the
project's other containers, which its file does not list, and a teardown removes only the
containers and networks that carry the instance's label. Without an instance the project is the
file's alone.
"""

import os
import subprocess
from typing import Dict, Optional

import yaml

from scenegems_tool.cluster.worker_node.launchers.docker_cli import force_remove_compose_project, force_remove_instance, remove_compose_project_networks, remove_instance_networks

COMPOSE_COMMAND = ["docker-compose"]
IGNORE_ORPHANS_VARIABLE = "COMPOSE_IGNORE_ORPHANS"  # no warning about the project's containers of other compose files


def dump_compose(compose: dict) -> str:
    """The compose file text, formatted as every launcher has always written it."""
    return yaml.dump(compose, default_flow_style=False, sort_keys=False, width=10000)


class ComposeProject:
    def __init__(self, name: str, compose_filename: str, instance: Optional[str] = None):
        self.name = name
        self.compose_filename = compose_filename
        self.instance = instance  # the label value of the one instance this file holds, in a project it shares

    def write(self, compose: dict) -> None:
        folder = os.path.dirname(self.compose_filename)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(self.compose_filename, "w", encoding="utf-8") as file:
            file.write(dump_compose(compose))

    def _environment(self) -> Optional[Dict[str, str]]:
        if self.instance is None:
            return None
        return {**os.environ, IGNORE_ORPHANS_VARIABLE: "true"}

    def _compose(self, *arguments: str, check: bool = False, capture: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run([*COMPOSE_COMMAND, "-f", self.compose_filename, "--project-name", self.name, *arguments], check=check, capture_output=capture, text=capture, env=self._environment())

    def up(self, *options: str) -> subprocess.CompletedProcess:
        """Start detached from local images only: a worker node never builds an image."""
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
        if self.instance is None:
            force_remove_compose_project(self.name)
            if networks:
                remove_compose_project_networks(self.name)
            return
        force_remove_instance(self.name, self.instance)
        if networks:
            remove_instance_networks(self.name, self.instance)
