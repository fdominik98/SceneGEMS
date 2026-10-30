"""Specs of the replay ASV software and the adapters it drives a control layer through."""

from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, LayerSpec
from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities, RepeatabilityTier
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, LayerRef
from scenegems_tool.vessel_stack.control_layers.ardupilot.ardupilot_specs import ARDUAGENT_CONTAINER, MAVPROXY_CONTAINER

REPLAY_LAYER = LayerSpec(
    layer=LayerRef.of(AsvSoftwareId.REPLAY),
    description="Follows the generated trajectory of the vessel (the workbench's autonomous control mode).",
)

REPLAY_STATE_FOLLOWER = AdapterSpec(
    id="replay_state_follower",
    source=LayerRef.of(AsvSoftwareId.REPLAY),
    target=LayerRef.of(ControlLayerId.NONE),
    description="Direct state follower in pure Python: heading and speed commands that track the trajectory, stepped only by the simulation clock.",
    provides_ports=frozenset({Port.HEADING_SPEED_CMD}),
    requires_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
)

REPLAY_ARDUAGENT_FOLLOWER = AdapterSpec(
    id="replay_arduagent_follower",
    source=LayerRef.of(AsvSoftwareId.REPLAY),
    target=LayerRef.of(ControlLayerId.ARDUPILOT),
    description="ArduAgent waypoint follower over MAVLink: the thinned trajectory is uploaded as an AUTO mission over WARA-PS MQTT and ArduPilot flies it in simulated time.",
    # ArduAgent runs on the wall clock (main loop 0.2 s, positions at 2 Hz), so it is not
    # stepped by the simulation clock. Its timing effect is part of the measured bounds of
    # the control and simulation pair.
    capabilities=Capabilities(lockstep=False),
    provides_ports=frozenset({Port.WAYPOINT_MISSION, Port.MAVLINK}),
    requires_ports=frozenset({Port.VESSEL_STATE}),
    containers=(MAVPROXY_CONTAINER, ARDUAGENT_CONTAINER),
)

# The default from replay to ardupilot. ArduAgent stays registered as the alternative the
# workbench selects (gateway/workbench_stack_mapping.py), because the browser workbench
# talks to its vessels over WARA-PS MQTT.
REPLAY_MAVLINK_LOCKSTEP = AdapterSpec(
    id="replay_mavlink_lockstep",
    source=LayerRef.of(AsvSoftwareId.REPLAY),
    target=LayerRef.of(ControlLayerId.ARDUPILOT),
    description="In-process ReplayFollower driving ArduPilot over MAVLink: GUIDED heading and speed targets sent on simulation-time step boundaries read from SITL, states recorded with SITL time. No MAVProxy or ArduAgent.",
    # Stepped by SITL time, so it has no wall-clock timer of its own. SITL is not held while a
    # command is in flight, so the tier stays bounded and max_speedup unknown until measured.
    capabilities=Capabilities(lockstep=True, repeatability_tier=RepeatabilityTier.BOUNDED, max_speedup=None),
    provides_ports=frozenset({Port.HEADING_SPEED_CMD, Port.MAVLINK}),
    requires_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
)


def mavlink_link_runtime():
    """Runtime of REPLAY_MAVLINK_LOCKSTEP, imported on first use so resolving needs no pymavlink."""
    from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_link import MavlinkLink

    return MavlinkLink
