"""The component servers of a vessel stack on the loopback interface: every layer of an instance behind the wire protocol, without Docker.

loopback_hosting starts the server each container of the instance's stack would run (the kinematic
simulator, and per vessel its ASV system and, on the custom controller, its controller) and
gives a ContainerHosting whose endpoints point at them, so a lockstep runner steps real sockets.
"""

from contextlib import ExitStack, contextmanager
from typing import Dict, Iterator

from scenegems_tool.vessel_stack.asv_system.replay.replay_server import IMPLEMENTATION as REPLAY
from scenegems_tool.vessel_stack.asv_system.replay.replay_server import ReplaySession
from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_server import IMPLEMENTATION as USV_NAVIGATION
from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_server import UsvNavigationSession
from scenegems_tool.vessel_stack.contracts.lockstep_wire import ROLE_ASV_SYSTEM, ROLE_CONTROLLER, ROLE_SIMULATOR, Endpoint, LineServer
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.stack_services import KINEMATIC_SIM_SERVICE, asv_system_service_name, controller_service_name, stack_agent_name
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig
from scenegems_tool.vessel_stack.control_layers.custom.custom_controller_server import IMPLEMENTATION as CUSTOM
from scenegems_tool.vessel_stack.control_layers.custom.custom_controller_server import CustomControllerSession
from scenegems_tool.vessel_stack.hosting import ContainerHosting
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_sim_server import IMPLEMENTATION as KINEMATIC
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_sim_server import KinematicSimSession

LOOPBACK = "127.0.0.1"
ASV_SYSTEM_SESSIONS = {AsvSystemId.REPLAY: (REPLAY, ReplaySession), AsvSystemId.USV_NAVIGATION: (USV_NAVIGATION, UsvNavigationSession)}


def serve(servers: ExitStack, role: str, implementation: str, session_factory) -> Endpoint:
    server = servers.enter_context(LineServer(role, implementation, session_factory, host=LOOPBACK))
    return Endpoint(LOOPBACK, server.port)


@contextmanager
def loopback_endpoints(instance: SimulationInstanceConfig) -> Iterator[Dict[str, Endpoint]]:
    """The servers of the instance's stack, by the name of the service each would be."""
    with ExitStack() as servers:
        endpoints: Dict[str, Endpoint] = {}
        if instance.simulation_layer == SimulationLayerId.KINEMATIC:
            endpoints[KINEMATIC_SIM_SERVICE] = serve(servers, ROLE_SIMULATOR, KINEMATIC, KinematicSimSession)
        for vessel in instance.simulated_vessels.values():
            agent_name = stack_agent_name(vessel)
            implementation, session = ASV_SYSTEM_SESSIONS[vessel.stack.asv_system]
            endpoints[asv_system_service_name(agent_name)] = serve(servers, ROLE_ASV_SYSTEM, implementation, session)
            if vessel.stack.control_layer == ControlLayerId.CUSTOM:
                endpoints[controller_service_name(agent_name)] = serve(servers, ROLE_CONTROLLER, CUSTOM, CustomControllerSession)
        yield endpoints


@contextmanager
def loopback_hosting(instance: SimulationInstanceConfig) -> Iterator[ContainerHosting]:
    with loopback_endpoints(instance) as endpoints:
        yield ContainerHosting(endpoints, connect_timeout_s=10.0)
