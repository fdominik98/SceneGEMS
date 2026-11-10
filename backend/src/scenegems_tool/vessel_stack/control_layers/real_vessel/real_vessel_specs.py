"""Specs of the real_vessel control layer: a physical vessel's own autopilot, and the ArduAgent adapters into it.

A real vessel covers two roles: its autopilot is the control layer and its hull in the water
the simulation layer (simulation_layers/real_vessel/real_vessel_specs.py), joined by a built-in
adapter. SceneGEMS reaches it only through the vessel's ArduAgent over MQTT, so every adapter
into it is an ArduAgent mode: replay uploads the trajectory as a mission, Mission Planner sends
the vessel toward its last waypoint and leaves it to the operator, and on_board leaves the
vessel to its own software while ArduAgent reports its position.

A real vessel is run from the workbench only, never in a campaign, and only in real time.
"""

from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, LayerSpec
from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities, RepeatabilityTier
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, LayerRef

# What every part of a real vessel restricts: it moves on the wall clock, once.
REAL_VESSEL_CAPABILITIES = Capabilities(faster_than_real_time=False, lockstep=False, repeatability_tier=RepeatabilityTier.NONE, interactive_only=True)
REAL_VESSEL_INTERACTIVE_NOTE = ("interactive_only", "a physical vessel is run from the workbench only, never in a campaign")

REAL_VESSEL_CONTROL_LAYER = LayerSpec(
    layer=LayerRef.of(ControlLayerId.REAL_VESSEL),
    description="The physical vessel's own autopilot, reached over MQTT through the ArduAgent on board.",
    capabilities=REAL_VESSEL_CAPABILITIES,
    restriction_notes=(REAL_VESSEL_INTERACTIVE_NOTE,),
    provides_ports=frozenset({Port.WAYPOINT_MISSION, Port.MAVLINK}),
    requires_ports=frozenset({Port.VESSEL_STATE}),
    on_board_asv_system=True,
)

REPLAY_ARDUAGENT_REAL_VESSEL = AdapterSpec(
    id="replay_arduagent_real_vessel",
    source=LayerRef.of(AsvSystemId.REPLAY),
    target=LayerRef.of(ControlLayerId.REAL_VESSEL),
    description="ArduAgent on the vessel takes the thinned trajectory as a mission over MQTT and the autopilot follows it (ArduAgent's autonomous mode).",
    capabilities=Capabilities(lockstep=False),
    provides_ports=frozenset({Port.WAYPOINT_MISSION}),
    requires_ports=frozenset({Port.VESSEL_STATE}),
)

MISSION_PLANNER_ARDUAGENT_REAL_VESSEL = AdapterSpec(
    id="mission_planner_arduagent_real_vessel",
    source=LayerRef.of(AsvSystemId.MISSION_PLANNER),
    target=LayerRef.of(ControlLayerId.REAL_VESSEL),
    description="ArduAgent sends the vessel toward its last waypoint over MQTT; the operator flies it with Mission Planner on the vessel's own ground control link (ArduAgent's external mode).",
    capabilities=Capabilities(lockstep=False),
    provides_ports=frozenset({Port.MAVLINK}),
    requires_ports=frozenset({Port.VESSEL_STATE}),
)

ON_BOARD_ARDUAGENT_REAL_VESSEL = AdapterSpec(
    id="on_board_arduagent_real_vessel",
    source=LayerRef.of(AsvSystemId.ON_BOARD),
    target=LayerRef.of(ControlLayerId.REAL_VESSEL),
    description="The vessel's own software steers it; ArduAgent only reports its position over MQTT, so the simulation and the monitor see it. SceneGEMS sends it no command.",
    capabilities=Capabilities(lockstep=False),
    requires_ports=frozenset({Port.VESSEL_STATE}),
)
