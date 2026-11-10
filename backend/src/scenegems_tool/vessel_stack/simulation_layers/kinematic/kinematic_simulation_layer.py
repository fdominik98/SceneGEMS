"""Kinematic simulation layer in a Docker stack: one simulator container per scenario.

The world needs no generated files: the runner sends the initial scene when it starts the
simulator (kinematic_sim_link.py), so the service has no volume.
"""

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.vessel_stack.contracts.docker_stack import DockerStackArtifacts, DockerStackRequest
from scenegems_tool.vessel_stack.contracts.stack_services import KINEMATIC_SIM_PORT, KINEMATIC_SIM_SERVICE, component_service
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselConfig
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_specs import KINEMATIC_LAYER, KINEMATIC_SIM_CONTAINER


class KinematicSimulationLayer:
    spec = KINEMATIC_LAYER

    def add_vessel(self, artifacts: DockerStackArtifacts, request: DockerStackRequest, vessel_config: VesselConfig, vessel: ConcreteVessel, state: ActorState) -> None:
        del artifacts, request, vessel_config, vessel, state  # the vessels live in the one simulator service

    def finish(self, artifacts: DockerStackArtifacts, request: DockerStackRequest) -> None:
        del request
        artifacts.services[KINEMATIC_SIM_SERVICE] = component_service(KINEMATIC_SIM_CONTAINER, KINEMATIC_SIM_PORT)
