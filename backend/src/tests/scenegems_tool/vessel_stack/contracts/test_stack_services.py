"""The port table of a vessel stack (contracts/stack_services.py): every listener of a vessel has a port of its own."""

import pytest

from scenegems_tool.vessel_stack.asv_system.moos_ivp import moos_ivp_server
from scenegems_tool.vessel_stack.asv_system.usv_navigation import usv_navigation_server
from scenegems_tool.vessel_stack.contracts.stack_services import (
    FIXED_PORTS,
    FOREIGN_PORT_RANGES,
    GZ_ACTUATOR_PORT,
    KINEMATIC_SIM_PORT,
    MAX_VESSELS,
    MOOSDB_PORTS_PER_VESSEL,
    PORT_RANGES,
    arduagent_port,
    asv_system_port,
    controller_port,
    gcs_container_port,
    moosdb_port,
)
from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_link import SITL_SERIAL0_BASE_PORT
from scenegems_tool.vessel_stack.control_layers.ardupilot.vessel_service_generator import SITL_SERIAL1_BASE_PORT
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_transport_actuator import DEFAULT_PORT as ACTUATOR_PORT

EPHEMERAL_PORTS_START = 32768  # the operating system hands out ports from here on


def all_ranges():
    return {**PORT_RANGES, **FOREIGN_PORT_RANGES}


def taken(port_range) -> set:
    return {(port_range.protocol, port) for vessel_id in range(MAX_VESSELS) for port in port_range.ports(vessel_id)}


class TestTable:
    def test_a_vessels_ports_are_its_id_above_the_base(self):
        assert (asv_system_port(0), asv_system_port(1), asv_system_port(7)) == (12000, 12001, 12007)
        assert (controller_port(0), gcs_container_port(2), arduagent_port(3)) == (12100, 12202, 12303)
        assert (moosdb_port(0), moosdb_port(2)) == (12400, 12432)

    def test_no_range_overlaps_another_range_or_a_fixed_port_for_any_vessel(self):
        names = list(all_ranges())
        for index, name in enumerate(names):
            assert not taken(all_ranges()[name]) & {("tcp", port) for port in FIXED_PORTS}, name
            for other in names[index + 1 :]:
                assert not taken(all_ranges()[name]) & taken(all_ranges()[other]), f"{name} and {other}"

    def test_the_ports_of_one_vessel_are_all_different(self):
        for vessel_id in (0, 1, MAX_VESSELS - 1):
            ports = [(port_range.protocol, port) for port_range in all_ranges().values() for port in port_range.ports(vessel_id)] + [("tcp", port) for port in FIXED_PORTS]
            assert len(ports) == len(set(ports))

    def test_every_port_is_below_the_operating_systems_ephemeral_ports(self):
        assert max(port_range.end for port_range in all_ranges().values()) <= EPHEMERAL_PORTS_START
        assert max(FIXED_PORTS) < EPHEMERAL_PORTS_START

    def test_a_vessel_id_outside_the_table_has_no_port(self):
        for function in (asv_system_port, controller_port, gcs_container_port, arduagent_port, moosdb_port):
            assert function(MAX_VESSELS - 1)
            with pytest.raises(ValueError, match="vessels a stack has ports for"):
                function(MAX_VESSELS)
            with pytest.raises(ValueError):
                function(-1)

    def test_a_vessel_id_given_as_text_is_a_number(self):
        assert asv_system_port("3") == asv_system_port(3)


class TestTheSoftwaresOwnPorts:
    """The ports SITL and Gazebo take by instance (instance = vessel id) lie in the table's foreign ranges."""

    def test_sitl_serial_ports_are_the_table_s_range(self):
        for vessel_id in range(MAX_VESSELS):
            assert SITL_SERIAL0_BASE_PORT + 10 * vessel_id in FOREIGN_PORT_RANGES["sitl_serial"].ports(vessel_id)
            assert SITL_SERIAL1_BASE_PORT + 10 * vessel_id in FOREIGN_PORT_RANGES["sitl_serial"].ports(vessel_id)
        assert FOREIGN_PORT_RANGES["sitl_serial"].base == SITL_SERIAL0_BASE_PORT

    def test_gazebos_plugin_port_is_in_the_table(self):
        for vessel_id in range(MAX_VESSELS):
            assert 9000 + vessel_id * 10 + 2 in FOREIGN_PORT_RANGES["gazebo_sitl_json"].ports(vessel_id)  # vessel_model_generator's fdm_port_in


class TestFixedPortsAndTheFilesThatCannotImportTheTable:
    def test_the_actuator_port_is_the_gazebo_adapters(self):
        assert GZ_ACTUATOR_PORT == ACTUATOR_PORT
        assert KINEMATIC_SIM_PORT in FIXED_PORTS

    def test_usv_navigation_listens_by_default_where_vessel_0_s_asv_system_does(self):
        assert usv_navigation_server.DEFAULT_PORT == asv_system_port(0)

    def test_moos_ivp_listens_by_default_where_vessel_0_s_asv_system_and_moosdb_do(self):
        assert moos_ivp_server.DEFAULT_PORT == asv_system_port(0)
        assert moos_ivp_server.DEFAULT_MOOSDB_PORT == moosdb_port(0)
        assert moos_ivp_server.MOOSDB_PORTS_PER_VESSEL == MOOSDB_PORTS_PER_VESSEL == PORT_RANGES["moosdb"].span
