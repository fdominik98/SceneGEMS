"""Default registry: every layer, adapter and ruled-out connection of design section 3.3.

New ASV software, controllers or simulators are added by implementing their specs, their
container (a server for the lockstep wire protocol, contracts/lockstep_wire.py, and the class
that adds its service to a stack) and registering them here. An ASV software that a lockstep
runner steps also gets its entry in asv_software/asv_software_runtime.py. A spec can be
registered as planned (SpecStatus.PLANNED) so the resolver answers its rows before it exists;
since Phase 2 every "yes" row of the availability matrix is available.
"""

from functools import lru_cache
from typing import Mapping, Optional

from scenegems_tool.vessel_stack.asv_software.mission_planner.mission_planner_specs import MISSION_PLANNER_GCS_PORT, MISSION_PLANNER_LAYER, MISSION_PLANNER_MAVLINK_PORT
from scenegems_tool.vessel_stack.asv_software.on_board.on_board_specs import ON_BOARD_LAYER
from scenegems_tool.vessel_stack.asv_software.replay.replay_specs import REPLAY_ARDUAGENT_FOLLOWER, REPLAY_LAYER, REPLAY_MAVLINK_LOCKSTEP, REPLAY_STATE_FOLLOWER, mavlink_link_runtime
from scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_specs import (
    CUSTOM_CONTROLLER_HEADING_SPEED_INPUT,
    USV_NAVIGATION_IN_PROCESS,
    USV_NAVIGATION_LAYER,
    USV_NAVIGATION_MAVLINK_LOCKSTEP,
    usv_navigation_participant_runtime,
)
from scenegems_tool.vessel_stack.contracts.adapter_spec import LayerSpec, UnsupportedConnection
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, LayerRef, SimulationLayerId
from scenegems_tool.vessel_stack.control_layers.ardupilot.ardupilot_specs import ARDUPILOT_CONTROL_LAYER
from scenegems_tool.vessel_stack.control_layers.custom.custom_controller_specs import CUSTOM_CONTROL_LAYER, CUSTOM_CONTROLLER_WAYPOINT_FOLLOWER, los_waypoint_follower_runtime
from scenegems_tool.vessel_stack.control_layers.real_vessel.real_vessel_specs import (
    MISSION_PLANNER_ARDUAGENT_REAL_VESSEL,
    ON_BOARD_ARDUAGENT_REAL_VESSEL,
    REAL_VESSEL_CONTROL_LAYER,
    REPLAY_ARDUAGENT_REAL_VESSEL,
)
from scenegems_tool.vessel_stack.registry.adapter_registry import AdapterRegistry
from scenegems_tool.vessel_stack.registry.measured_capabilities import CapabilityMeasurement, load_capability_measurements
from scenegems_tool.vessel_stack.registry.resolver import StackResolver
from scenegems_tool.vessel_stack.simulation_layers.ardupilot_sim.ardupilot_sim_specs import ARDUPILOT_SIM_LAYER, SITL_INTERNAL_PHYSICS
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gazebo_specs import ARDUPILOT_GAZEBO_PLUGIN, GAZEBO_LAYER, GZ_TRANSPORT_ACTUATOR, gz_lockstep_link_runtime
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_specs import KINEMATIC_COMMAND_INPUT, KINEMATIC_LAYER
from scenegems_tool.vessel_stack.simulation_layers.real_vessel.real_vessel_specs import REAL_VESSEL_AUTOPILOT, REAL_VESSEL_SIMULATION_LAYER

_USV_NAVIGATION = LayerRef.of(AsvSoftwareId.USV_NAVIGATION)
_MISSION_PLANNER = LayerRef.of(AsvSoftwareId.MISSION_PLANNER)
_ON_BOARD = LayerRef.of(AsvSoftwareId.ON_BOARD)
_ARDUPILOT = LayerRef.of(ControlLayerId.ARDUPILOT)
_CUSTOM = LayerRef.of(ControlLayerId.CUSTOM)
_NONE = LayerRef.of(ControlLayerId.NONE)
_REAL_VESSEL_CONTROL = LayerRef.of(ControlLayerId.REAL_VESSEL)
_KINEMATIC = LayerRef.of(SimulationLayerId.KINEMATIC)
_GAZEBO = LayerRef.of(SimulationLayerId.GAZEBO)
_ARDUPILOT_SIM = LayerRef.of(SimulationLayerId.ARDUPILOT_SIM)
_REAL_VESSEL_SIMULATION = LayerRef.of(SimulationLayerId.REAL_VESSEL)

NONE_CONTROL_LAYER = LayerSpec(
    layer=_NONE,
    description="No separate controller: the simulation layer integrates control itself.",
)

# The "no" rows of the availability matrix, with the reasons the design gives.
UNSUPPORTED_CONNECTIONS = (
    UnsupportedConnection(_MISSION_PLANNER, _NONE, "control layer none has no MAVLink endpoint (it only drives the kinematic sim, which has none)"),
    UnsupportedConnection(_MISSION_PLANNER, _CUSTOM, "the custom controller has no MAVLink"),
    UnsupportedConnection(_NONE, _GAZEBO, "Gazebo needs actuator commands"),
    UnsupportedConnection(_NONE, _ARDUPILOT_SIM, "ardupilot_sim is the physics inside ArduPilot SITL, so its control layer is ardupilot"),
    UnsupportedConnection(_CUSTOM, _ARDUPILOT_SIM, "SITL physics only accepts ArduPilot control"),
    UnsupportedConnection(_ARDUPILOT, _KINEMATIC, "the kinematic sim integrates control internally"),
    UnsupportedConnection(_CUSTOM, _KINEMATIC, "the kinematic sim integrates control internally"),
    # A real vessel is reached only through its ArduAgent, and covers the control and simulation roles itself.
    UnsupportedConnection(_USV_NAVIGATION, _REAL_VESSEL_CONTROL, "a real vessel is reached only through ArduAgent, which has no command for USV Navigation's heading and speed references"),
    *(UnsupportedConnection(_ON_BOARD, control, "this control layer brings no ASV software of its own") for control in (_ARDUPILOT, _CUSTOM, _NONE)),
    *(UnsupportedConnection(_REAL_VESSEL_CONTROL, simulation, "a real vessel's autopilot drives only its own hull") for simulation in (_KINEMATIC, _GAZEBO, _ARDUPILOT_SIM)),
    *(UnsupportedConnection(control, _REAL_VESSEL_SIMULATION, "a real vessel is moved only by its own autopilot (control layer real_vessel)") for control in (_ARDUPILOT, _CUSTOM, _NONE)),
)


# Loaders import on first use, so resolving a stack stays free of the code that runs it.
# runtime: the class that runs a spec in the caller's process.
def _kinematic_simulation():
    from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_simulation import KinematicSimulation

    return KinematicSimulation


def _replay_follower():
    from scenegems_tool.vessel_stack.asv_software.replay.replay_follower import ReplayFollower

    return ReplayFollower


# docker: the class that adds a spec's containers to a stack (contracts/docker_stack.py).
def _kinematic_simulation_layer():
    from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_simulation_layer import KinematicSimulationLayer

    return KinematicSimulationLayer


def _replay_container():
    from scenegems_tool.vessel_stack.asv_software.replay.replay_service_generator import ReplayAsvSoftware

    return ReplayAsvSoftware


def _usv_navigation_container():
    from scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_service_generator import UsvNavigationAsvSoftware

    return UsvNavigationAsvSoftware


def _ardupilot_control_layer():
    from scenegems_tool.vessel_stack.control_layers.ardupilot.ardupilot_control_layer import ArduPilotControlLayer

    return ArduPilotControlLayer


def _custom_control_layer():
    from scenegems_tool.vessel_stack.control_layers.custom.custom_control_layer import CustomControlLayer

    return CustomControlLayer


def _gazebo_simulation_layer():
    from scenegems_tool.vessel_stack.simulation_layers.gazebo.gazebo_simulation_layer import GazeboSimulationLayer

    return GazeboSimulationLayer


def _ardupilot_sim_layer():
    from scenegems_tool.vessel_stack.simulation_layers.ardupilot_sim.ardupilot_sim_layer import ArduPilotSimLayer

    return ArduPilotSimLayer


def build_registry(measurements: Optional[Mapping[str, CapabilityMeasurement]] = None) -> AdapterRegistry:
    registry = AdapterRegistry(load_capability_measurements() if measurements is None else measurements)

    registry.register_layer(REPLAY_LAYER)
    registry.register_layer(USV_NAVIGATION_LAYER)
    registry.register_layer(MISSION_PLANNER_LAYER)
    registry.register_layer(ON_BOARD_LAYER)
    # A control or simulation layer brings its own containers. Control layer none is the absence of a controller and brings none.
    registry.register_layer(ARDUPILOT_CONTROL_LAYER, docker=_ardupilot_control_layer)
    registry.register_layer(CUSTOM_CONTROL_LAYER, docker=_custom_control_layer)
    registry.register_layer(NONE_CONTROL_LAYER)
    registry.register_layer(REAL_VESSEL_CONTROL_LAYER)
    registry.register_layer(KINEMATIC_LAYER, runtime=_kinematic_simulation, docker=_kinematic_simulation_layer)
    registry.register_layer(GAZEBO_LAYER, docker=_gazebo_simulation_layer)
    registry.register_layer(ARDUPILOT_SIM_LAYER, docker=_ardupilot_sim_layer)
    registry.register_layer(REAL_VESSEL_SIMULATION_LAYER)

    # An ASV software's container comes with the adapter that runs it: the routes a lockstep runner
    # steps have one per vessel, ArduAgent's and Mission Planner's are started by the ArduPilot control layer.
    registry.register_adapter(REPLAY_STATE_FOLLOWER, runtime=_replay_follower, docker=_replay_container)
    registry.register_adapter(USV_NAVIGATION_IN_PROCESS, runtime=usv_navigation_participant_runtime, docker=_usv_navigation_container)
    registry.register_adapter(REPLAY_ARDUAGENT_FOLLOWER)
    registry.register_adapter(REPLAY_MAVLINK_LOCKSTEP, runtime=mavlink_link_runtime, docker=_replay_container, default=True)
    registry.register_adapter(MISSION_PLANNER_GCS_PORT)
    # ArduAgent's external control mode, for the simulated vessels of instances with a real vessel (gateway/workbench_stack_mapping.py).
    registry.register_adapter(MISSION_PLANNER_MAVLINK_PORT, default=False)
    registry.register_adapter(KINEMATIC_COMMAND_INPUT)
    registry.register_adapter(SITL_INTERNAL_PHYSICS)
    registry.register_adapter(ARDUPILOT_GAZEBO_PLUGIN)
    registry.register_adapter(CUSTOM_CONTROLLER_WAYPOINT_FOLLOWER, runtime=los_waypoint_follower_runtime, docker=_replay_container)
    registry.register_adapter(GZ_TRANSPORT_ACTUATOR, runtime=gz_lockstep_link_runtime)
    registry.register_adapter(CUSTOM_CONTROLLER_HEADING_SPEED_INPUT, runtime=usv_navigation_participant_runtime, docker=_usv_navigation_container)
    registry.register_adapter(USV_NAVIGATION_MAVLINK_LOCKSTEP, runtime=mavlink_link_runtime, docker=_usv_navigation_container)
    # A real vessel: ArduAgent's modes into its autopilot, and the autopilot's built-in link to its hull.
    registry.register_adapter(REPLAY_ARDUAGENT_REAL_VESSEL)
    registry.register_adapter(MISSION_PLANNER_ARDUAGENT_REAL_VESSEL)
    registry.register_adapter(ON_BOARD_ARDUAGENT_REAL_VESSEL)
    registry.register_adapter(REAL_VESSEL_AUTOPILOT)

    for connection in UNSUPPORTED_CONNECTIONS:
        registry.declare_unsupported(connection)
    registry.check_measurements()
    return registry


@lru_cache(maxsize=1)
def default_registry() -> AdapterRegistry:
    return build_registry()


def default_resolver() -> StackResolver:
    return StackResolver(default_registry())
