"""Names, ports and compose services of the components of a vessel stack that speak the lockstep wire protocol.

One place decides how the runner finds a component on the stack's network, so the generator of a
component's service and the runner's link to it cannot disagree.

Ports. The containers of one run may share a network namespace (one pod), so no two listeners of a
stack may use the same port number of one protocol, whichever vessel they serve. PORT_RANGES is the one table: a
range of every listener that is per vessel, with the vessel's id as the offset, and FOREIGN_PORT_RANGES
the ranges the software of the stack takes by itself (ArduPilot SITL and the ArduPilot plugin of Gazebo,
by instance = vessel id), which the table keeps clear of. The fixed ports are the kinematic simulator's
and the gz-transport actuator's (gz_transport_actuator.DEFAULT_PORT, which that file cannot import). The
numbers are all below 32768, the start of the operating system's ephemeral ports.
"""

from typing import List, NamedTuple, Union

from functional_level.models.object_generator import OS_ID, vessel_name
from scenegems_tool.vessel_stack.contracts.adapter_spec import ContainerSpec, image_reference
from scenegems_tool.vessel_stack.contracts.lockstep_wire import Endpoint
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselConfig

STACK_NETWORK = "maritime_net"  # the network every service of a vessel stack is on
KINEMATIC_SIM_PORT = 11430
GZ_ACTUATOR_PORT = 11400  # gz_transport_actuator.DEFAULT_PORT; a test keeps the two equal
MAX_VESSELS = 100  # vessel ids 0 to MAX_VESSELS - 1 have ports


class PortRange(NamedTuple):
    """Ports of one kind of listener: vessel v takes base + step * v up to base + step * v + span - 1, of one protocol."""

    base: int
    step: int = 1
    span: int = 1
    protocol: str = "tcp"

    def port(self, vessel_id: int) -> int:
        if not 0 <= int(vessel_id) < MAX_VESSELS:
            raise ValueError(f"vessel id {vessel_id} is outside the {MAX_VESSELS} vessels a stack has ports for")
        return self.base + self.step * int(vessel_id)

    def ports(self, vessel_id: int) -> range:
        first = self.port(vessel_id)
        return range(first, first + self.span)

    @property
    def end(self) -> int:
        """One past the last port of the last vessel."""
        return self.port(MAX_VESSELS - 1) + self.span


MOOSDB_PORTS_PER_VESSEL = 16  # a MOOSDB server process takes a new port per run from its window, so a run never meets the socket of the one before

# The ports SceneGEMS gives the listeners of a vessel stack, by vessel id.
PORT_RANGES = {
    "asv_system": PortRange(12000),  # the lockstep server of the vessel's ASV system
    "controller": PortRange(12100),  # the lockstep server of the vessel's custom controller
    "ground_control": PortRange(12200),  # MAVProxy's TCP endpoint for a ground control station
    "arduagent": PortRange(12300),  # MAVProxy's TCP endpoint for the vessel's ArduAgent
    "moosdb": PortRange(12400, MOOSDB_PORTS_PER_VESSEL, MOOSDB_PORTS_PER_VESSEL),  # the MOOSDB of MOOS-IvP, beside its ASV system server
}
# What the software of the stack takes per instance (instance = vessel id, ports 10 * instance higher): checked by tests against the generators.
FOREIGN_PORT_RANGES = {
    "sitl_rc_and_view": PortRange(5500, 10, 10, "udp"),  # SITL's RC input (5501) and flight view (5503); from instance 26 on they have the serial ports' numbers, which is no clash for UDP
    "sitl_serial": PortRange(5760, 10, 10),  # SITL's serial ports: SERIAL0 (5760, the lockstep runner) and SERIAL1 (5762, MAVLink)
    "gazebo_sitl_json": PortRange(9000, 10, 10, "udp"),  # the ArduPilot plugin of Gazebo (9002) and SITL's JSON backend (9003, IRLock 9005)
}
FIXED_PORTS = (KINEMATIC_SIM_PORT, GZ_ACTUATOR_PORT)  # TCP
# The names of services are host names on the stack's network (and in a pod, hostAliases), so they are RFC 1123 names: lowercase letters, digits and hyphens.
KINEMATIC_SIM_SERVICE = "kinematic-sim"
_ASV_SYSTEM_SUFFIX = "-asv-system"  # after the agent's name, as its -mavproxy and -arduagent services are named
_CONTROLLER_SUFFIX = "-controller"


def backend_component_container(server_module: str) -> ContainerSpec:
    """The container of a component that is part of the SceneGEMS backend: the simulation subsystem image, started at the component's server module."""
    return ContainerSpec(
        image=image_reference("SIMULATION_IMAGE", "scenegems-simulation-subsystem"),
        build_fingerprint_source="deploy/images/simulation",
        entrypoint=f"python -m {server_module}",
        extra_fingerprint_sources=("backend/src",),
    )


def vessel_stack_name(agent_id: Union[int, str]) -> str:
    """A vessel's name in a stack, as every screen names it: os for the own ship and ts<n> for a target; an id that is no number names itself."""
    try:
        actor_id = int(agent_id)
    except ValueError:
        return str(agent_id)
    return vessel_name(actor_id, actor_id == OS_ID)


def stack_agent_name(vessel_config: VesselConfig) -> str:
    """The name a vessel's services carry: its agent's name, or the vessel's own (os, ts1) without an agent connection."""
    return vessel_config.connection.agent_name if vessel_config.connection is not None else vessel_stack_name(vessel_config.agent_id)


def asv_system_service_name(agent_name: str) -> str:
    return f"{agent_name}{_ASV_SYSTEM_SUFFIX}"


def controller_service_name(agent_name: str) -> str:
    return f"{agent_name}{_CONTROLLER_SUFFIX}"


def asv_system_port(vessel_id: int) -> int:
    return PORT_RANGES["asv_system"].port(vessel_id)


def controller_port(vessel_id: int) -> int:
    return PORT_RANGES["controller"].port(vessel_id)


def gcs_container_port(vessel_id: int) -> int:
    """The port of a vessel's MAVProxy for a ground control station, inside its container."""
    return PORT_RANGES["ground_control"].port(vessel_id)


def arduagent_port(vessel_id: int) -> int:
    """The port of a vessel's MAVProxy for its ArduAgent."""
    return PORT_RANGES["arduagent"].port(vessel_id)


def moosdb_port(vessel_id: int) -> int:
    """The first MOOSDB port of a vessel's MOOS-IvP server; a run takes the next of MOOSDB_PORTS_PER_VESSEL."""
    return PORT_RANGES["moosdb"].port(vessel_id)


def asv_system_endpoint(agent_name: str, vessel_id: int) -> Endpoint:
    return Endpoint(asv_system_service_name(agent_name), asv_system_port(vessel_id))


def controller_endpoint(agent_name: str, vessel_id: int) -> Endpoint:
    return Endpoint(controller_service_name(agent_name), controller_port(vessel_id))


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
