"""ArduPilotControlLayer: the parameter file follows the hull of the generated model, a vessel model preset included."""

import dataclasses

import pytest

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.vessel_stack.contracts.roles import SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig
from scenegems_tool.vessel_stack.control_layers.ardupilot.ardu_param_generator import generate_ardu_params
from scenegems_tool.vessel_stack.simulation_docker_stack import build_simulation_docker_stack_artifacts
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_model_catalog import VesselOutOfPresetBounds, load_vessel_model_catalog, vessel_dynamics_overrides
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, make_vessel, mqtt_connection, stack_instance
from tests.scenegems_tool.vessel_stack.sdf import parse_params

PRESET = "hanjin_pretoria"  # a Panamax container ship with a rudder: 226 to 306 m long, 27.4 to 37 m wide, 6 to 13.5 m of draft
CRUISE_SPEED = 8.0
GAINS = ("ATC_STR_RAT_FF", "ATC_STR_RAT_P", "ATC_STR_RAT_I", "ATC_STR_ANG_P", "MOT_SPD_SCA_BASE", "CRUISE_THROTTLE")


def panamax_vessel(steering_type: str = "rudder", draft: float = 8.565):
    vessel = make_vessel(0, True, length=266.0, max_speed=12.0, max_angular_speed=0.01, max_acceleration=0.05)
    return dataclasses.replace(vessel, breadth=32.2, draft=draft, height=2.5 * draft, _propeller_diameter=0.6 * draft, _motor_length=0.9 * draft, _steering_type=steering_type)


def params_of_stack(vessel, simulation_layer: SimulationLayerId, preset=None) -> dict:
    """The parameter file the control layer writes for the vessel alone on a straight course."""
    instance = stack_instance(simulation_layer, [0])
    instance.vessels["0"].vessel_model_preset = preset
    trajectories = TrajectoryBuilder.default_trajectory_from_scene(ConcreteScene({vessel: ActorState(0.0, 0.0, CRUISE_SPEED, 0.0)}), 1, 60)
    writes, _ = build_simulation_docker_stack_artifacts(instance, trajectories, mqtt_connection(), GEOFENCE, headless=True)
    return parse_params(next(content for path, content in writes if path.endswith("params-agent_0.params")))


def expected_params(vessel, simulation_layer: SimulationLayerId, overrides) -> dict:
    calm = EnvironmentConfig.calm()
    return generate_ardu_params(vessel, CRUISE_SPEED, calm.wind_vector, calm.wave, simulation_layer, guided_targets=True, overrides=overrides)


class TestVesselModelPreset:
    def test_the_shipped_preset_fits_the_vessel_and_changes_its_hull(self):
        vessel = panamax_vessel()
        preset = load_vessel_model_catalog().get(PRESET)
        assert preset.fits(vessel) and preset.dynamics
        assert vessel_dynamics_overrides(vessel, PRESET) != vessel_dynamics_overrides(vessel)

    def test_a_preset_changes_the_gains_of_a_rudder_vessel_on_gazebo(self):
        vessel = panamax_vessel()
        plain, preset = params_of_stack(vessel, SimulationLayerId.GAZEBO), params_of_stack(vessel, SimulationLayerId.GAZEBO, PRESET)
        for name in GAINS:
            assert preset[name] != plain[name], name
            assert preset[name] > 0 and plain[name] > 0, name
        assert (preset["SERVO1_FUNCTION"], preset["SERVO3_FUNCTION"]) == (plain["SERVO1_FUNCTION"], plain["SERVO3_FUNCTION"]) == (26, 70)

    def test_the_gains_are_those_of_the_hull_with_the_presets_values(self):
        vessel = panamax_vessel()
        params = params_of_stack(vessel, SimulationLayerId.GAZEBO, PRESET)
        expected = expected_params(vessel, SimulationLayerId.GAZEBO, vessel_dynamics_overrides(vessel, PRESET))
        for name in GAINS:
            assert params[name] == pytest.approx(expected[name], rel=1e-12), name

    def test_without_a_preset_the_gains_are_those_of_the_override_files_alone(self):
        vessel = panamax_vessel()
        params = params_of_stack(vessel, SimulationLayerId.GAZEBO)
        expected = expected_params(vessel, SimulationLayerId.GAZEBO, vessel_dynamics_overrides(vessel))
        for name in GAINS:
            assert params[name] == pytest.approx(expected[name], rel=1e-12), name

    def test_a_preset_the_vessel_cannot_take_fails_the_stack(self):
        with pytest.raises(VesselOutOfPresetBounds, match="its steering type is skid, the preset's is rudder"):
            params_of_stack(panamax_vessel(steering_type="skid"), SimulationLayerId.GAZEBO, PRESET)
        with pytest.raises(VesselOutOfPresetBounds, match="its draft of 15 m is outside 6 to 13.5 m"):
            params_of_stack(panamax_vessel(draft=15.0), SimulationLayerId.GAZEBO, PRESET)

    def test_a_preset_does_not_change_the_gains_of_sitls_own_boat(self):
        """SITL's boat does not follow the vessel's hull, so only the generated Gazebo hull has gains a preset can change."""
        vessel = panamax_vessel()
        plain, preset = params_of_stack(vessel, SimulationLayerId.ARDUPILOT_SIM), params_of_stack(vessel, SimulationLayerId.ARDUPILOT_SIM, PRESET)
        assert preset == plain
        assert (plain["SERVO1_FUNCTION"], plain["SERVO3_FUNCTION"]) == (26, 70)
