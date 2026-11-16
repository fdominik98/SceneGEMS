"""Every name a stack's services dial each other by is a valid RFC 1123 name.

The containers of one run may become the containers of one pod, where the names they dial are hostAliases, and
Kubernetes accepts only lowercase letters, digits and hyphens there (starting and ending with a letter or digit).
The test generates every available stack of the matrix (the stacks and adapters of test_stack_ports.py) with
vessels named as a run names them (os, ts1, ...) and checks the key of every service, what a service depends on
and every host a command or an environment variable of a service dials.
"""

import re
from typing import Dict, List, Set

import pytest

from scenegems_tool.vessel_stack.contracts.stack_services import (
    KINEMATIC_SIM_SERVICE,
    MAX_VESSELS,
    asv_system_endpoint,
    controller_endpoint,
    is_participant_service,
    kinematic_sim_endpoint,
    vessel_stack_name,
)
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import AgentConnection, EnvironmentConfig, SimulationInstanceConfig, VesselConfig, VesselStackConfig
from scenegems_tool.vessel_stack.control_layers.ardupilot.vessel_service_generator import gcs_mavproxy_service_name
from scenegems_tool.vessel_stack.simulation_docker_stack import build_simulation_docker_stack_artifacts
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, mqtt_connection
from tests.scenegems_tool.vessel_stack.test_stack_ports import CASES, VESSEL_IDS, trajectories_of

RFC_1123_LABEL = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
MAX_NAME_LENGTH = 63
# A host in an endpoint of a command or a variable: tcp:HOST:PORT, tcpin:HOST:PORT, udp:HOST:PORT, host:port after --master or --out
ENDPOINT_HOST = re.compile(r"\b(?:tcp|tcpin|udp|udpin|udpout):([^:\s;'\"]+):\d+")
HOST_VARIABLE = re.compile(r"(?:^|_)HOST$")
EXTERNAL_HOSTS = {"host.docker.internal"}  # not a service of the stack: Docker's name for the host machine, in extra_hosts
IP_ADDRESS = re.compile(r"^\d+\.\d+\.\d+\.\d+$")  # a bind address such as MAVProxy's tcpin:0.0.0.0:port is no name


def is_valid_name(name: str) -> bool:
    return len(name) <= MAX_NAME_LENGTH and RFC_1123_LABEL.match(name) is not None


def instance_named_as_a_run_names_it(stack: VesselStackConfig, vessel_ids, adapter_ids=()) -> SimulationInstanceConfig:
    """The vessels carry the names of a run (os, ts1, ts2, ...), as the runners give them."""
    return SimulationInstanceConfig(
        simulation_layer=stack.simulation_layer,
        environment=EnvironmentConfig.calm(),
        vessels={
            str(vessel_id): VesselConfig(
                agent_id=str(vessel_id),
                stack=stack,
                connection=AgentConnection(agent_name=vessel_stack_name(vessel_id), topic=f"waraps/unit/surface/{vessel_stack_name(vessel_id)}"),
                adapter_ids=tuple(adapter_ids),
            )
            for vessel_id in vessel_ids
        },
    )


def environment_of(service: dict) -> Dict[str, str]:
    environment = service.get("environment", [])
    if isinstance(environment, list):
        return dict(item.split("=", 1) for item in environment if "=" in item)
    return {key: str(value) for key, value in environment.items()}


def command_text(service: dict) -> str:
    command = service.get("command", "")
    return command if isinstance(command, str) else " ".join(command)


def network_aliases(service: dict) -> List[str]:
    networks = service.get("networks", {})
    if not isinstance(networks, dict):
        return []
    return [alias for settings in networks.values() for alias in (settings or {}).get("aliases", [])]


def names_in(compose: dict) -> Dict[str, Set[str]]:
    """Every name a generated stack gives a service or dials, by the kind of place it is in."""
    names: Dict[str, Set[str]] = {"service key": set(), "depends_on": set(), "network alias": set(), "endpoint host": set(), "host variable": set()}
    for key, service in compose["services"].items():
        names["service key"].add(key)
        depends_on = service.get("depends_on", [])
        names["depends_on"].update(depends_on if isinstance(depends_on, list) else depends_on.keys())
        names["network alias"].update(network_aliases(service))
        environment = environment_of(service)
        for text in (command_text(service), *environment.values()):
            names["endpoint host"].update(host for host in ENDPOINT_HOST.findall(text) if not IP_ADDRESS.match(host))
        names["host variable"].update(value for variable, value in environment.items() if HOST_VARIABLE.search(variable) and value)
    return names


def generated_compose(stack: VesselStackConfig, vessel_ids, adapter_ids=()) -> dict:
    _, compose = build_simulation_docker_stack_artifacts(instance_named_as_a_run_names_it(stack, vessel_ids, adapter_ids), trajectories_of(vessel_ids), mqtt_connection(), GEOFENCE)
    return compose


@pytest.mark.parametrize("name, stack, adapter_ids", CASES, ids=[case[0] for case in CASES])
def test_every_service_key_and_every_host_a_service_dials_is_an_rfc_1123_name(name, stack, adapter_ids):
    names = names_in(generated_compose(stack, VESSEL_IDS, adapter_ids))
    invalid = {kind: sorted(value for value in values if not is_valid_name(value)) for kind, values in names.items() if any(not is_valid_name(value) for value in values)}
    assert not invalid, f"{name}: names Kubernetes refuses as host names: {invalid}"


def test_a_service_dialed_in_a_command_is_a_service_of_the_stack():
    """A guard on the test: the hosts it finds are the stack's services, so it reads the commands and variables that matter."""
    found: Set[str] = set()
    for _, stack, adapter_ids in CASES:
        compose = generated_compose(stack, (0, 1), adapter_ids)
        names = names_in(compose)
        assert (names["endpoint host"] | names["host variable"] | names["depends_on"]) - EXTERNAL_HOSTS <= names["service key"]
        found.update(names["endpoint host"] | names["host variable"] | names["depends_on"])
    assert {"os", "ts1", "os-mavproxy", "ts1-mavproxy", "gazebo"} <= found, "SITL, MAVProxy's endpoints, ArduAgent's dependency and Gazebo's host are all dialed by name"


def test_the_stacks_of_the_matrix_have_every_kind_of_named_service():
    keys: Set[str] = set()
    for _, stack, adapter_ids in CASES:
        keys.update(names_in(generated_compose(stack, (0, 1), adapter_ids))["service key"])
    assert {KINEMATIC_SIM_SERVICE, "os-asv-system", "ts1-asv-system", "os-controller", "ts1-controller", "os-mavproxy", "os-arduagent", "ts1-arduagent", "os", "ts1", "gazebo"} <= keys


@pytest.mark.parametrize("vessel_id", [0, 1, 2, 10, MAX_VESSELS - 1])
def test_the_endpoints_the_runner_dials_are_rfc_1123_names(vessel_id):
    agent_name = vessel_stack_name(vessel_id)
    hosts = [
        asv_system_endpoint(agent_name, vessel_id).host,
        controller_endpoint(agent_name, vessel_id).host,
        kinematic_sim_endpoint().host,
        gcs_mavproxy_service_name(agent_name),
    ]
    assert all(is_valid_name(host) for host in hosts), hosts


def test_the_participant_services_are_still_recognised_by_their_suffix():
    assert is_participant_service(asv_system_endpoint("ts1", 1).host)
    assert is_participant_service(controller_endpoint("os", 0).host)
    assert not is_participant_service(KINEMATIC_SIM_SERVICE)
    assert not is_participant_service(gcs_mavproxy_service_name("os"))
    assert not is_participant_service("os")
