import logging
import os
import shutil
import subprocess
import threading
from typing import Optional

import yaml

from scenegems_tool.waraps_integration.mqtt_client import MQttConnectionInfo
from scenegems_tool.waraps_integration.sim_utils import Geofence
from utils.docker_compose_network import attach_broker_network_to_compose
from utils.file_system_utils import SCENARIO_GENERATION_GEN_FOLDER, merge_compose_volumes

_COMPOSE_PROJECT = "scenegems-scenario-generation-subsystem"
_SERVICE_NAME = "scenario_generation"
_DEFAULT_IMAGE = "scenegems-scenario-generation-subsystem:latest"
_MAX_WORKER_CPUS = 5
_SERVICE_CPU = 1
_CONTAINER_CPUS = _MAX_WORKER_CPUS + _SERVICE_CPU
_logger = logging.getLogger(__name__)


def _container_ids_for_compose_project(project: str) -> list[str]:
    result = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return [container_id for container_id in result.stdout.split() if container_id]


def force_destroy_scenario_generation_stack() -> None:
    """Fast teardown: force-remove scenario-generation subsystem containers."""
    container_ids = _container_ids_for_compose_project(_COMPOSE_PROJECT)
    if container_ids:
        subprocess.run(["docker", "rm", "-f", *container_ids], check=False)


class ScenarioGenerationContainer:
    """Owns Docker Compose lifecycle for the scenario generation subsystem container."""

    def __init__(self, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence):
        self.mqtt_connection = mqtt_connection
        self.reference_geofence = reference_geofence
        self._shutdown = threading.Event()
        self._lifecycle_thread: Optional[threading.Thread] = None
        self.compose_filename = f"{SCENARIO_GENERATION_GEN_FOLDER}/docker-compose.yml"
        docker_compose = self._build_compose()
        self._lifecycle_thread = threading.Thread(
            target=self._run_container_lifecycle_startup,
            args=(docker_compose, self.compose_filename),
            name="scenario_generation_compose",
            daemon=True,
        )
        self._lifecycle_thread.start()

    def _build_compose(self) -> dict:
        image = os.environ.get("SCENARIO_GENERATION_IMAGE", _DEFAULT_IMAGE)
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
        }
        service = {
            "image": image,
            "container_name": _SERVICE_NAME,
            "hostname": _SERVICE_NAME,
            "environment": environment,
            "cpus": _CONTAINER_CPUS,
            "networks": ["scenario_generation_net"],
        }

        return merge_compose_volumes(
            attach_broker_network_to_compose(
                {
                    "services": {
                        _SERVICE_NAME: service,
                    },
                    "networks": {
                        "scenario_generation_net": {
                            "name": "scenario_generation_net",
                            "driver": "bridge",
                        }
                    },
                }
            )
        )

    def _run_container_lifecycle_startup(self, docker_compose: dict, compose_filename: str) -> None:
        try:
            if self._shutdown.is_set():
                return
            self._remove_docker_compose_project()
            if self._shutdown.is_set():
                return
            if os.path.exists(SCENARIO_GENERATION_GEN_FOLDER):
                shutil.rmtree(SCENARIO_GENERATION_GEN_FOLDER)
            os.makedirs(SCENARIO_GENERATION_GEN_FOLDER, exist_ok=True)
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
                    _COMPOSE_PROJECT,
                    "up",
                    "-d",
                    "--no-build",
                ],
                check=False,
            )
        except BaseException:
            _logger.exception("ScenarioGenerationContainer container lifecycle startup failed")

    def _remove_docker_compose_project(self) -> None:
        force_destroy_scenario_generation_stack()

    def destroy(self) -> None:
        self._shutdown.set()
        if self._lifecycle_thread is not None:
            self._lifecycle_thread.join(timeout=120.0)
            self._lifecycle_thread = None
        self._remove_docker_compose_project()
