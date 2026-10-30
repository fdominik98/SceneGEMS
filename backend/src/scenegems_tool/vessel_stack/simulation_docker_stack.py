"""Simulation instance builder for Docker-based stacks: a thin caller of the adapter registry.

The instance is resolved first, so an unavailable stack or an unsupported environment is
rejected before anything is generated. The simulation layer adapter and each vessel's
control layer adapter then contribute their files and compose services.
"""

import json
import logging
import os
import subprocess
import threading
from typing import List, Optional, Tuple

import yaml

from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.trajectories import Trajectories
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.agent_topic_scope import agent_mqtt_connection
from scenegems_tool.vessel_stack.contracts.docker_stack import DockerControlLayer, DockerSimulationLayer, DockerStackArtifacts, DockerStackRequest
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from scenegems_tool.vessel_stack.contracts.roles import LayerRef
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig
from scenegems_tool.vessel_stack.registry.adapter_registry import AdapterRegistry
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from scenegems_tool.vessel_stack.registry.resolver import StackUnavailableError
from utils.file_system_utils import GAZEBO_GEN_MOUNT, SIMULATION_GEN_FOLDER, docker_volume_path, merge_compose_volumes

SIMULATION_COMPOSE_PROJECT = "asv_maritime_net"
_logger = logging.getLogger(__name__)
_STANDALONE_COMPOSE_FILENAME = f"{SIMULATION_GEN_FOLDER}/docker-compose.yml"


def _docker_runtime(registry: AdapterRegistry, ref: LayerRef, kind: type) -> object:
    runtime_class = registry.runtime(str(ref))
    if not issubclass(runtime_class, kind):
        raise StackUnavailableError([f"{ref} has no Docker stack adapter"])
    return runtime_class()


def build_simulation_docker_stack_artifacts(
    simulation_config: SimulationInstanceConfig,
    trajectories: Trajectories,
    mqtt_connection: MQttConnectionInfo,
    reference_geofence: Geofence,
    *,
    headless: bool = True,
    embedded_in_subsystem: bool = False,
    gen_folder: str = SIMULATION_GEN_FOLDER,
) -> Tuple[List[Tuple[str, str]], dict]:
    """The files to write and the compose services of one instance. gen_folder must lie on the runtime assets volume."""
    resolver = default_resolver()
    resolution = resolver.require_instance(simulation_config)
    for warning in resolution.warnings:
        _logger.warning("Simulation stack: %s", warning)

    request = DockerStackRequest(
        simulation=simulation_config,
        trajectories=trajectories,
        # ArduAgent containers publish under the session's prefix only when every vessel is simulated.
        mqtt_connection=agent_mqtt_connection(mqtt_connection, simulation_config),
        reference_geofence=reference_geofence,
        headless=headless,
        gen_folder=gen_folder,
        mounted_gen_folder=GAZEBO_GEN_MOUNT if gen_folder == SIMULATION_GEN_FOLDER else docker_volume_path(gen_folder),
    )
    artifacts = DockerStackArtifacts()
    simulation_layer = _docker_runtime(resolver.registry, LayerRef.of(simulation_config.simulation_layer), DockerSimulationLayer)
    for agent_id, vessel_config in simulation_config.vessels.items():
        vessel = trajectories.initial_scene.get_by_id(agent_id)
        if not isinstance(vessel, ConcreteVessel):
            raise ValueError(f"Vessel {vessel} is not a ConcreteVessel.")
        if not vessel_config.is_simulated:
            continue
        state = trajectories.initial_scene[vessel]
        control_layer = _docker_runtime(resolver.registry, LayerRef.of(vessel_config.stack.control_layer), DockerControlLayer)
        simulation_layer.add_vessel(artifacts, request, vessel_config, vessel, state)
        control_layer.add_vessel(artifacts, request, vessel_config, vessel, state)
    simulation_layer.finish(artifacts, request)
    # The scenario execution worker reads the trajectories from the shared gen folder.
    artifacts.pending_writes.append((f"{gen_folder}/trajectories.json", json.dumps(trajectories.to_dict())))

    if embedded_in_subsystem:
        maritime_network = {"maritime_net": {"driver": "bridge"}}
    else:
        maritime_network = {"maritime_net": {"name": SIMULATION_COMPOSE_PROJECT, "driver": "bridge"}}

    docker_compose = merge_compose_volumes(
        {
            "services": artifacts.services,
            "networks": maritime_network,
        }
    )
    return artifacts.pending_writes, docker_compose


def write_simulation_gen_files(pending_writes: List[Tuple[str, str]], gen_folder: str = SIMULATION_GEN_FOLDER) -> None:
    os.makedirs(gen_folder, exist_ok=True)
    for path, content in pending_writes:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            file.write(content)


def destroy_simulation_docker_stack() -> None:
    """Remove legacy standalone Gazebo/SITL stacks from older two-stack startups."""
    ids = subprocess.check_output(
        ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={SIMULATION_COMPOSE_PROJECT}"],
        text=True,
    ).split()
    if ids:
        subprocess.run(["docker", "rm", "-f", *ids], check=False)


def run_simulation_docker_stack_startup(
    pending_writes: List[Tuple[str, str]],
    docker_compose: dict,
    compose_filename: str,
    shutdown_event: Optional[threading.Event] = None,
) -> None:
    try:
        if shutdown_event is not None and shutdown_event.is_set():
            return
        destroy_simulation_docker_stack()
        write_simulation_gen_files(pending_writes)
        if shutdown_event is not None and shutdown_event.is_set():
            return
        with open(compose_filename, "w", encoding="utf-8") as file:
            yaml.dump(docker_compose, file, default_flow_style=False, sort_keys=False, width=10000)
        if shutdown_event is not None and shutdown_event.is_set():
            return
        subprocess.run(
            [
                "docker-compose",
                "-f",
                compose_filename,
                "--project-name",
                SIMULATION_COMPOSE_PROJECT,
                "up",
                "-d",
                "--no-build",
            ],
            check=False,
        )
    except BaseException:
        _logger.exception("Simulation docker stack startup failed")
