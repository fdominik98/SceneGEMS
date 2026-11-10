"""Specs of the kinematic simulation layer (ConcreteVessel.simulate), the simulated world of a scenario in its own container."""

from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, LayerSpec
from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities, EnvironmentSupport
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId, LayerRef, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.stack_services import backend_component_container

_NO_ENVIRONMENT_MODEL = "the kinematic model has no wind or wave forces"

KINEMATIC_SIM_CONTAINER = backend_component_container("scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_sim_server")

KINEMATIC_LAYER = LayerSpec(
    layer=LayerRef.of(SimulationLayerId.KINEMATIC),
    description=(
        "Own kinematic simulator: ConcreteVessel.simulate under the speed, acceleration and turn limits of each vessel, fixed dt, no wall clock. "
        "One container per scenario, stepped by the runner: the fast, simplified alternative to Gazebo."
    ),
    capabilities=Capabilities(wind=EnvironmentSupport.UNSUPPORTED, waves=EnvironmentSupport.UNSUPPORTED),
    restriction_notes=(("wind", _NO_ENVIRONMENT_MODEL), ("waves", _NO_ENVIRONMENT_MODEL)),
    provides_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
    requires_ports=frozenset({Port.HEADING_SPEED_CMD, Port.ENVIRONMENT}),
    containers=(KINEMATIC_SIM_CONTAINER,),
)

KINEMATIC_COMMAND_INPUT = AdapterSpec(
    id="kinematic_command_input",
    source=LayerRef.of(ControlLayerId.NONE),
    target=LayerRef.of(SimulationLayerId.KINEMATIC),
    description="heading_speed_cmd goes straight into ConcreteVessel.simulate, which integrates control itself.",
    provides_ports=frozenset({Port.HEADING_SPEED_CMD}),
    requires_ports=frozenset({Port.HEADING_SPEED_CMD}),
)
