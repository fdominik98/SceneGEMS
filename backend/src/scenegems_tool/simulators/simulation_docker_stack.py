import json
import logging
import os
import subprocess
import threading
from typing import List, Optional, Tuple

import yaml

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.trajectories import Trajectories
from scenegems_tool.simulators.gazeboo.ardu_param_generator import generate_ardu_params
from scenegems_tool.simulators.gazeboo.gazebo_service_generator import generate_gazebo_service
from scenegems_tool.simulators.gazeboo.vessel_model_generator import generate_vessel_model
from scenegems_tool.simulators.gazeboo.vessel_service_generator import generate_vessel_service
from scenegems_tool.simulators.gazeboo.world_generator import generate_world
from scenegems_tool.simulators.simulation_config import SimulationConfig
from scenegems_tool.waraps_integration.mqtt_agent_client import MqttAgentClient
from scenegems_tool.waraps_integration.mqtt_client import MQttConnectionInfo
from scenegems_tool.waraps_integration.sim_utils import Geofence
from utils.file_system_utils import GAZEBO_GEN_MOUNT, SIMULATION_GEN_FOLDER, merge_compose_volumes

SIMULATION_COMPOSE_PROJECT = "asv_maritime_net"
_logger = logging.getLogger(__name__)
_STANDALONE_COMPOSE_FILENAME = f"{SIMULATION_GEN_FOLDER}/docker-compose.yml"


def build_simulation_docker_stack_artifacts(
    simulation_config: SimulationConfig,
    trajectories: Trajectories,
    mqtt_connection: MQttConnectionInfo,
    reference_geofence: Geofence,
    *,
    headless: bool = True,
    embedded_in_subsystem: bool = False,
) -> Tuple[List[Tuple[str, str]], dict]:
    docker_services = {}
    vessel_includes: List[Tuple[str, ActorState]] = []
    pending_writes: List[Tuple[str, str]] = []

    for agent_id, agent_config in simulation_config.simulated_agents.items():
        vessel = trajectories.initial_scene.get_by_id(agent_id)
        if not isinstance(vessel, ConcreteVessel):
            raise ValueError(f"Vessel {vessel} is not a ConcreteVessel.")

        state = trajectories.initial_scene[vessel]
        if agent_config.context != "simulation":
            continue

        agent_stub = MqttAgentClient(
            vessel=vessel,
            mqtt_connection=mqtt_connection,
            topic=agent_config.topic,
            control_mode=agent_config.control_mode,
            agent_name=agent_config.agent_name,
            reference_geofence=reference_geofence,
            initial_state=state,
            parent_service_name="scenario_execution_service",
            mission_waypoints=[],
        )

        if agent_config.gazebo_vessel_model is not None:
            vessel_model = agent_config.gazebo_vessel_model
        else:
            vessel_model = generate_vessel_model(vessel, agent_config.agent_name)
        vessel_model_filename = f"{agent_config.agent_name}_model.sdf"
        vessel_model_file = f"{SIMULATION_GEN_FOLDER}/{vessel_model_filename}"
        pending_writes.append((vessel_model_file, vessel_model))
        vessel_includes.append((f"{GAZEBO_GEN_MOUNT}/{vessel_model_filename}", state))

        ardu_params = generate_ardu_params(
            vessel,
            trajectories.get_max_speed(vessel),
            simulation_config.wind_vector,
            simulation_config.wave,
        )
        params_file = f"{SIMULATION_GEN_FOLDER}/params-{agent_config.agent_name}.params"
        lines = []
        for key, value in ardu_params.items():
            if value is not None:
                lines.append(f"{key}\t{value}\n")
        pending_writes.append((params_file, "".join(lines)))
        docker_services.update(
            generate_vessel_service(
                agent_stub,
                agent_config.port,
                params_file,
                simulation_config.simulation_speed,
                simulation_config.is_ardupilot_sim,
            )
        )

    os_state = trajectories.initial_scene.os_state
    lat_long = reference_geofence.to_lat_long(os_state.p)
    world_model = generate_world(
        lat_long,
        vessel_includes,
        simulation_config.wind_vector,
        simulation_config.wave,
        simulation_config.simulation_speed,
        headless=headless,
    )
    world_file = f"{SIMULATION_GEN_FOLDER}/ocean_world.sdf"
    pending_writes.append((world_file, world_model))
    trajectories_file = f"{SIMULATION_GEN_FOLDER}/trajectories.json"
    pending_writes.append((trajectories_file, json.dumps(trajectories.to_dict())))

    if simulation_config.is_gazebo_sim:
        gazebo_service = generate_gazebo_service(
            world_file,
            [agent_config.agent_name for agent_config in simulation_config.simulated_agents.values()],
            headless=headless,
            display="host.docker.internal:0.0",
            verbose=4,
        )
        docker_services.update(gazebo_service)

    if embedded_in_subsystem:
        maritime_network = {"maritime_net": {"driver": "bridge"}}
    else:
        maritime_network = {"maritime_net": {"name": SIMULATION_COMPOSE_PROJECT, "driver": "bridge"}}

    docker_compose = merge_compose_volumes(
        {
            "services": docker_services,
            "networks": maritime_network,
        }
    )
    return pending_writes, docker_compose


def write_simulation_gen_files(pending_writes: List[Tuple[str, str]]) -> None:
    os.makedirs(SIMULATION_GEN_FOLDER, exist_ok=True)
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
