"""The replay container of one vessel in a Docker stack, for the replay adapters a lockstep runner steps."""

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.vessel_stack.asv_software.replay.replay_specs import REPLAY_CONTAINER
from scenegems_tool.vessel_stack.contracts.docker_stack import DockerStackArtifacts, DockerStackRequest
from scenegems_tool.vessel_stack.contracts.stack_services import ASV_SOFTWARE_PORT, asv_software_service_name, component_service, stack_agent_name
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselConfig


class ReplayAsvSoftware:
    def add_vessel(self, artifacts: DockerStackArtifacts, request: DockerStackRequest, vessel_config: VesselConfig, vessel: ConcreteVessel, state: ActorState) -> None:
        del request, vessel, state  # the runner sends the trajectory when it starts the software
        artifacts.services[asv_software_service_name(stack_agent_name(vessel_config))] = component_service(REPLAY_CONTAINER, ASV_SOFTWARE_PORT)
