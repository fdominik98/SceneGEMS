"""Specs of the custom control layer and of the replay route into it.

The custom controller is SceneGEMS's own heading and speed autopilot for a twin
differential-thrust hull (twin_thrust_autopilot.py), for Gazebo only. Every vessel has its own
controller container (custom_controller_server.py). The runner carries its thrusts to the hull
through the gz-transport actuator adapter (simulation_layers/gazebo/gz_transport_actuator.py),
which steps the paused world, so controller and physics share one clock.
"""

from scenegems_tool.vessel_stack.asv_system.replay.replay_specs import REPLAY_CONTAINER
from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, LayerSpec
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, LayerRef
from scenegems_tool.vessel_stack.contracts.stack_services import backend_component_container

CUSTOM_CONTROLLER_CONTAINER = backend_component_container("scenegems_tool.vessel_stack.control_layers.custom.custom_controller_server")

CUSTOM_CONTROL_LAYER = LayerSpec(
    layer=LayerRef.of(ControlLayerId.CUSTOM),
    description=(
        "Own heading and speed autopilot for twin differential thrust: a surge loop sets the common thrust and a yaw loop the differential thrust, "
        "with gains from the generated hull model. One container per vessel. Gazebo only."
    ),
    provides_ports=frozenset({Port.ACTUATOR_CMD}),
    requires_ports=frozenset({Port.HEADING_SPEED_CMD, Port.WAYPOINT_MISSION}),
    containers=(CUSTOM_CONTROLLER_CONTAINER,),
)

CUSTOM_CONTROLLER_WAYPOINT_FOLLOWER = AdapterSpec(
    id="custom_controller_waypoint_follower",
    source=LayerRef.of(AsvSystemId.REPLAY),
    target=LayerRef.of(ControlLayerId.CUSTOM),
    description=(
        "Line-of-sight waypoint follower inside the custom controller (los_waypoint_follower.py): the replay container hands the replayed trajectory "
        "over as the waypoint mission, steered by its geometry and paced by its timing."
    ),
    provides_ports=frozenset({Port.WAYPOINT_MISSION}),
    requires_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
    containers=(REPLAY_CONTAINER,),
)


def los_waypoint_follower_runtime():
    """Runtime of CUSTOM_CONTROLLER_WAYPOINT_FOLLOWER, imported on first use."""
    from scenegems_tool.vessel_stack.control_layers.custom.los_waypoint_follower import LosWaypointFollower

    return LosWaypointFollower
