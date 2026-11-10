"""Key properties of the generated Gazebo stack (the full output is pinned by the snapshots of test_simulation_docker_stack)."""

import pytest

from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselStackConfig
from scenegems_tool.vessel_stack.registry.resolver import StackUnavailableError
from scenegems_tool.vessel_stack.simulation_docker_stack import build_simulation_docker_stack_artifacts
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.hydrodynamics import RHO_WATER
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, encounter_trajectories, mqtt_connection, stack_instance
from tests.scenegems_tool.vessel_stack.sdf import child_float, parse_params, parse_sdf, plugins
from tests.scenegems_tool.vessel_stack.stack_cases import generate_stack


@pytest.fixture(scope="module")
def world(gazebo_stack):
    return parse_sdf(gazebo_stack.files["ocean_world.sdf"])


@pytest.fixture(scope="module")
def model(gazebo_stack):
    return parse_sdf(gazebo_stack.files["agent_0_model.sdf"])


class TestCompose:
    def test_services_are_sitl_and_replay_per_vessel_and_gazebo(self, gazebo_stack):
        assert list(gazebo_stack.compose["services"]) == ["agent_0", "agent_0_asv_software", "agent_1", "agent_1_asv_software", "gazebo"]

    def test_sitl_uses_the_json_backend_against_the_gazebo_service(self, gazebo_stack):
        for name in ("agent_0", "agent_1"):
            environment = gazebo_stack.compose["services"][name]["environment"]
            assert "SITL_SIMULATOR=gazebo" in environment
            assert "SITL_MODEL=JSON" in environment
            assert "SITL_RESOLVE_HOST=gazebo" in environment

    def test_sitl_instances_have_distinct_ids(self, gazebo_stack):
        services = gazebo_stack.compose["services"]
        assert "SITL_SYSID=1" in services["agent_0"]["environment"] and "SITL_INSTANCE=0" in services["agent_0"]["environment"]
        assert "SITL_SYSID=2" in services["agent_1"]["environment"] and "SITL_INSTANCE=1" in services["agent_1"]["environment"]

    def test_the_lockstep_path_starts_no_mavproxy_or_arduagent(self, gazebo_stack):
        assert not [name for name in gazebo_stack.compose["services"] if name.endswith("_mavproxy") or name.endswith("_arduagent")]

    def test_gazebo_waits_for_every_agent(self, gazebo_stack):
        assert gazebo_stack.compose["services"]["gazebo"]["depends_on"] == ["agent_0", "agent_1"]

    def test_headless_run_sets_the_headless_flag(self, gazebo_stack):
        assert gazebo_stack.compose["services"]["gazebo"]["environment"]["GZ_HEADLESS"] == "1"

    def test_gui_run_clears_the_headless_flag_and_adds_the_scene_broadcaster(self):
        stack = generate_stack("gazebo_lockstep_wind", headless=False)
        assert stack.compose["services"]["gazebo"]["environment"]["GZ_HEADLESS"] == "0"
        assert plugins(parse_sdf(stack.files["ocean_world.sdf"]), "gz-sim-scene-broadcaster-system")

    def test_sitl_is_homed_at_the_reference_geofence_centre(self, gazebo_stack):
        assert "SITL_CUSTOM_LOCATION=57.757128,16.673189,0,0" in gazebo_stack.compose["services"]["agent_0"]["environment"]


class TestWorld:
    def test_world_name_and_physics_step(self, world):
        assert world.find("world").get("name") == "ocean_world"
        assert child_float(world.find("world/physics"), "max_step_size") == 0.005

    def test_speedup_is_the_real_time_factor(self):
        world = parse_sdf(generate_stack("gazebo_lockstep_wind").files["ocean_world.sdf"])
        assert child_float(world.find("world/physics"), "real_time_factor") == 1.0

    def test_wind_is_set_and_the_wind_effects_system_is_loaded(self, world):
        assert world.find("world/wind/linear_velocity").text == "3.0 4.0 0.0"
        assert plugins(world, "gz-sim-wind-effects-system")

    def test_waves_system_is_absent_and_flat_buoyancy_is_loaded(self, world):
        assert plugins(world, "gz-sim-buoyancy-system")
        assert not plugins(world, "gz-waves1-waves-model-system")

    def test_reference_point_is_the_own_ship_position(self, world):
        coordinates = world.find("world/spherical_coordinates")
        assert float(coordinates.find("latitude_deg").text) == pytest.approx(57.757128, abs=1e-5)
        assert float(coordinates.find("longitude_deg").text) == pytest.approx(16.673189, abs=1e-5)

    def test_each_vessel_is_included_at_its_start_pose(self, world):
        includes = world.findall("world/include")
        assert len(includes) == 2
        assert "agent_0_model.sdf" in includes[0].find("uri").text
        assert includes[0].find("pose").text.split()[:2] == ["0.0", "0.0"]
        assert includes[1].find("pose").text.split()[:2] == ["6000.0", "0.0"]
        assert float(includes[1].find("pose").text.split()[5]) == pytest.approx(3.141592653589793)


class TestVesselModel:
    def test_model_is_named_after_the_agent(self, gazebo_stack):
        assert parse_sdf(gazebo_stack.files["agent_0_model.sdf"]).find("model").get("name") == "agent_0"
        assert parse_sdf(gazebo_stack.files["agent_1_model.sdf"]).find("model").get("name") == "agent_1"

    def test_thrusters_are_on_both_sides_aft_of_midship(self, model):
        poses = {link.get("name"): [float(value) for value in link.find("pose").text.split()] for link in model.iter("link") if link.get("name", "").startswith("motor_")}
        assert set(poses) == {"motor_port_link", "motor_stbd_link"}
        assert poses["motor_port_link"][0] == poses["motor_stbd_link"][0] < 0
        assert poses["motor_port_link"][1] == -poses["motor_stbd_link"][1] > 0, "the port thruster is on the +y side (heading east, north is port)"

    def test_both_thrusters_are_sized_to_the_same_limit(self, model):
        limits = [child_float(plugin, "max_thrust_cmd") for plugin in plugins(model, "gz-sim-thruster-system")]
        assert len(limits) == 2 and limits[0] == limits[1] > 0

    def test_ardupilot_plugin_runs_in_lock_step_on_two_motor_channels(self, model):
        (plugin,) = plugins(model, "ArduPilotPlugin")
        assert child_float(plugin, "lock_step") == 1
        channels = {control.get("channel"): control.find("jointName").text for control in plugin.findall("control")}
        assert channels == {"0": "motor_port_joint", "2": "motor_stbd_joint"}
        for control in plugin.findall("control"):
            assert control.find("cmd_topic").text.startswith("/model/agent_0/joint/")

    def test_pwm_range_maps_to_the_sized_thrust(self, model):
        (plugin,) = plugins(model, "ArduPilotPlugin")
        limit = child_float(plugins(model, "gz-sim-thruster-system")[0], "max_thrust_cmd")
        control = plugin.find("control")
        assert child_float(control, "multiplier") == pytest.approx(2 * limit, rel=1e-5)
        assert child_float(control, "offset") == -0.5

    def test_total_mass_is_the_displacement_at_the_draft(self, model):
        total = sum(float(link.find("inertial/mass").text) for link in model.iter("link") if link.find("inertial/mass") is not None)
        # The 30 m test vessel has breadth 10 m and draft 1.8 m; the block coefficient is 0.6.
        assert total == pytest.approx(RHO_WATER * 0.6 * 30.0 * 10.0 * 1.8, rel=1e-3)

    def test_windage_link_carries_the_wind(self, model):
        windage = [link for link in model.iter("link") if link.get("name") == "windage_link"]
        assert len(windage) == 1
        assert windage[0].find("enable_wind").text == "true"

    def test_hull_floats_on_nine_buoyancy_cells(self, model):
        cells = [collision for collision in model.iter("collision") if collision.get("name").startswith("collision_hull_")]
        assert len(cells) == 9

    def test_imu_sensor_feeds_the_ardupilot_plugin(self, model):
        (plugin,) = plugins(model, "ArduPilotPlugin")
        names = [sensor.get("name") for sensor in model.iter("sensor")]
        assert plugin.find("imuName").text in names


class TestParams:
    def test_vessel_limits_become_ardupilot_limits(self, gazebo_stack):
        params = parse_params(gazebo_stack.files["params-agent_0.params"])
        assert params["SPEED_MAX"] == pytest.approx(1.2 * 20.57778), "full thrust of the generated hull"
        assert params["WP_SPEED"] == pytest.approx(20.57778), "the lockstep link's GUIDED targets are capped at the vessel's max speed"
        assert params["CRUISE_SPEED"] == 8.0
        assert params["ATC_ACCEL_MAX"] == 0.4

    def test_the_hull_is_skid_steered(self, gazebo_stack):
        params = parse_params(gazebo_stack.files["params-agent_0.params"])
        assert (params["SERVO1_FUNCTION"], params["SERVO3_FUNCTION"]) == (73, 74)
        assert params["ATC_STR_RAT_FF"] > 0

    def test_wind_reaches_ardupilot_as_speed_and_direction(self, gazebo_stack):
        params = parse_params(gazebo_stack.files["params-agent_0.params"])
        assert params["SIM_WIND_SPD"] == pytest.approx(5.0)
        assert params["SIM_WAVE_ENABLE"] == 0


def build(instance):
    writes, compose = build_simulation_docker_stack_artifacts(instance, encounter_trajectories("head_on", 60), mqtt_connection(), GEOFENCE, headless=True)
    return {path.rsplit("/", 1)[-1]: content for path, content in writes}, compose


@pytest.fixture(scope="module")
def custom_stack():
    return build(stack_instance(SimulationLayerId.GAZEBO, [0, 1], control_layer=ControlLayerId.CUSTOM))


class TestCustomControlLayer:
    def test_every_vessel_has_its_controller_and_replay_container_next_to_gazebo(self, custom_stack):
        assert list(custom_stack[1]["services"]) == ["agent_0_controller", "agent_0_asv_software", "agent_1_controller", "agent_1_asv_software", "gazebo"]

    def test_the_world_starts_paused_for_the_actuator_and_waits_for_no_agent(self, custom_stack):
        gazebo = custom_stack[1]["services"]["gazebo"]
        assert gazebo["environment"]["GZ_START_PAUSED"] == "1"
        assert gazebo["environment"]["GZ_ACTUATOR_PORT"] == "11400"
        assert "depends_on" not in gazebo

    def test_the_world_is_stepped_without_a_real_time_factor(self, custom_stack):
        world = parse_sdf(custom_stack[0]["ocean_world.sdf"])
        assert child_float(world.find("world/physics"), "real_time_factor") == 0.0

    def test_the_models_have_no_ardupilot_plugin(self, custom_stack):
        for name in ("agent_0_model.sdf", "agent_1_model.sdf"):
            assert plugins(parse_sdf(custom_stack[0][name]), "ArduPilotPlugin") == [], name

    def test_an_ardupilot_world_still_waits_for_its_agents(self, gazebo_stack):
        gazebo = gazebo_stack.compose["services"]["gazebo"]
        assert "GZ_START_PAUSED" not in gazebo["environment"] and gazebo["depends_on"] == ["agent_0", "agent_1"]

    def test_custom_and_ardupilot_vessels_cannot_share_a_world(self):
        instance = stack_instance(SimulationLayerId.GAZEBO, [0, 1], control_layer=ControlLayerId.CUSTOM)
        instance.vessels["1"].stack = VesselStackConfig(instance.vessels["1"].stack.asv_software, ControlLayerId.ARDUPILOT, SimulationLayerId.GAZEBO)
        with pytest.raises(StackUnavailableError, match="mixes"):
            build(instance)
