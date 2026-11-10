"""Custom control layer in a Docker stack: one controller container per vessel.

The container runs the vessel's autopilot (custom_controller_server.py); the runner carries its
thrusts to the hull (simulation_layers/gazebo/gz_lockstep_runner.py). The Gazebo layer gives the
vessel's model the variant without ArduPilotPlugin and starts the gz-transport actuator.
"""

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.vessel_stack.contracts.docker_stack import DockerStackArtifacts, DockerStackRequest
from scenegems_tool.vessel_stack.contracts.roles import SimulationLayerId
from scenegems_tool.vessel_stack.contracts.stack_services import CONTROLLER_PORT, component_service, controller_service_name, stack_agent_name
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselConfig
from scenegems_tool.vessel_stack.control_layers.custom.custom_controller_specs import CUSTOM_CONTROL_LAYER, CUSTOM_CONTROLLER_CONTAINER


class CustomControlLayer:
    spec = CUSTOM_CONTROL_LAYER

    def add_vessel(self, artifacts: DockerStackArtifacts, request: DockerStackRequest, vessel_config: VesselConfig, vessel: ConcreteVessel, state: ActorState) -> None:
        del request, vessel, state  # the runner sends the vessel and its gains when it starts the controller
        if vessel_config.stack.simulation_layer != SimulationLayerId.GAZEBO:
            raise ValueError(f"The custom control layer drives Gazebo only, not {vessel_config.stack.simulation_layer.value}")
        artifacts.services[controller_service_name(stack_agent_name(vessel_config))] = component_service(CUSTOM_CONTROLLER_CONTAINER, CONTROLLER_PORT)
