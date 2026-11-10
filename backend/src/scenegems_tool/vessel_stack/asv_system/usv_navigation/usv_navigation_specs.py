"""Specs of the USV Navigation ASV system and its adapters.

USV Navigation is colav_automaton (github.com/michaelstolberger27/usv-navigation, MIT),
pinned to COLAV_AUTOMATON_COMMIT in backend/pyproject.toml and in its own image
(deploy/images/usv_navigation). It is a plug and play component: one container per vessel that
holds colav_automaton and its server (usv_navigation_server.py) and nothing else of SceneGEMS,
stepped by the simulation clock over the lockstep wire protocol. The adapters differ in what
takes its heading and speed: the kinematic layer itself, the custom controller's autopilot on
Gazebo (WP5c), or ArduPilot as GUIDED targets over the lockstep MAVLink link (WP5b).

The adapter ids keep their names (usv_navigation_in_process), since run records and the measured
capabilities refer to them.
"""

from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, ContainerSpec, LayerSpec, image_reference
from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities, RepeatabilityTier
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, LayerRef

COLAV_AUTOMATON_COMMIT = "54866f24a04987334057ae5c5896dfc3ee8ca058"

USV_NAVIGATION_SERVER_SOURCE = "backend/src/scenegems_tool/vessel_stack/asv_system/usv_navigation/usv_navigation_server.py"  # copied into the image
LOCKSTEP_WIRE_SOURCE = "backend/src/scenegems_tool/vessel_stack/contracts/lockstep_wire.py"  # copied into the image

USV_NAVIGATION_CONTAINER = ContainerSpec(
    image=image_reference("USV_NAVIGATION_IMAGE", "scenegems-usv-navigation"),
    build_fingerprint_source="deploy/images/usv_navigation",
    entrypoint="python -m scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_server",
    extra_fingerprint_sources=(USV_NAVIGATION_SERVER_SOURCE, LOCKSTEP_WIRE_SOURCE),
)

USV_NAVIGATION_LAYER = LayerSpec(
    layer=LayerRef.of(AsvSystemId.USV_NAVIGATION),
    description="USV Navigation (colav_automaton.SyncColavRuntime) in its own image, one container per vessel, stepped by the simulation clock.",
    requires_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
    containers=(USV_NAVIGATION_CONTAINER,),
)

USV_NAVIGATION_IN_PROCESS = AdapterSpec(
    id="usv_navigation_in_process",
    source=LayerRef.of(AsvSystemId.USV_NAVIGATION),
    target=LayerRef.of(ControlLayerId.NONE),
    description="USV Navigation on the heading_speed_cmd port: SyncColavRuntime.step_external every step, its output straight into the simulation layer.",
    provides_ports=frozenset({Port.HEADING_SPEED_CMD}),
    requires_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
)

CUSTOM_CONTROLLER_HEADING_SPEED_INPUT = AdapterSpec(
    id="custom_controller_heading_speed_input",
    source=LayerRef.of(AsvSystemId.USV_NAVIGATION),
    target=LayerRef.of(ControlLayerId.CUSTOM),
    description="USV Navigation's heading and speed commands are the setpoints of the vessel's custom controller container (gz_lockstep_runner.py).",
    provides_ports=frozenset({Port.HEADING_SPEED_CMD}),
    requires_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
)

USV_NAVIGATION_MAVLINK_LOCKSTEP = AdapterSpec(
    id="usv_navigation_mavlink_lockstep",
    source=LayerRef.of(AsvSystemId.USV_NAVIGATION),
    target=LayerRef.of(ControlLayerId.ARDUPILOT),
    description=(
        "USV Navigation driving ArduPilot over MAVLink: the runner sends its heading and speed as GUIDED targets on simulation-time step boundaries "
        "read from SITL, as replay_mavlink_lockstep does for the replay follower. No MAVProxy or ArduAgent."
    ),
    # The same link as replay_mavlink_lockstep: SITL is not held while a command is in flight.
    capabilities=Capabilities(lockstep=True, repeatability_tier=RepeatabilityTier.BOUNDED, max_speedup=None),
    provides_ports=frozenset({Port.HEADING_SPEED_CMD, Port.MAVLINK}),
    requires_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
)


def usv_navigation_participant_runtime():
    """The in-process participant of every USV Navigation route, imported on first use so resolving needs no numpy."""
    from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_participant import UsvNavigationParticipant

    return UsvNavigationParticipant
