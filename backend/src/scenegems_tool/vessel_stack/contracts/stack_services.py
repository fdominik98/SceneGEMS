"""Names, ports and compose services of the components of a vessel stack that speak the lockstep wire protocol.

One place decides how the runner finds a component on the stack's network, so the generator of a
component's service and the runner's link to it cannot disagree.
"""

from typing import List

from scenegems_tool.vessel_stack.contracts.adapter_spec import ContainerSpec, image_reference
from scenegems_tool.vessel_stack.contracts.lockstep_wire import Endpoint
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselConfig

STACK_NETWORK = "maritime_net"  # the network every service of a vessel stack is on
ASV_SYSTEM_PORT = 11410
CONTROLLER_PORT = 11420
KINEMATIC_SIM_PORT = 11430
KINEMATIC_SIM_SERVICE = "kinematic_sim"
_ASV_SYSTEM_SUFFIX = "_asv_system"  # after the agent's name, as its _mavproxy and _arduagent services are named
_CONTROLLER_SUFFIX = "_controller"


def backend_component_container(server_module: str) -> ContainerSpec:
    """The container of a component that is part of the SceneGEMS backend: the scenario execution image, started at the component's server module."""
    return ContainerSpec(
        image=image_reference("SCENARIO_EXECUTION_IMAGE", "scenegems-scenario-execution-subsystem"),
        build_fingerprint_source="deploy/images/scenario_execution",
        entrypoint=f"python -m {server_module}",
        extra_fingerprint_sources=("backend/src",),
    )


def stack_agent_name(vessel_config: VesselConfig) -> str:
    """The name a vessel's services carry: its agent's name, or vessel_<id> for a vessel without an agent connection."""
    return vessel_config.connection.agent_name if vessel_config.connection is not None else f"vessel_{vessel_config.agent_id}"


def asv_system_service_name(agent_name: str) -> str:
    return f"{agent_name}{_ASV_SYSTEM_SUFFIX}"


def controller_service_name(agent_name: str) -> str:
    return f"{agent_name}{_CONTROLLER_SUFFIX}"


def asv_system_endpoint(agent_name: str) -> Endpoint:
    return Endpoint(asv_system_service_name(agent_name), ASV_SYSTEM_PORT)


def controller_endpoint(agent_name: str) -> Endpoint:
    return Endpoint(controller_service_name(agent_name), CONTROLLER_PORT)


def kinematic_sim_endpoint() -> Endpoint:
    return Endpoint(KINEMATIC_SIM_SERVICE, KINEMATIC_SIM_PORT)


def is_participant_service(service_name: str) -> bool:
    """Whether a service of a stack is a vessel's ASV system or controller component (a caller that hosts them itself leaves them out)."""
    return service_name.endswith((_ASV_SYSTEM_SUFFIX, _CONTROLLER_SUFFIX))


def component_command(container: ContainerSpec, port: int) -> List[str]:
    """The command of a component's service: the container's entry point, listening on the port."""
    return [*container.entrypoint.split(), "--port", str(port)]


def component_service(container: ContainerSpec, port: int) -> dict:
    """The compose service of one component: its image and entry point on the stack's network, with no host port and no volume."""
    return {
        "image": container.image,
        "command": component_command(container, port),
        "environment": {"PYTHONUNBUFFERED": "1"},
        "networks": [STACK_NETWORK],
    }
