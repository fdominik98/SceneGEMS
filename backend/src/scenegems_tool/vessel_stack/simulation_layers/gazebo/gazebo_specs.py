"""Specs of the Gazebo simulation layer and of the ArduPilot and custom controller links into it."""

from typing import Optional

from scenegems_tool.vessel_stack.contracts.adapter_spec import UPSTREAM_PINS_FILE, AdapterSpec, ContainerSpec, LayerSpec, image_reference
from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities, EnvironmentSupport, RepeatabilityTier
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId, LayerRef, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig
from utils.file_system_utils import GAZEBO_ENTRYPOINT_CONTAINER_PATH

# The Gazebo image builds asv_wave_sim (gz-waves1, ASV_WAVE_SIM_COMMIT in upstream_pins.env), so a
# world with waves replaces the flat Buoyancy system by a wave field and each vessel model carries
# the wave-aware buoyancy system on finer cells. Set it False for an image without asv_wave_sim:
# waves then leave the world flat, and the waves capability must say unsupported.
GAZEBO_WAVE_FORCES_AVAILABLE = True


def wave_forces_enabled(environment: Optional[EnvironmentConfig]) -> bool:
    """Whether the world and every vessel model use the asv_wave_sim wave field (decided once for both)."""
    return GAZEBO_WAVE_FORCES_AVAILABLE and environment is not None and environment.waves_requested


GZ_TRANSPORT_ACTUATOR_SOURCE = "backend/src/scenegems_tool/vessel_stack/simulation_layers/gazebo/gz_transport_actuator.py"  # copied into the image

GAZEBO_CONTAINER = ContainerSpec(
    image=image_reference("GAZEBO_IMAGE", "scenegems-gazebo-harmonic"),
    build_fingerprint_source="deploy/images/gazebo",
    entrypoint=GAZEBO_ENTRYPOINT_CONTAINER_PATH,
    upstream_pins_file=UPSTREAM_PINS_FILE,
    extra_fingerprint_sources=(GZ_TRANSPORT_ACTUATOR_SOURCE,),
)

GAZEBO_LAYER = LayerSpec(
    layer=LayerRef.of(SimulationLayerId.GAZEBO),
    description="Gazebo Harmonic with a generated ocean world and one parametric twin-thrust SDF model per vessel (buoyancy, hydrodynamics, thrusters, WindEffects wind on a windage link).",
    # Waves come from asv_wave_sim (GAZEBO_WAVE_FORCES_AVAILABLE); whether they are supported is a measurement.
    capabilities=Capabilities(wind=EnvironmentSupport.SUPPORTED, waves=EnvironmentSupport.UNMEASURED),
    provides_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
    requires_ports=frozenset({Port.ACTUATOR_CMD, Port.ENVIRONMENT}),
    containers=(GAZEBO_CONTAINER,),
)

ARDUPILOT_GAZEBO_PLUGIN = AdapterSpec(
    id="ardupilot_gazebo_plugin",
    source=LayerRef.of(ControlLayerId.ARDUPILOT),
    target=LayerRef.of(SimulationLayerId.GAZEBO),
    description="SITL with the JSON backend, linked to the ArduPilotPlugin of each generated vessel model (lock_step 1, thrust commands on the motor joints).",
    # Bounded and unmeasured until Phase 0 measures it; measured values replace these from
    # registry/measured_capabilities.yaml.
    capabilities=Capabilities(repeatability_tier=RepeatabilityTier.BOUNDED, max_speedup=None),
    provides_ports=frozenset({Port.ACTUATOR_CMD}),
    requires_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
)

GZ_TRANSPORT_ACTUATOR = AdapterSpec(
    id="gz_transport_actuator",
    source=LayerRef.of(ControlLayerId.CUSTOM),
    target=LayerRef.of(SimulationLayerId.GAZEBO),
    description=(
        "gz-transport actuator adapter in the Gazebo container (gz_transport_actuator.py): thrust as gz.msgs.Double on "
        "/model/<model>/joint/<joint>/cmd_thrust, odometry back, and the paused world stepped through its world control "
        "service, so controller and physics share one clock."
    ),
    # Unmeasured until measured; registry/measured_capabilities.yaml holds the values.
    capabilities=Capabilities(repeatability_tier=RepeatabilityTier.BOUNDED, max_speedup=None),
    provides_ports=frozenset({Port.ACTUATOR_CMD}),
    requires_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
)


def gz_lockstep_link_runtime():
    """Runtime of GZ_TRANSPORT_ACTUATOR on the runner's side, imported on first use."""
    from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_lockstep_link import GzLockstepLink

    return GzLockstepLink
