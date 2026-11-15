"""Specs of the ardupilot_sim simulation layer: the internal physics of ArduPilot SITL."""

from logical_level.mapping.vessel_type import SteeringType
from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, LayerSpec
from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities, EnvironmentSupport, RepeatabilityTier
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId, LayerRef, SimulationLayerId

ARDUPILOT_SIM_LAYER = LayerSpec(
    layer=LayerRef.of(SimulationLayerId.ARDUPILOT_SIM),
    description="ArduPilot SITL's built-in motorboat physics, homed at the start pose of each vessel. No separate simulator container.",
    # SITL's boat (libraries/SITL/SIM_Sailboat.cpp) steers by a rudder or, on a frame with "skid" in its name, by its two motors.
    capabilities=Capabilities(wind=EnvironmentSupport.SUPPORTED, waves=EnvironmentSupport.UNMEASURED, steering_types=frozenset({SteeringType.RUDDER, SteeringType.SKID})),
    restriction_notes=(
        ("waves", "SITL receives the SIM_WAVE_* parameters, but their effect on a boat is not measured yet"),
        ("steering_types", "SITL's boat steers by a rudder (frame motorboat) or by the difference of two motors (frame motorboat-skid) and has no thruster that turns"),
    ),
    provides_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
    requires_ports=frozenset({Port.ENVIRONMENT}),
)

SITL_INTERNAL_PHYSICS = AdapterSpec(
    id="sitl_internal_physics",
    source=LayerRef.of(ControlLayerId.ARDUPILOT),
    target=LayerRef.of(SimulationLayerId.ARDUPILOT_SIM),
    description="ArduPilot drives its own SITL physics in one process (SITL_SIMULATOR=ardupilot), paced by SITL --speedup.",
    # Bounded and unmeasured until measured; registry/measured_capabilities.yaml holds the values.
    capabilities=Capabilities(repeatability_tier=RepeatabilityTier.BOUNDED, max_speedup=None),
    provides_ports=frozenset({Port.ACTUATOR_CMD}),
    requires_ports=frozenset({Port.VESSEL_STATE}),
    built_in=True,
)
