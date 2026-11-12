"""Scenes and trajectories shared by the vessel stack tests: the controlled encounters of the calibration package and stack instances."""

from typing import Sequence

import numpy as np

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.calibration.reference_scenarios import (  # noqa: F401  re-exported for the tests
    ENCOUNTER_TARGETS,
    SPEED,
    encounter_scene,
    encounter_trajectories,
    make_vessel,
)
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import (
    AgentConnection,
    EnvironmentConfig,
    SimulationInstanceConfig,
    VesselConfig,
    VesselStackConfig,
)

GEOFENCE = Geofence(57.757128, 16.673189, 5000)


def straight_trajectories(length: float = 30.0, speed: float = SPEED, timespan: int = 60) -> Trajectories:
    """One own ship heading east at constant speed."""
    scene = ConcreteScene({make_vessel(0, True, length=length): ActorState(0.0, 0.0, speed, 0.0)})
    return TrajectoryBuilder.default_trajectory_from_scene(scene, 1, timespan)


def mqtt_connection() -> MQttConnectionInfo:
    return MQttConnectionInfo(user="user", password="password", agent_broker="broker", client_broker="broker", port=1883, tls_connection=False, allow_certificates=False)


def stack_instance(
    simulation_layer: SimulationLayerId,
    vessel_ids: Sequence[int],
    asv_system: AsvSystemId = AsvSystemId.REPLAY,
    control_layer: ControlLayerId = ControlLayerId.ARDUPILOT,
    *,
    environment: EnvironmentConfig | None = None,
    speedup: int = 1,
    adapter_ids: Sequence[str] = (),
) -> SimulationInstanceConfig:
    """An instance with the same triple on every vessel, each with an agent connection."""
    stack = VesselStackConfig(asv_system=asv_system, control_layer=control_layer, simulation_layer=simulation_layer)
    return SimulationInstanceConfig(
        simulation_layer=simulation_layer,
        environment=environment or EnvironmentConfig.calm(),
        speedup=speedup,
        vessels={
            str(vessel_id): VesselConfig(
                agent_id=str(vessel_id),
                stack=stack,
                connection=AgentConnection(agent_name=f"agent_{vessel_id}", topic=f"waraps/unit/surface/agent_{vessel_id}"),
                adapter_ids=tuple(adapter_ids),
            )
            for vessel_id in vessel_ids
        },
    )


def wind_environment(east: float = 0.0, north: float = 5.0) -> EnvironmentConfig:
    environment = EnvironmentConfig.calm()
    environment.wind_vector = np.array([east, north, 0.0])
    return environment
