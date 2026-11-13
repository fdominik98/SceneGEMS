"""Specs of the MOOS-IvP ASV system and its adapters.

MOOS-IvP (github.com/moos-ivp/moos-ivp; the apps and the COLREGS behaviours are GPLv3, libMOOS
LGPL) is the autonomy software of MIT's marine robotics group. The part SceneGEMS runs is its
helm, pHelmIvP: it takes the own ship's position, heading and speed and the reports of the
vessels around it, and decides a heading and a speed, with a waypoint behaviour for the transit
and a collision avoidance behaviour per contact (the COLREGS behaviour BHV_AvdColregsV22, or
the rule-free BHV_AvoidCollision).

It is a plug and play component, like USV Navigation: one container per vessel that holds a
MOOSDB, pHelmIvP, a small bridge client and its server (moos_ivp_server.py), and nothing else of
SceneGEMS. The image (deploy/images/moos_ivp) builds MOOS-IvP from the commit pinned in
deploy/images/upstream_pins.env (MOOS_IVP_REPO, MOOS_IVP_COMMIT): a fork whose libMOOS takes its
time from a clock the server steps, so the helm runs exactly one pass per simulation step and a
run repeats.

The adapters differ in what takes the helm's heading and speed, as USV Navigation's do: the
kinematic layer itself, the custom controller's autopilot on Gazebo, or ArduPilot as GUIDED
targets over the lockstep MAVLink link. The simulation job's runners run them in mode moos_ivp
(cluster/worker_node/jobs/simulation_runners/kinematic_runner.py), with the helm on the own ship.
"""

from scenegems_tool.vessel_stack.contracts.adapter_spec import UPSTREAM_PINS_FILE, AdapterSpec, ContainerSpec, LayerSpec, image_reference
from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities, RepeatabilityTier
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, LayerRef

MOOS_IVP_SERVER_SOURCE = "backend/src/scenegems_tool/vessel_stack/asv_system/moos_ivp/moos_ivp_server.py"  # copied into the image
LOCKSTEP_WIRE_SOURCE = "backend/src/scenegems_tool/vessel_stack/contracts/lockstep_wire.py"  # copied into the image

MOOS_IVP_CONTAINER = ContainerSpec(
    image=image_reference("MOOS_IVP_IMAGE", "scenegems-moos-ivp"),
    build_fingerprint_source="deploy/images/moos_ivp",
    entrypoint="python3 -m scenegems_tool.vessel_stack.asv_system.moos_ivp.moos_ivp_server",
    upstream_pins_file=UPSTREAM_PINS_FILE,
    extra_fingerprint_sources=(MOOS_IVP_SERVER_SOURCE, LOCKSTEP_WIRE_SOURCE),
)

MOOS_IVP_LAYER = LayerSpec(
    layer=LayerRef.of(AsvSystemId.MOOS_IVP),
    description="MOOS-IvP's helm (pHelmIvP with a waypoint and a collision avoidance behaviour) in its own image, one container per vessel, one helm pass per step of the simulation clock.",
    requires_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
    containers=(MOOS_IVP_CONTAINER,),
)

MOOS_IVP_HEADING_SPEED = AdapterSpec(
    id="moos_ivp_heading_speed",
    source=LayerRef.of(AsvSystemId.MOOS_IVP),
    target=LayerRef.of(ControlLayerId.NONE),
    description="MOOS-IvP on the heading_speed_cmd port: the helm's desired heading and speed of every step, straight into the simulation layer.",
    # The pace is the helm's, not measured on the SceneGEMS layers until registry/measured_capabilities.yaml says so.
    capabilities=Capabilities(max_speedup=None),
    provides_ports=frozenset({Port.HEADING_SPEED_CMD}),
    requires_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
)

MOOS_IVP_CUSTOM_CONTROLLER_INPUT = AdapterSpec(
    id="moos_ivp_custom_controller_input",
    source=LayerRef.of(AsvSystemId.MOOS_IVP),
    target=LayerRef.of(ControlLayerId.CUSTOM),
    description="MOOS-IvP's desired heading and speed are the setpoints of the vessel's custom controller container (gz_lockstep_runner.py).",
    capabilities=Capabilities(max_speedup=None),
    provides_ports=frozenset({Port.HEADING_SPEED_CMD}),
    requires_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
)

MOOS_IVP_MAVLINK_LOCKSTEP = AdapterSpec(
    id="moos_ivp_mavlink_lockstep",
    source=LayerRef.of(AsvSystemId.MOOS_IVP),
    target=LayerRef.of(ControlLayerId.ARDUPILOT),
    description=(
        "MOOS-IvP driving ArduPilot over MAVLink: the runner sends the helm's desired heading and speed as GUIDED targets on simulation-time step boundaries "
        "read from SITL, as replay_mavlink_lockstep does for the replay follower. No MAVProxy or ArduAgent."
    ),
    # The same link as replay_mavlink_lockstep: SITL is not held while a command is in flight.
    capabilities=Capabilities(lockstep=True, repeatability_tier=RepeatabilityTier.BOUNDED, max_speedup=None),
    provides_ports=frozenset({Port.HEADING_SPEED_CMD, Port.MAVLINK}),
    requires_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
)
