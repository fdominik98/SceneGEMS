import base64
import logging
import os
import re
import shutil
import subprocess
import threading
import uuid
from typing import Optional

import yaml

from scenegems_tool.waraps_integration.mqtt_client import MQttConnectionInfo
from scenegems_tool.waraps_integration.sim_utils import Geofence
from utils.docker_compose_network import attach_broker_network_to_compose
from utils.file_system_utils import MONITORING_GEN_FOLDER

_COMPOSE_PROJECT = "scenegems-monitoring-subsystem"
_DEFAULT_IMAGE = "scenegems-monitoring-subsystem:latest"
_SERVICE_CPU = 1
_logger = logging.getLogger(__name__)


def _container_ids_for_monitor_stacks() -> list[str]:
    result = subprocess.run(
        ["docker", "ps", "-a", "--format", '{{.ID}}\t{{.Label "com.docker.compose.project"}}'],
        capture_output=True,
        text=True,
        check=False,
    )
    container_ids: list[str] = []
    for line in result.stdout.splitlines():
        container_id, _, project = line.partition("\t")
        if container_id and project.startswith(_COMPOSE_PROJECT):
            container_ids.append(container_id)
    return container_ids


def force_destroy_monitor_subsystem_stack() -> None:
    """Fast teardown: force-remove every COLREGS monitoring worker container."""
    container_ids = _container_ids_for_monitor_stacks()
    if container_ids:
        subprocess.run(["docker", "rm", "-f", *container_ids], check=False)


def _sanitize_docker_name(name: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "_", name)
    sanitized = sanitized.strip("_.-") or "monitor"
    return sanitized[:63]


class MonitorSubsystemContainer:
    """Owns Docker Compose lifecycle for the internal COLREGS monitoring worker container."""

    def __init__(
        self,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        agent_name: str,
        topic: str,
        colregs_constraints_content: str,
    ):
        self.mqtt_connection = mqtt_connection
        self.reference_geofence = reference_geofence
        self.agent_name = agent_name
        self.topic = topic
        self.colregs_constraints_content = colregs_constraints_content
        self.instance_id = uuid.uuid4().hex[:8]
        self.compose_project = f"{_COMPOSE_PROJECT}-{self.instance_id}"
        self.container_name = f"{_sanitize_docker_name(agent_name)[:54]}-{self.instance_id}"
        self.compose_folder = f"{MONITORING_GEN_FOLDER}/{self.instance_id}"
        self.compose_filename = f"{self.compose_folder}/docker-compose.yml"
        self._shutdown = threading.Event()
        self._startup_complete = threading.Event()
        self._lifecycle_thread: Optional[threading.Thread] = None
        docker_compose = self._build_compose()
        self._lifecycle_thread = threading.Thread(
            target=self._run_container_lifecycle_startup,
            args=(docker_compose, self.compose_filename),
            name="monitoring_compose",
            daemon=True,
        )
        self._lifecycle_thread.start()

    def _build_compose(self) -> dict:
        image = os.environ.get("MONITORING_IMAGE", _DEFAULT_IMAGE)
        constraints_b64 = base64.b64encode(self.colregs_constraints_content.encode("utf-8")).decode("ascii")
        environment = {
            "MQTT_USER": self.mqtt_connection.user,
            "MQTT_PASSWORD": self.mqtt_connection.password,
            "MQTT_BROKER": self.mqtt_connection.agent_broker,
            "MQTT_PORT": str(self.mqtt_connection.port),
            "MQTT_TLS": "1" if self.mqtt_connection.tls_connection else "0",
            "MQTT_ALLOW_CERTIFICATES": "1" if self.mqtt_connection.allow_certificates else "0",
            "GEOFENCE_LATITUDE": str(self.reference_geofence.latitude),
            "GEOFENCE_LONGITUDE": str(self.reference_geofence.longitude),
            "GEOFENCE_RADIUS": str(self.reference_geofence.radius_meters),
            "MONITOR_AGENT_NAME": self.agent_name,
            "MONITOR_TOPIC": self.topic,
            "COLREGS_CONSTRAINTS_YAML_B64": constraints_b64,
        }
        service = {
            "image": image,
            "container_name": self.container_name,
            "hostname": self.container_name,
            "environment": environment,
            "cpus": _SERVICE_CPU,
            "networks": ["monitoring_net"],
        }

        return attach_broker_network_to_compose(
            {
                "services": {
                    "monitoring": service,
                },
                "networks": {
                    "monitoring_net": {
                        "driver": "bridge",
                    }
                },
            }
        )

    def _run_container_lifecycle_startup(self, docker_compose: dict, compose_filename: str) -> None:
        try:
            if self._shutdown.is_set():
                return
            os.makedirs(self.compose_folder, exist_ok=True)
            if self._shutdown.is_set():
                return
            with open(compose_filename, "w", encoding="utf-8") as file:
                yaml.dump(docker_compose, file, default_flow_style=False, sort_keys=False, width=10000)
            if self._shutdown.is_set():
                return
            subprocess.run(
                [
                    "docker-compose",
                    "-f",
                    compose_filename,
                    "--project-name",
                    self.compose_project,
                    "up",
                    "-d",
                    "--no-build",
                ],
                check=False,
            )
            if self._shutdown.is_set():
                self._remove_owned_container()
                return
            self._startup_complete.set()
        except BaseException:
            _logger.exception("MonitoringContainer container lifecycle startup failed")

    def _remove_owned_container(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.container_name], check=False)
        if os.path.isdir(self.compose_folder):
            shutil.rmtree(self.compose_folder, ignore_errors=True)

    def _is_container_running(self) -> bool:
        result = subprocess.run(
            ["docker", "ps", "-q", "-f", f"name=^{self.container_name}$"],
            capture_output=True,
            text=True,
            check=False,
        )
        return bool(result.stdout.strip())

    @property
    def is_ready(self) -> bool:
        return self._startup_complete.is_set() and self._is_container_running()

    def destroy(self) -> None:
        self._shutdown.set()
        if self._lifecycle_thread is not None:
            self._lifecycle_thread.join(timeout=120.0)
            self._lifecycle_thread = None
        self._remove_owned_container()
