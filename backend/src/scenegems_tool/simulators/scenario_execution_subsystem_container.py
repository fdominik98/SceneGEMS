import base64
import json
import logging
import os
import subprocess
import threading

import yaml

from concrete_level.models.trajectories import Trajectories
from scenegems_tool.backend_service.protocol import make_simulation_models_body
from scenegems_tool.simulators.simulation_config import SimulationConfig
from scenegems_tool.simulators.simulation_docker_stack import (
    SIMULATION_COMPOSE_PROJECT,
    build_simulation_docker_stack_artifacts,
    write_simulation_gen_files,
)
from scenegems_tool.waraps_integration.mqtt_client import MQttConnectionInfo
from scenegems_tool.waraps_integration.mqtt_scenario_execution_service import SCENARIO_EXECUTION_SERVICE_TOPIC
from scenegems_tool.waraps_integration.sim_utils import Geofence
from utils.docker_compose_network import attach_broker_network_to_compose
from utils.file_system_utils import (
    SCENARIO_EXECUTION_GEN_FOLDER,
    docker_volume_path,
    merge_compose_volumes,
    runtime_assets_volume_mount,
)

COMPOSE_PROJECT = "scenario_execution_subsystem"
SERVICE_NAME = "scenario_execution"
DEFAULT_IMAGE = "scenegems-scenario-execution-subsystem:latest"
SERVICE_CPU = 2
TRAJECTORIES_GEN_FILE = f"{SCENARIO_EXECUTION_GEN_FOLDER}/trajectories.json"
_logger = logging.getLogger(__name__)
_stack_lock = threading.Lock()
_stack_generation = 0
_stack_generation_lock = threading.Lock()


def claim_stack_ownership() -> int:
    """Mark a new stack owner; stale scheduled destroys for older generations are ignored."""
    global _stack_generation
    with _stack_generation_lock:
        _stack_generation += 1
        return _stack_generation


def _container_ids_for_compose_project(project: str) -> list[str]:
    result = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return [container_id for container_id in result.stdout.split() if container_id]


def _force_remove_container_ids(container_ids: list[str]) -> None:
    if container_ids:
        subprocess.run(["docker", "rm", "-f", *container_ids], check=False)


def force_destroy_scenario_execution_stack(compose_filename: str | None = None) -> None:
    """Fast teardown: force-remove containers by compose project label (no blocking compose down)."""
    del compose_filename
    _force_remove_container_ids(_container_ids_for_compose_project(COMPOSE_PROJECT))
    _force_remove_container_ids(_container_ids_for_compose_project(SIMULATION_COMPOSE_PROJECT))


def schedule_force_destroy_scenario_execution_stack(
    compose_filename: str | None = None,
    owner_generation: int | None = None,
) -> None:
    """Tear down the scenario-execution stack on a background thread without blocking the caller."""

    def _run_destroy() -> None:
        try:
            with _stack_generation_lock:
                if owner_generation is not None and owner_generation != _stack_generation:
                    return
            with _stack_lock:
                force_destroy_scenario_execution_stack(compose_filename)
        except BaseException:
            _logger.exception("Background scenario execution stack destroy failed")

    threading.Thread(
        target=_run_destroy,
        name="scenario_execution_force_destroy",
        daemon=True,
    ).start()


class ScenarioExecutionSubsystemContainer:
    """Spawns and tears down the unified scenario-execution Docker Compose stack."""

    service_topic = SCENARIO_EXECUTION_SERVICE_TOPIC

    def __init__(
        self,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        simulation_config: SimulationConfig,
        trajectories: Trajectories,
        time_step: int,
    ):
        self.compose_filename = f"{SCENARIO_EXECUTION_GEN_FOLDER}/docker-compose.yml"
        self._destroyed = False
        self._shutdown = threading.Event()
        self._stack_generation = claim_stack_ownership()
        self._spawn_thread = threading.Thread(
            target=self._run_spawn,
            args=(mqtt_connection, reference_geofence, simulation_config, trajectories, time_step),
            name="scenario_execution_compose_spawn",
            daemon=True,
        )
        self._spawn_thread.start()

    def _run_spawn(
        self,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        simulation_config: SimulationConfig,
        trajectories: Trajectories,
        time_step: int,
    ) -> None:
        try:
            if self._shutdown.is_set():
                return
            with _stack_lock:
                if self._shutdown.is_set():
                    return
                if _container_ids_for_compose_project(COMPOSE_PROJECT):
                    force_destroy_scenario_execution_stack()
                if self._shutdown.is_set():
                    return
            self._spawn(mqtt_connection, reference_geofence, simulation_config, trajectories, time_step)
        except BaseException:
            _logger.exception("Scenario execution stack spawn failed")
            force_destroy_scenario_execution_stack()

    def _spawn(
        self,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        simulation_config: SimulationConfig,
        trajectories: Trajectories,
        time_step: int,
    ) -> None:
        pending_writes, stack_compose = build_simulation_docker_stack_artifacts(
            simulation_config,
            trajectories,
            mqtt_connection,
            reference_geofence,
            embedded_in_subsystem=True,
        )
        write_simulation_gen_files(pending_writes)
        self._verify_gen_files(pending_writes)

        unified_compose = self._build_unified_compose(
            stack_compose,
            mqtt_connection,
            reference_geofence,
            simulation_config,
            time_step,
        )
        with open(self.compose_filename, "w", encoding="utf-8") as file:
            yaml.dump(unified_compose, file, default_flow_style=False, sort_keys=False, width=10000)

        subprocess.run(
            [
                "docker-compose",
                "-f",
                self.compose_filename,
                "--project-name",
                COMPOSE_PROJECT,
                "up",
                "-d",
                "--no-build",
                "--force-recreate",
            ],
            check=False,
        )

    def _verify_gen_files(self, pending_writes: list[tuple[str, str]]) -> None:
        missing = [path for path, _ in pending_writes if not os.path.isfile(path)]
        if missing:
            raise FileNotFoundError(f"Simulation gen files missing before compose up: {missing}")

    def _build_unified_compose(
        self,
        stack_compose: dict,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        simulation_config: SimulationConfig,
        time_step: int,
    ) -> dict:
        image = os.environ.get("SCENARIO_EXECUTION_IMAGE", DEFAULT_IMAGE)
        simulation_config_b64 = base64.b64encode(json.dumps(make_simulation_models_body(simulation_config)).encode("utf-8")).decode("ascii")

        agent_service_names = list(stack_compose["services"].keys())
        scenario_execution_service = {
            "image": image,
            "container_name": SERVICE_NAME,
            "hostname": SERVICE_NAME,
            "depends_on": agent_service_names,
            "environment": {
                "MQTT_USER": mqtt_connection.user,
                "MQTT_PASSWORD": mqtt_connection.password,
                "MQTT_BROKER": mqtt_connection.agent_broker,
                "MQTT_PORT": str(mqtt_connection.port),
                "MQTT_TLS": "1" if mqtt_connection.tls_connection else "0",
                "MQTT_ALLOW_CERTIFICATES": "1" if mqtt_connection.allow_certificates else "0",
                "GEOFENCE_LATITUDE": str(reference_geofence.latitude),
                "GEOFENCE_LONGITUDE": str(reference_geofence.longitude),
                "GEOFENCE_RADIUS": str(reference_geofence.radius_meters),
                "SIMULATION_CONFIG_JSON_B64": simulation_config_b64,
                "TRAJECTORIES_PATH": docker_volume_path(TRAJECTORIES_GEN_FILE),
                "TIME_STEP": str(time_step),
            },
            "cpus": SERVICE_CPU,
            "restart": "unless-stopped",
            "extra_hosts": ["host.docker.internal:host-gateway"],
            "volumes": [runtime_assets_volume_mount(read_only=True)],
            "networks": ["scenario_execution_net"],
        }

        return merge_compose_volumes(
            attach_broker_network_to_compose(
                {
                    "services": {
                        **stack_compose["services"],
                        SERVICE_NAME: scenario_execution_service,
                    },
                    "networks": {
                        "scenario_execution_net": {"driver": "bridge"},
                        **stack_compose.get("networks", {}),
                    },
                }
            )
        )

    def cancel(self) -> None:
        """Stop spawn without tearing down the shared Docker stack (session replace)."""
        if self._destroyed:
            return
        self._destroyed = True
        self._shutdown.set()

    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        self._shutdown.set()
        schedule_force_destroy_scenario_execution_stack(
            self.compose_filename,
            owner_generation=self._stack_generation,
        )
