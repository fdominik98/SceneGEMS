"""The MOOS-IvP container of one vessel in a Docker stack: the software's own image, for every adapter out of it."""

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.vessel_stack.asv_system.moos_ivp.moos_ivp_specs import MOOS_IVP_CONTAINER
from scenegems_tool.vessel_stack.contracts.docker_stack import DockerStackArtifacts, DockerStackRequest
from scenegems_tool.vessel_stack.contracts.stack_services import asv_system_port, asv_system_service_name, component_service, moosdb_port, stack_agent_name
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselConfig


class MoosIvpAsvSystem:
    def add_vessel(self, artifacts: DockerStackArtifacts, request: DockerStackRequest, vessel_config: VesselConfig, vessel: ConcreteVessel, state: ActorState) -> None:
        del request, state  # the runner sends the parameters when it starts the software
        service = component_service(MOOS_IVP_CONTAINER, asv_system_port(vessel.id))
        service["command"] += ["--moosdb-port", str(moosdb_port(vessel.id))]  # the vessel's MOOSDB, beside the other vessels' in one network namespace
        artifacts.services[asv_system_service_name(stack_agent_name(vessel_config))] = service
