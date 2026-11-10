"""The workbench vocabulary (simulatorType, asvSystem, controlLayer, and the older controlMode) and the stack triples it maps to."""

import pytest

from scenegems_tool.gateway.workbench_stack_mapping import (
    asv_system_from_control_mode,
    control_mode_label,
    default_control_layer,
    simulation_layer_from_simulator_type,
    simulator_type_label,
    workbench_adapter_ids,
    workbench_stack,
)
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId


class TestSimulatorType:
    @pytest.mark.parametrize("label,layer", [("Gazebo", SimulationLayerId.GAZEBO), ("ArduPilot Sim", SimulationLayerId.ARDUPILOT_SIM), ("Kinematic", SimulationLayerId.KINEMATIC)])
    def test_labels_map_to_layers(self, label, layer):
        assert simulation_layer_from_simulator_type(label) == layer
        assert simulator_type_label(layer) == label

    @pytest.mark.parametrize("label", ["gazebo", "GAZEBO", "  Gazebo  ", "ardupilot sim", "kinematic"])
    def test_label_is_case_and_space_insensitive(self, label):
        simulation_layer_from_simulator_type(label)

    def test_unknown_simulator_type_lists_the_choices(self):
        with pytest.raises(ValueError, match="Unknown simulatorType 'Webots'; expected one of Gazebo, ArduPilot Sim, Kinematic"):
            simulation_layer_from_simulator_type("Webots")


class TestControlMode:
    @pytest.mark.parametrize("label,software", [("autonomous", AsvSystemId.REPLAY), ("external", AsvSystemId.MISSION_PLANNER)])
    def test_modes_map_to_asv_system(self, label, software):
        assert asv_system_from_control_mode(label) == software
        assert control_mode_label(software) == label

    def test_control_mode_is_case_sensitive(self):
        with pytest.raises(ValueError, match="Unknown controlMode 'Autonomous'; expected one of autonomous, external"):
            asv_system_from_control_mode("Autonomous")

    def test_usv_navigation_has_no_arduagent_mode(self):
        assert control_mode_label(AsvSystemId.USV_NAVIGATION) is None


class TestStack:
    def test_asv_system_and_control_layer_name_the_triple(self):
        stack = workbench_stack("Gazebo", "usv_navigation", "custom")
        assert (stack.asv_system, stack.control_layer, stack.simulation_layer) == (AsvSystemId.USV_NAVIGATION, ControlLayerId.CUSTOM, SimulationLayerId.GAZEBO)

    def test_an_older_client_names_the_asv_system_by_control_mode(self):
        stack = workbench_stack("ArduPilot Sim", None, None, "external")
        assert (stack.asv_system, stack.control_layer, stack.simulation_layer) == (AsvSystemId.MISSION_PLANNER, ControlLayerId.ARDUPILOT, SimulationLayerId.ARDUPILOT_SIM)

    def test_asv_system_wins_over_control_mode(self):
        assert workbench_stack("Gazebo", "usv_navigation", None, "autonomous").asv_system == AsvSystemId.USV_NAVIGATION

    @pytest.mark.parametrize(
        "layer,control", [(SimulationLayerId.KINEMATIC, ControlLayerId.NONE), (SimulationLayerId.GAZEBO, ControlLayerId.ARDUPILOT), (SimulationLayerId.ARDUPILOT_SIM, ControlLayerId.ARDUPILOT)]
    )
    def test_the_control_layer_defaults_per_simulator(self, layer, control):
        assert default_control_layer(layer) == control
        assert workbench_stack(simulator_type_label(layer), "replay", None).control_layer == control

    @pytest.mark.parametrize(
        "asv,control,message",
        [
            ("pilot", None, "Unknown asvSystem 'pilot'; expected one of replay, usv_navigation, mission_planner"),
            ("replay", "pid", "Unknown controlLayer 'pid'"),
            (None, None, "needs an asvSystem"),
        ],
    )
    def test_unknown_or_missing_values_are_rejected(self, asv, control, message):
        with pytest.raises(ValueError, match=message):
            workbench_stack("Gazebo", asv, control)


class TestAdapters:
    def test_an_instance_of_simulated_vessels_uses_the_registry_defaults(self):
        for software in ("replay", "mission_planner", "usv_navigation"):
            assert workbench_adapter_ids(workbench_stack("ArduPilot Sim", software, None), instance_has_real_vessel=False) == ()

    def test_an_instance_with_a_real_vessel_runs_through_arduagent(self):
        assert workbench_adapter_ids(workbench_stack("ArduPilot Sim", "replay", None), instance_has_real_vessel=True) == ("replay_arduagent_follower",)
        assert workbench_adapter_ids(workbench_stack("ArduPilot Sim", "mission_planner", None), instance_has_real_vessel=True) == ("mission_planner_mavlink_port",)

    def test_usv_navigation_has_no_arduagent_adapter_to_select(self):
        assert workbench_adapter_ids(workbench_stack("ArduPilot Sim", "usv_navigation", None), instance_has_real_vessel=True) == ()
