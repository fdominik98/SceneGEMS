"""Specs of the mission_planner ASV system: an operator or external software on a MAVLink port.

Two adapters connect it to ArduPilot:

- mission_planner_gcs_port (the default, WP7): MAVProxy on the vessel's SITL SERIAL1 with one
  TCP ground control station endpoint per vessel, published on a host port Docker assigns
  and reported in the simulation status. No ArduAgent: the operator flies the vessel, and
  the lockstep runner only watches it on SERIAL0 so the other vessels see it.
- mission_planner_mavlink_port (Phase 1, the alternative for instances with real vessels,
  which run through ArduAgent): ArduAgent sends the vessel toward the last waypoint of its
  trajectory and MAVProxy forwards it to a UDP ground control station port on the host.
"""

from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, LayerSpec
from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities, RepeatabilityTier
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, LayerRef
from scenegems_tool.vessel_stack.control_layers.ardupilot.ardupilot_specs import ARDUAGENT_CONTAINER, MAVPROXY_CONTAINER

MISSION_PLANNER_LAYER = LayerSpec(
    layer=LayerRef.of(AsvSystemId.MISSION_PLANNER),
    description="A human operator or external software on a MAVLink endpoint (the workbench's external control mode).",
    # A person in the loop is neither stepped by the simulation clock nor repeatable. The
    # pace stays the operator's choice, so it does not cap the speedup.
    capabilities=Capabilities(lockstep=False, repeatability_tier=RepeatabilityTier.NONE, interactive_only=True),
    restriction_notes=(("interactive_only", "a person drives the vessel, so it is not used in unattended campaigns"),),
    requires_ports=frozenset({Port.MAVLINK}),
)

MISSION_PLANNER_MAVLINK_PORT = AdapterSpec(
    id="mission_planner_mavlink_port",
    source=LayerRef.of(AsvSystemId.MISSION_PLANNER),
    target=LayerRef.of(ControlLayerId.ARDUPILOT),
    description="Exposed MAVLink port: MAVProxy forwards each vessel to a UDP ground control station port, and ArduAgent sends the vessel toward its last waypoint.",
    capabilities=Capabilities(lockstep=False),
    provides_ports=frozenset({Port.MAVLINK}),
    containers=(MAVPROXY_CONTAINER, ARDUAGENT_CONTAINER),
)

GCS_CONTAINER_PORT = 5770  # MAVProxy's TCP endpoint for the ground control station, inside its container

MISSION_PLANNER_GCS_PORT = AdapterSpec(
    id="mission_planner_gcs_port",
    source=LayerRef.of(AsvSystemId.MISSION_PLANNER),
    target=LayerRef.of(ControlLayerId.ARDUPILOT),
    description=(
        "One ground control station endpoint per vessel: MAVProxy on the vessel's SITL SERIAL1 listens on TCP, "
        "published on a host port Docker assigns and reported in the simulation status. The operator flies the "
        "vessel; nothing else commands it."
    ),
    capabilities=Capabilities(lockstep=False),
    provides_ports=frozenset({Port.MAVLINK}),
    containers=(MAVPROXY_CONTAINER,),
)
