import logging
import threading
from typing import List, Optional, Protocol

from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.scene_builder import SceneBuilder
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.simulators.simulation_config import SimulationConfig
from scenegems_tool.simulators.simulation_docker_stack import (
    _STANDALONE_COMPOSE_FILENAME,
    SIMULATION_COMPOSE_PROJECT,
    build_simulation_docker_stack_artifacts,
    destroy_simulation_docker_stack,
    run_simulation_docker_stack_startup,
)

__all__ = ["SimulationParser", "SimulationParentClient", "SIMULATION_COMPOSE_PROJECT"]
from scenegems_tool.waraps_integration.mqtt_agent_client import ExecutionState, MqttAgentClient
from scenegems_tool.waraps_integration.mqtt_client import MQttConnectionInfo
from scenegems_tool.waraps_integration.sim_utils import Geofence, waypoint_from_state

_logger = logging.getLogger(__name__)


class SimulationParentClient(Protocol):
    name: str
    reference_geofence: Geofence


class SimulationParser:

    HEADLESS = True
    """Owns MQTT agent clients and optionally Docker Compose lifecycle for the Gazebo/SITL stack."""

    def __init__(
        self,
        simulation_config: SimulationConfig,
        trajectories: Trajectories,
        mqtt_connection: MQttConnectionInfo,
        parent_client: SimulationParentClient,
        *,
        spawn_docker_stack: bool = True,
    ):
        self.simulation_config = simulation_config
        self.clients: List[MqttAgentClient] = []
        self._spawn_docker_stack = spawn_docker_stack
        self._shutdown = threading.Event()
        self._lifecycle_thread: Optional[threading.Thread] = None

        builder = TrajectoryBuilder.from_trajectories(trajectories).convert_to_max_scene_number(400)

        pending_writes = None
        docker_compose = None
        compose_filename = None
        if spawn_docker_stack:
            pending_writes, docker_compose = build_simulation_docker_stack_artifacts(
                simulation_config,
                trajectories,
                mqtt_connection,
                parent_client.reference_geofence,
                headless=self.HEADLESS,
            )
            compose_filename = _STANDALONE_COMPOSE_FILENAME

        for agent_id, agent_config in self.simulation_config.simulated_agents.items():
            vessel = trajectories.initial_scene.get_by_id(agent_id)
            if not isinstance(vessel, ConcreteVessel):
                raise ValueError(f"Vessel {vessel} is not a ConcreteVessel.")

            state = trajectories.initial_scene[vessel]
            max_speed = trajectories.get_max_speed(vessel)

            state_list = builder.build().state_list(vessel)
            first_index_with_max_speed = next((i for i, s in enumerate(state_list) if s.speed > max_speed * 0.9), 0)
            mission_waypoints = [waypoint_from_state(s, parent_client.reference_geofence) for s in state_list[first_index_with_max_speed:]]

            client = MqttAgentClient(
                vessel=vessel,
                mqtt_connection=mqtt_connection,
                topic=agent_config.topic,
                control_mode=agent_config.control_mode,
                agent_name=agent_config.agent_name,
                reference_geofence=parent_client.reference_geofence,
                initial_state=state,
                parent_service_name=parent_client.name,
                mission_waypoints=mission_waypoints,
            )
            client.connect()
            self.clients.append(client)
            client.publish_trajectory([[point["latitude"], point["longitude"]] for point in mission_waypoints])

        if spawn_docker_stack and pending_writes is not None and docker_compose is not None and compose_filename is not None:
            self.compose_filename = compose_filename
            self._lifecycle_thread = threading.Thread(
                target=run_simulation_docker_stack_startup,
                args=(pending_writes, docker_compose, compose_filename, self._shutdown),
                name="simulation_parser_compose",
                daemon=True,
            )
            self._lifecycle_thread.start()

    @property
    def os_client(self) -> MqttAgentClient:
        os_client = next((client for client in self.clients if client.actor.is_os), None)
        if os_client is None:
            raise ValueError("No OS client found")
        return os_client

    @property
    def are_agents_initialized(self) -> bool:
        return all(client.is_connected and client.position_received for client in self.clients)

    @property
    def are_agents_ready(self) -> bool:
        return self.are_agents_initialized and all(client.is_armable and client.at_start_point() for client in self.clients)

    @property
    def get_current_scene(self) -> ConcreteScene:
        builder = SceneBuilder()
        for client in self.clients:
            builder.set_state(client.actor, client.current_agent_state)
        return builder.build()

    @property
    def are_agents_running(self) -> bool:
        return self.are_agents_initialized and all(client.execution_state == ExecutionState.RUNNING for client in self.clients)

    def destroy(self) -> None:
        for client in self.clients:
            client.disconnect()
        self._shutdown.set()
        if self._lifecycle_thread is not None:
            self._lifecycle_thread.join(timeout=120.0)
            self._lifecycle_thread = None
        if self._spawn_docker_stack:
            destroy_simulation_docker_stack()

    @property
    def clock(self) -> float:
        return max(client.clock for client in self.clients)
