"""Roles, layer references, specs and the typed stack configuration."""

import numpy as np
import pytest

from scenegems_tool.vessel_stack.contracts.adapter_spec import UPSTREAM_PINS_FILE, AdapterSpec, ContainerSpec, LayerSpec, SpecStatus
from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities, EnvironmentSupport
from scenegems_tool.vessel_stack.contracts.ports import HeadingSpeedCommand, Port
from scenegems_tool.vessel_stack.contracts.roles import STACK_ROLE_ORDER, AsvSoftwareId, ControlLayerId, LayerRef, Role, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import (
    AgentConnection,
    AgentContext,
    EnvironmentConfig,
    SimulationInstanceConfig,
    VesselConfig,
    VesselStackConfig,
    WaveConfig,
)


class TestRoles:
    def test_layer_ref_knows_its_role_from_the_implementation_type(self):
        assert LayerRef.of(AsvSoftwareId.REPLAY) == LayerRef(Role.ASV_SOFTWARE, "replay")
        assert LayerRef.of(ControlLayerId.NONE) == LayerRef(Role.CONTROL_LAYER, "none")
        assert LayerRef.of(SimulationLayerId.GAZEBO) == LayerRef(Role.SIMULATION_LAYER, "gazebo")

    def test_layer_ref_prints_as_role_slash_implementation(self):
        assert str(LayerRef.of(SimulationLayerId.ARDUPILOT_SIM)) == "simulation_layer/ardupilot_sim"

    def test_same_implementation_name_in_two_roles_is_two_refs(self):
        assert LayerRef(Role.CONTROL_LAYER, "none") != LayerRef(Role.ASV_SOFTWARE, "none")

    def test_stack_order_is_asv_control_simulation(self):
        assert STACK_ROLE_ORDER == (Role.ASV_SOFTWARE, Role.CONTROL_LAYER, Role.SIMULATION_LAYER)

    def test_supported_implementations(self):
        assert {item.value for item in AsvSoftwareId} == {"replay", "usv_navigation", "mission_planner", "on_board"}
        assert {item.value for item in ControlLayerId} == {"ardupilot", "custom", "none", "real_vessel"}
        assert {item.value for item in SimulationLayerId} == {"kinematic", "gazebo", "ardupilot_sim", "real_vessel"}

    def test_ids_are_strings(self):
        assert AsvSoftwareId("replay") is AsvSoftwareId.REPLAY
        assert SimulationLayerId.GAZEBO == "gazebo"


class TestSpecs:
    def test_layer_spec_id_is_the_layer_ref(self):
        assert LayerSpec(layer=LayerRef.of(AsvSoftwareId.REPLAY), description="x").id == "asv_software/replay"

    def test_adapter_spec_exposes_both_ends(self):
        spec = AdapterSpec(id="a", source=LayerRef.of(AsvSoftwareId.REPLAY), target=LayerRef.of(ControlLayerId.NONE), description="x")
        assert (spec.from_role, spec.from_impl, spec.to_role, spec.to_impl) == (Role.ASV_SOFTWARE, "replay", Role.CONTROL_LAYER, "none")

    def test_note_for_a_capability(self):
        spec = LayerSpec(layer=LayerRef.of(SimulationLayerId.GAZEBO), description="x", restriction_notes=(("waves", "no waves"),))
        assert spec.note_for("waves") == "no waves"
        assert spec.note_for("wind") is None

    def test_with_capabilities_keeps_the_spec_and_merges_notes(self):
        spec = LayerSpec(layer=LayerRef.of(SimulationLayerId.GAZEBO), description="x", restriction_notes=(("waves", "old"), ("wind", "keep")))
        updated = spec.with_capabilities(Capabilities(waves=EnvironmentSupport.UNSUPPORTED), (("waves", "new"),))
        assert updated.capabilities.waves == EnvironmentSupport.UNSUPPORTED
        assert updated.note_for("waves") == "new"
        assert updated.note_for("wind") == "keep"
        assert updated.id == spec.id
        assert spec.capabilities == Capabilities(), "specs are immutable"

    def test_specs_default_to_available(self):
        assert LayerSpec(layer=LayerRef.of(AsvSoftwareId.REPLAY), description="x").status == SpecStatus.AVAILABLE

    def test_container_fingerprint_sources_include_the_pins_file(self):
        container = ContainerSpec(image="img", build_fingerprint_source="deploy/images/sitl", entrypoint="/x", upstream_pins_file=UPSTREAM_PINS_FILE)
        assert container.build_fingerprint_sources == ("deploy/images/sitl", UPSTREAM_PINS_FILE)

    def test_container_fingerprint_sources_include_extra_sources(self):
        """The Gazebo image copies the actuator script from the backend, so a change to it rebuilds the image."""
        container = ContainerSpec(image="img", build_fingerprint_source="deploy/images/gazebo", entrypoint="/x", upstream_pins_file=UPSTREAM_PINS_FILE, extra_fingerprint_sources=("backend/a.py",))
        assert container.build_fingerprint_sources == ("deploy/images/gazebo", UPSTREAM_PINS_FILE, "backend/a.py")

    def test_container_without_pins_fingerprints_only_its_folder(self):
        container = ContainerSpec(image="img", build_fingerprint_source="deploy/images/mavproxy", entrypoint="/x")
        assert container.build_fingerprint_sources == ("deploy/images/mavproxy",)

    def test_container_default_image_is_the_tag_the_reference_falls_back_to(self):
        def default(image):
            return ContainerSpec(image=image, build_fingerprint_source="deploy/images/sitl", entrypoint="/x").default_image

        assert default("${SITL_IMAGE:-scenegems-ardupilot-sitl:latest}") == "scenegems-ardupilot-sitl:latest"
        assert default("scenegems-mavproxy:latest") == "scenegems-mavproxy:latest"


class TestPorts:
    def test_the_seven_ports_of_the_design(self):
        assert {port.value for port in Port} == {"vessel_state", "heading_speed_cmd", "waypoint_mission", "mavlink", "actuator_cmd", "clock", "environment"}

    def test_heading_speed_command_is_a_value(self):
        assert HeadingSpeedCommand(1.0, 2.0) == HeadingSpeedCommand(heading=1.0, speed=2.0)


class TestEnvironmentConfig:
    def test_calm_requests_nothing(self):
        environment = EnvironmentConfig.calm(seed=5)
        assert not environment.wind_requested
        assert not environment.waves_requested
        assert environment.seed == 5

    def test_wind_is_requested_by_a_non_zero_vector(self):
        environment = EnvironmentConfig.calm()
        environment.wind_vector = np.array([0.0, 0.0, 0.1])
        assert environment.wind_requested

    def test_waves_are_requested_by_a_non_zero_direction(self):
        wave = WaveConfig(amplitude=0.5, period=5.0, steepness=0.1, direction=np.array([3.0, 4.0]))
        assert wave.speed == 5.0
        assert wave.length == 25.0
        assert wave.is_enabled
        assert not WaveConfig(0.5, 5.0, 0.1, np.zeros(2)).is_enabled


class TestVesselConfig:
    def stack(self):
        return VesselStackConfig(AsvSoftwareId.REPLAY, ControlLayerId.ARDUPILOT, SimulationLayerId.GAZEBO)

    def test_stack_prints_as_the_triple(self):
        assert str(self.stack()) == "replay, ardupilot, gazebo"

    def test_a_simulated_vessel_is_the_default(self):
        assert VesselConfig(agent_id="1", stack=self.stack()).is_simulated

    def test_a_real_vessel_is_not_simulated(self):
        assert not VesselConfig(agent_id="1", stack=self.stack(), context=AgentContext.REAL).is_simulated

    def test_connection_is_required_when_asked_for(self):
        with pytest.raises(ValueError, match="Vessel 1 has no agent connection"):
            VesselConfig(agent_id="1", stack=self.stack()).require_connection()
        connection = AgentConnection(agent_name="a", topic="t", port=None)
        assert VesselConfig(agent_id="1", stack=self.stack(), connection=connection).require_connection() is connection

    def test_instance_lists_only_simulated_vessels(self):
        instance = SimulationInstanceConfig(
            simulation_layer=SimulationLayerId.GAZEBO,
            environment=EnvironmentConfig.calm(),
            vessels={
                "1": VesselConfig(agent_id="1", stack=self.stack()),
                "2": VesselConfig(agent_id="2", stack=self.stack(), context=AgentContext.REAL),
            },
        )
        assert list(instance.simulated_vessels) == ["1"]
        assert instance.speedup == 1
