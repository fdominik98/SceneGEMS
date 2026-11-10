import logging
import threading
from typing import List, Optional, Protocol

from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.scene_builder import SceneBuilder
from scenegems_tool.vessel_stack.agent_topic_scope import agent_mqtt_connection
from scenegems_tool.vessel_stack.asv_system.replay.replay_mission import cap_mission_trajectories, replay_mission_waypoints
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig
from scenegems_tool.vessel_stack.control_layers.ardupilot.arduagent_control_mode import ARDUAGENT_ADAPTER_IDS, arduagent_control_mode
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from scenegems_tool.vessel_stack.registry.resolver import StackUnavailableError
from scenegems_tool.vessel_stack.simulation_docker_stack import (
    _STANDALONE_COMPOSE_FILENAME,
    SIMULATION_COMPOSE_PROJECT,
    build_simulation_docker_stack_artifacts,
    destroy_simulation_docker_stack,
    run_simulation_docker_stack_startup,
)

__all__ = ["SimulationParser", "SimulationParentClient", "SIMULATION_COMPOSE_PROJECT"]
from scenegems_tool.messaging.mqtt_agent_client import ExecutionState, MqttAgentClient
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

_logger = logging.getLogger(__name__)


class SimulationParentClient(Protocol):
    name: str
    reference_geofence: Geofence


class SimulationParser:

    HEADLESS = True
    """Owns the ArduAgent MQTT clients of a resolved instance and optionally the Docker Compose lifecycle of its stack."""

    def __init__(
        self,
        simulation_config: SimulationInstanceConfig,
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

        resolution = default_resolver().require_instance(simulation_config)
        for warning in resolution.warnings:
            _logger.warning("Simulation stack: %s", warning)
        # This parser drives vessels through ArduAgent over MQTT. Vessels on the lockstep MAVLink
        # adapter have no ArduAgent; control_layers/ardupilot/mavlink_lockstep_runner.py runs them.
        not_arduagent = [
            f"vessel {agent_id} uses {chain.asv_adapter.id if chain.asv_adapter else 'no adapter'}"
            for agent_id, chain in resolution.chains.items()
            if chain.asv_adapter is None or chain.asv_adapter.id not in ARDUAGENT_ADAPTER_IDS
        ]
        if not_arduagent:
            raise StackUnavailableError([f"the scenario execution worker drives vessels only through ArduAgent: {', '.join(not_arduagent)}"])
        mission_trajectories = cap_mission_trajectories(trajectories)
        # The service's own topics carry the session's prefix; a real vessel's ArduAgent, and so every agent of its instance, the unscoped ones.
        agent_connection = agent_mqtt_connection(mqtt_connection, simulation_config)

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

        for agent_id, vessel_config in self.simulation_config.vessels.items():
            vessel = trajectories.initial_scene.get_by_id(agent_id)
            if not isinstance(vessel, ConcreteVessel):
                raise ValueError(f"Vessel {vessel} is not a ConcreteVessel.")

            state = trajectories.initial_scene[vessel]
            # Replay follows the whole mission; external control (mission_planner) is sent to its last waypoint.
            mission_waypoints = replay_mission_waypoints(mission_trajectories, vessel, trajectories.get_max_speed(vessel), parent_client.reference_geofence)

            agent_config = vessel_config.require_connection()
            client = MqttAgentClient(
                vessel=vessel,
                mqtt_connection=agent_connection,
                topic=agent_config.topic,
                control_mode=arduagent_control_mode(vessel_config.stack.asv_system),
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
    def simulator_clocks(self) -> List[float]:
        """Simulated time each ArduAgent reports from its SITL (SYSTEM_TIME), in seconds; 0 until the first report."""
        return [client.clock for client in self.clients]
