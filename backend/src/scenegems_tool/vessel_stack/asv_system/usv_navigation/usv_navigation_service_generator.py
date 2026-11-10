"""The USV Navigation container of one vessel in a Docker stack: the software's own image, for every adapter out of it."""

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_specs import USV_NAVIGATION_CONTAINER
from scenegems_tool.vessel_stack.contracts.docker_stack import DockerStackArtifacts, DockerStackRequest
from scenegems_tool.vessel_stack.contracts.stack_services import ASV_SYSTEM_PORT, asv_system_service_name, component_service, stack_agent_name
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselConfig


class UsvNavigationAsvSystem:
    def add_vessel(self, artifacts: DockerStackArtifacts, request: DockerStackRequest, vessel_config: VesselConfig, vessel: ConcreteVessel, state: ActorState) -> None:
        del request, vessel, state  # the runner sends the parameters when it starts the software
        artifacts.services[asv_system_service_name(stack_agent_name(vessel_config))] = component_service(USV_NAVIGATION_CONTAINER, ASV_SYSTEM_PORT)
