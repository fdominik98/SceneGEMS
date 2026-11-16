"""No two listeners of a vessel stack share a port.

The containers of one run may share a network namespace (one pod), so every listener of a stack needs a port
of its own, whichever vessel it serves. The test generates every available stack of the matrix with several
vessels (every adapter alternative of the ASV system's connection included), collects the ports each service
listens on, the ports SITL and Gazebo take by themselves per instance included, and asserts that none is used
twice and that each lies in the port table of contracts/stack_services.py.
"""

import re
from typing import Dict, List, Tuple

import pytest

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.vessel_stack.calibration.reference_scenarios import make_vessel
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId, LayerRef, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.stack_services import FIXED_PORTS, FOREIGN_PORT_RANGES, MAX_VESSELS, PORT_RANGES
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import AgentConnection, EnvironmentConfig, SimulationInstanceConfig, VesselConfig, VesselStackConfig
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from scenegems_tool.vessel_stack.simulation_docker_stack import build_simulation_docker_stack_artifacts
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, mqtt_connection

VESSEL_IDS = (0, 1, 2, 3, 7)  # the own ship, targets, and ids that are not next to each other
SITL_TCP_PORTS_PER_INSTANCE = 10  # SITL's serial ports take base + 0 to base + 9 of its instance (--instance adds 10 to every port)
# What ArduPilot SITL takes per instance, read from the SITL_cmdline.cpp of the pinned image: the base port of its serial ports,
# the RC input and flight view ports, and with the JSON backend the port it listens on, the plugin's port and the IRLock port.
SITL_BASE_PORT, SITL_RCIN_PORT, SITL_FG_VIEW_PORT = 5760, 5501, 5503
SITL_JSON_IN_PORT, SITL_JSON_OUT_PORT, SITL_IRLOCK_PORT = 9003, 9002, 9005


def trajectories_of(vessel_ids) -> Trajectories:
    """Vessels on a line heading east, vessel 0 the own ship."""
    states = {make_vessel(vessel_id, vessel_id == 0): ActorState(0.0, 500.0 * vessel_id, 5.0, 0.0) for vessel_id in vessel_ids}
    return TrajectoryBuilder.default_trajectory_from_scene(ConcreteScene(states), 1, 60)


def instance_of(stack: VesselStackConfig, vessel_ids, adapter_ids=()) -> SimulationInstanceConfig:
    return SimulationInstanceConfig(
        simulation_layer=stack.simulation_layer,
        environment=EnvironmentConfig.calm(),
        vessels={
            str(vessel_id): VesselConfig(
                agent_id=str(vessel_id),
                stack=stack,
                connection=AgentConnection(agent_name=f"agent_{vessel_id}", topic=f"waraps/unit/surface/agent_{vessel_id}"),
                adapter_ids=tuple(adapter_ids),
            )
            for vessel_id in vessel_ids
        },
    )


def stack_cases() -> List[Tuple[str, VesselStackConfig, Tuple[str, ...]]]:
    """Every available triple of the matrix, once per adapter of the ASV system's connection, as (id, stack, adapter ids)."""
    resolver = default_resolver()
    cases = []
    for chain in resolver.availability_matrix():
        stack = chain.stack
        if not chain.available or SimulationLayerId.REAL_VESSEL in (stack.simulation_layer,) or ControlLayerId.REAL_VESSEL == stack.control_layer:
            continue  # a real vessel is no container of the stack
        asv_ref, control_ref = LayerRef.of(stack.asv_system), LayerRef.of(stack.control_layer)
        alternatives = [spec.id for spec in resolver.registry.adapters_between(asv_ref, control_ref)] or [""]
        for adapter_id in alternatives:
            cases.append((f"{stack}" + (f" via {adapter_id}" if adapter_id else ""), stack, (adapter_id,) if adapter_id else ()))
    return cases


CASES = stack_cases()


Listener = Tuple[str, str, int]  # the service (or file) that makes it listen, the protocol, the port


def ports_of_command(command) -> List[int]:
    """The TCP ports a service's command makes it listen on: --port and --moosdb-port of a component, and every tcpin endpoint of MAVProxy."""
    text = command if isinstance(command, str) else " ".join(command)
    ports = [int(value) for value in re.findall(r"--(?:port|moosdb-port)[ =](\d+)", text)]
    ports += [int(value) for value in re.findall(r"tcpin:[^:\s;]+:(\d+)", text)]
    return ports


def sitl_ports(name: str, environment: Dict[str, str]) -> List[Listener]:
    instance = int(environment["SITL_INSTANCE"])
    first = SITL_BASE_PORT + 10 * instance
    listeners = [(name, "tcp", port) for port in range(first, first + SITL_TCP_PORTS_PER_INSTANCE)]
    listeners += [(name, "udp", SITL_RCIN_PORT + 10 * instance), (name, "udp", SITL_FG_VIEW_PORT + 10 * instance)]
    if environment.get("SITL_SIMULATOR") == "gazebo":
        listeners += [(name, "udp", SITL_JSON_IN_PORT + 10 * instance), (name, "udp", SITL_IRLOCK_PORT + 10 * instance)]
    return listeners


def listeners_of(compose: dict, writes) -> List[Listener]:
    """Every port a service of the generated stack listens on, and the ArduPilot plugin's ports of Gazebo's vessel models."""
    listeners: List[Listener] = []
    for name, service in compose["services"].items():
        environment = service.get("environment", [])
        environment = dict(item.split("=", 1) for item in environment if "=" in item) if isinstance(environment, list) else dict(environment)
        listeners += [(name, "tcp", port) for port in ports_of_command(service.get("command", []))]
        if "SITL_INSTANCE" in environment:
            listeners += sitl_ports(name, environment)
        if "GZ_ACTUATOR_PORT" in environment:
            listeners.append((name, "tcp", int(environment["GZ_ACTUATOR_PORT"])))
    for path, content in writes:
        listeners += [(path, "udp", int(port)) for port in re.findall(r"<fdm_port_in>(\d+)</fdm_port_in>", content)]
    return listeners


def in_the_table(protocol: str, port: int) -> bool:
    if protocol == "tcp" and port in FIXED_PORTS:
        return True
    return any(
        port_range.protocol == protocol and any(port in port_range.ports(vessel_id) for vessel_id in range(MAX_VESSELS)) for port_range in [*PORT_RANGES.values(), *FOREIGN_PORT_RANGES.values()]
    )


def generated(stack: VesselStackConfig, vessel_ids, adapter_ids=()) -> List[Listener]:
    writes, compose = build_simulation_docker_stack_artifacts(instance_of(stack, vessel_ids, adapter_ids), trajectories_of(vessel_ids), mqtt_connection(), GEOFENCE)
    return listeners_of(compose, writes)


@pytest.mark.parametrize("name, stack, adapter_ids", CASES, ids=[case[0] for case in CASES])
def test_no_two_listeners_of_a_stack_share_a_port(name, stack, adapter_ids):
    listeners = generated(stack, VESSEL_IDS, adapter_ids)
    owners: Dict[Tuple[str, int], str] = {}
    for owner, protocol, port in listeners:
        assert (protocol, port) not in owners, f"{name}: {protocol} port {port} is used by {owners.get((protocol, port))} and by {owner}"
        owners[(protocol, port)] = owner
    outside = sorted((protocol, port) for _, protocol, port in listeners if not in_the_table(protocol, port))
    assert not outside, f"{name}: ports outside the table: {outside}"


def test_the_matrix_has_stacks_with_every_kind_of_listener():
    """The invariant is checked on the services that matter: component servers, MOOSDB, MAVProxy's endpoints, SITL and Gazebo."""
    seen = set()
    for _, stack, adapter_ids in CASES:
        for _, protocol, port in generated(stack, (0, 1), adapter_ids):
            seen.update(kind for kind, port_range in {**PORT_RANGES, **FOREIGN_PORT_RANGES}.items() if port_range.protocol == protocol and any(port in port_range.ports(v) for v in (0, 1)))
            if protocol == "tcp" and port in FIXED_PORTS:
                seen.add("fixed")
    assert seen == {*PORT_RANGES, *FOREIGN_PORT_RANGES, "fixed"}


def test_a_stack_of_the_highest_and_the_lowest_vessel_id_has_no_shared_port():
    """The ranges are sized for MAX_VESSELS: the last id next to the first."""
    for name, stack, adapter_ids in CASES:
        ports = [(protocol, port) for _, protocol, port in generated(stack, (0, MAX_VESSELS - 1), adapter_ids)]
        assert len(ports) == len(set(ports)), name


def test_a_stack_has_ports_for_max_vessels_and_no_more():
    stack = next(stack for _, stack, _ in CASES if stack.simulation_layer == SimulationLayerId.KINEMATIC)
    with pytest.raises(ValueError, match="vessels a stack has ports for"):
        generated(stack, (0, MAX_VESSELS))


def test_the_listeners_this_test_derives_are_what_the_generators_wrote():
    """A guard on the test: it finds the ports of SITL and of the ArduPilot plugin in a generated stack."""
    stack = next(stack for _, stack, _ in CASES if stack.simulation_layer == SimulationLayerId.GAZEBO and stack.control_layer == ControlLayerId.ARDUPILOT)
    ports: Dict[str, set] = {}
    for owner, protocol, port in generated(stack, (0, 1)):
        ports.setdefault(owner, set()).add((protocol, port))
    assert {"agent_0", "agent_1"} <= set(ports)
    assert ports["agent_1"] == {*(("tcp", port) for port in range(5770, 5780)), ("udp", 5511), ("udp", 5513), ("udp", 9013), ("udp", 9015)}, "SITL's instance 1"
    assert any(owner.endswith(".sdf") and ports[owner] == {("udp", 9012)} for owner in ports), "the plugin's port is read from the vessel's model"
