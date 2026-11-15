"""generate_vessel_model: the hull, the steering gear of each steering type, the ArduPilot and custom variants, wind and waves, and the hull mesh."""

import dataclasses
import math
import xml.etree.ElementTree as ET
from typing import List, Tuple

import numpy as np
import pytest

from logical_level.mapping.vessel_type import VesselTypeMap
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig, WaveConfig
from scenegems_tool.vessel_stack.simulation_layers.gazebo import gazebo_specs
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators import vessel_model_generator
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.hull_form import HullForm
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.hydrodynamics import rudder_normal_force_coefficient
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import BUOYANCY_GRID, HULL_STATIONS, check_inertia, derive_vessel_dynamics, hull_stations
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics_overrides import VesselDynamicsOverrides
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_model_generator import (
    MAX_WAVE_CELLS,
    STEERING_JOINT,
    STEERING_LINK,
    STEERING_STOP_MARGIN,
    buoyancy_cells,
    buoyancy_stations,
    deep_water_wavelength,
    generate_hull_mesh,
    generate_vessel_model,
    hull_mesh_filename,
    render_vessel_model,
    sdf_value,
    steering_topic,
    thrust_topic,
    thruster_names,
)
from tests.scenegems_tool.vessel_stack.scenarios import make_vessel, wind_environment
from tests.scenegems_tool.vessel_stack.sdf import child_float, child_floats, child_tags, child_text, joint, link, names, parse_sdf, plugin_for, plugins
from tests.scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessels import HELM_STEERING_TYPES, SCALES, STEERING_TYPES, scaled_vessel, steered, vessel_of_type

CONTROL_LAYERS = (ControlLayerId.ARDUPILOT, ControlLayerId.CUSTOM)
THRUSTER_SYSTEM = "gz-sim-thruster-system"
HYDRODYNAMICS_SYSTEM = "gz-sim-hydrodynamics-system"
HELM_CONTROLLER = "gz-sim-joint-position-controller-system"
HYDRODYNAMIC_COEFFICIENTS = ("xDotU", "yDotV", "zDotW", "nDotR", "xU", "yV", "zW", "kP", "mQ", "nR", "xUabsU", "yVabsV", "nRabsR")


@pytest.fixture
def vessel():
    """A vessel as a scene file without a steering type describes it: skid steered."""
    return make_vessel(2, True)


@pytest.fixture(params=STEERING_TYPES)
def steering(request) -> str:
    return request.param


@pytest.fixture(params=HELM_STEERING_TYPES)
def helm_steering(request) -> str:
    return request.param


@pytest.fixture(params=CONTROL_LAYERS, ids=lambda layer: layer.value)
def control_layer(request) -> ControlLayerId:
    return request.param


def model(vessel, control_layer: ControlLayerId = ControlLayerId.CUSTOM, agent_name: str = "boat", **arguments) -> ET.Element:
    return parse_sdf(generate_vessel_model(vessel, agent_name, control_layer, **arguments))


def windage_mass(sdf_text: str) -> float:
    return child_float(link(parse_sdf(sdf_text), "windage_link"), "inertial/mass")


def hull_collisions(root: ET.Element) -> List[ET.Element]:
    return [collision for collision in root.iter("collision") if collision.get("name", "").startswith("collision_hull_")]


def center_of_buoyancy(root: ET.Element) -> Tuple[float, float]:
    """(x, y) of the center of the volume the model's buoyant boxes hold below the waterline, in the model's frame."""
    boxes = [(child_floats(collision, "pose"), child_floats(collision, "geometry/box/size")) for collision in hull_collisions(root)]
    volume = sum(size[0] * size[1] * size[2] / 2 for _, size in boxes)
    along = sum(pose[0] * size[0] * size[1] * size[2] / 2 for pose, size in boxes) / volume
    across = sum(pose[1] * size[0] * size[1] * size[2] / 2 for pose, size in boxes) / volume
    return along, across


def stl_vertices(text: str) -> List[Tuple[float, ...]]:
    return [tuple(float(value) for value in line.split()[1:]) for line in text.splitlines() if line.strip().startswith("vertex")]


def inertia_of(element: ET.Element) -> tuple:
    return tuple(child_float(element, f"inertial/inertia/{axis}") for axis in ("ixx", "iyy", "izz"))


def waves_environment(period: float = 5.0) -> EnvironmentConfig:
    environment = EnvironmentConfig.calm()
    environment.wave = WaveConfig(amplitude=0.5, period=period, steepness=0.1, direction=np.array([1.0, 0.0]))
    return environment


class TestNames:
    def test_thrusters_by_steering_type(self):
        assert thruster_names("skid") == ("port", "stbd")
        assert thruster_names("rudder") == ("center",)
        assert thruster_names("vectored_thrust") == ("center",)

    def test_topics_are_those_of_the_models_joints(self):
        assert thrust_topic("agent_4", "port") == "/model/agent_4/joint/motor_port_joint/cmd_thrust"
        assert thrust_topic("agent_4", "center") == "/model/agent_4/joint/motor_center_joint/cmd_thrust"
        assert steering_topic("agent_4") == "/model/agent_4/joint/steering_joint/cmd_pos"

    def test_the_steering_gear_and_the_hull_mesh_have_fixed_names(self):
        assert (STEERING_JOINT, STEERING_LINK) == ("steering_joint", "steering_link")
        assert hull_mesh_filename("agent_4") == "agent_4_hull.stl"

    def test_sdf_value_is_the_number_as_the_model_carries_it(self):
        assert sdf_value(1234567.891) == 1234570.0
        assert sdf_value(-0.000123456789) == -0.000123457
        assert sdf_value(2.5) == 2.5


class TestVariants:
    def test_ardupilot_variant_carries_the_plugin_and_the_imu(self, vessel, steering):
        root = model(steered(vessel, steering), ControlLayerId.ARDUPILOT)
        assert len(plugins(root, "ArduPilotPlugin")) == 1
        assert [sensor.get("name") for sensor in root.iter("sensor")] == ["imu_sensor"]

    def test_custom_variant_has_no_ardupilot_plugin_and_no_imu(self, vessel, steering):
        root = model(steered(vessel, steering), ControlLayerId.CUSTOM)
        assert plugins(root, "ArduPilotPlugin") == []
        assert list(root.iter("sensor")) == []

    def test_both_variants_publish_odometry_and_accept_thrust(self, vessel, steering, control_layer):
        root = model(steered(vessel, steering), control_layer)
        assert len(plugins(root, "gz-sim-odometry-publisher-system")) == 1
        assert len(plugins(root, "gz-sim-joint-state-publisher-system")) == 1
        assert len(plugins(root, THRUSTER_SYSTEM)) == (2 if steering == "skid" else 1)

    def test_the_control_layer_changes_nothing_but_the_ardupilot_plugin_and_the_imu(self, vessel, steering):
        ardupilot, custom = (model(steered(vessel, steering), layer) for layer in CONTROL_LAYERS)
        (model_element,) = ardupilot.iter("model")
        model_element.remove(plugins(ardupilot, "ArduPilotPlugin")[0])
        base = link(ardupilot, "base_link")
        base.remove(base.find("sensor"))
        strip = lambda element: [(node.tag, sorted(node.attrib.items()), (node.text or "").strip()) for node in element.iter()]  # noqa: E731
        assert strip(ardupilot) == strip(custom)

    def test_odometry_publishes_at_fifty_hertz(self, vessel):
        assert child_float(plugins(model(vessel), "gz-sim-odometry-publisher-system")[0], "odom_publish_frequency") == 50

    def test_other_control_layers_have_no_gazebo_model(self, vessel, steering):
        with pytest.raises(ValueError, match="No Gazebo vessel model for control layer none"):
            generate_vessel_model(steered(vessel, steering), "boat", ControlLayerId.NONE)

    def test_the_model_and_topics_are_named_after_the_agent(self, vessel):
        text = generate_vessel_model(vessel, "unit_7", ControlLayerId.CUSTOM)
        assert parse_sdf(text).find("model").get("name") == "unit_7"
        assert "/model/unit_7/joint/motor_port_joint/cmd_thrust" in text
        assert "/model/unit_7/joint/motor_stbd_joint/cmd_thrust" in text

    def test_the_header_names_the_steering_and_its_commands(self, vessel):
        skid = generate_vessel_model(vessel, "unit_7", ControlLayerId.CUSTOM)
        rudder = generate_vessel_model(steered(vessel, "rudder"), "unit_7", ControlLayerId.CUSTOM)
        vectored = generate_vessel_model(steered(vessel, "vectored_thrust"), "unit_7", ControlLayerId.CUSTOM)
        assert "skid steered by two thrusters" in skid and "helm angle" not in skid.split("<model")[0]
        assert "a rudder of" in rudder and "one thruster of" in vectored and "turning with the helm" in vectored
        for text in (rudder, vectored):
            header = text.split("<model")[0]
            assert thrust_topic("unit_7", "center") in header and f"helm angle in rad on {steering_topic('unit_7')}" in header

    def test_generation_is_deterministic(self, vessel, steering, control_layer):
        vessel = steered(vessel, steering)
        assert generate_vessel_model(vessel, "boat", control_layer) == generate_vessel_model(vessel, "boat", control_layer)

    def test_the_model_takes_its_pose_from_the_world(self, vessel, steering):
        (model_element,) = model(steered(vessel, steering)).iter("model")
        assert model_element.find("pose") is None
        assert child_text(model_element, "static") == "false" and child_text(model_element, "self_collide") == "false"


class TestLinksAndJoints:
    def test_a_skid_steered_model_has_two_thrusters_and_no_steering_gear(self, vessel, control_layer):
        root = model(vessel, control_layer)
        assert names(root, "link") == ["base_link", "windage_link", "motor_port_link", "motor_stbd_link"]
        assert names(root, "joint") == ["windage_joint", "motor_port_joint", "motor_stbd_joint"]
        assert plugins(root, HELM_CONTROLLER) == []
        assert STEERING_JOINT not in ET.tostring(root, encoding="unicode") and STEERING_LINK not in ET.tostring(root, encoding="unicode")

    def test_a_rudder_or_vectored_thrust_model_has_one_thruster_and_the_steering_gear(self, vessel, helm_steering, control_layer):
        root = model(steered(vessel, helm_steering), control_layer)
        assert sorted(names(root, "link")) == ["base_link", "motor_center_link", "steering_link", "windage_link"]
        assert sorted(names(root, "joint")) == ["motor_center_joint", "steering_joint", "windage_joint"]
        assert len(plugins(root, HELM_CONTROLLER)) == 1
        text = ET.tostring(root, encoding="unicode")
        assert "motor_port" not in text and "motor_stbd" not in text

    def test_every_joint_connects_links_of_the_model_and_every_plugin_names_one_of_its_parts(self, vessel, steering, control_layer):
        root = model(steered(vessel, steering), control_layer)
        links, joints = set(names(root, "link")), set(names(root, "joint"))
        for joint_element in root.iter("joint"):
            assert child_text(joint_element, "parent") in links and child_text(joint_element, "child") in links
        for plugin in root.iter("plugin"):
            for joint_name in list(plugin.iter("joint_name")) + list(plugin.iter("jointName")):
                assert joint_name.text in joints
            for link_name in plugin.iter("link_name"):
                assert link_name.text in links
        children = [child_text(joint_element, "child") for joint_element in root.iter("joint")]
        assert sorted(children) == sorted(links - {"base_link"}), "every link but the hull hangs on exactly one joint"

    def test_the_hull_link_carries_the_dynamics_mass_and_inertia(self, vessel, steering):
        vessel = steered(vessel, steering)
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        base = link(model(vessel, overrides={}), "base_link")
        assert child_float(base, "inertial/mass") == sdf_value(dynamics.hull_mass)
        assert child_floats(base, "inertial/pose") == (0.0, 0.0, sdf_value(dynamics.com_z), 0.0, 0.0, 0.0)
        assert inertia_of(base) == (sdf_value(dynamics.hull_ixx), sdf_value(dynamics.hull_iyy), sdf_value(dynamics.hull_izz))
        assert [child_float(base, f"inertial/inertia/{axis}") for axis in ("ixy", "ixz", "iyz")] == [0.0, 0.0, 0.0]

    def test_the_links_together_weigh_the_displacement(self, vessel, steering):
        vessel = steered(vessel, steering)
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        masses = [child_float(element, "inertial/mass") for element in model(vessel, overrides={}).iter("link")]
        assert sum(masses) == pytest.approx(dynamics.total_mass, rel=1e-5)
        assert sum(masses) == pytest.approx(1025.0 * dynamics.displaced_volume, rel=1e-5)

    def test_every_link_has_an_inertia_gazebo_accepts(self, vessel, steering):
        for element in model(steered(vessel, steering)).iter("link"):
            check_inertia(element.get("name"), *inertia_of(element))
            assert child_float(element, "inertial/mass") > 0

    def test_the_windage_link_is_fixed_to_the_hull_and_feels_the_wind(self, vessel, steering):
        vessel = steered(vessel, steering)
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        root = model(vessel, overrides={})
        windage = link(root, "windage_link")
        assert child_text(windage, "enable_wind") == "true"
        assert child_float(windage, "inertial/mass") == sdf_value(dynamics.windage_mass)
        assert child_floats(windage, "pose") == (0.0, 0.0, sdf_value(dynamics.windage_z), 0.0, 0.0, 0.0)
        windage_joint = joint(root, "windage_joint")
        assert windage_joint.get("type") == "fixed"
        assert (child_text(windage_joint, "parent"), child_text(windage_joint, "child")) == ("base_link", "windage_link")


class TestThrusters:
    def test_two_thrusters_sit_side_by_side_on_the_hull(self, vessel, control_layer):
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        root = model(vessel, control_layer, overrides={})
        port, starboard = link(root, "motor_port_link"), link(root, "motor_stbd_link")
        assert child_floats(port, "pose") == (sdf_value(dynamics.thruster_x), sdf_value(dynamics.thruster_y), sdf_value(dynamics.thruster_z), 0.0, 0.0, 0.0)
        assert child_floats(starboard, "pose") == (sdf_value(dynamics.thruster_x), sdf_value(-dynamics.thruster_y), sdf_value(dynamics.thruster_z), 0.0, 0.0, 0.0)
        assert child_floats(port, "pose")[1] > 0 > child_floats(starboard, "pose")[1], "y is to port"
        for name in ("port", "stbd"):
            assert child_text(joint(root, f"motor_{name}_joint"), "parent") == "base_link"

    def test_one_thruster_sits_on_the_centerline(self, vessel, helm_steering, control_layer):
        vessel = steered(vessel, helm_steering)
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        root = model(vessel, control_layer, overrides={})
        assert child_floats(link(root, "motor_center_link"), "pose") == (sdf_value(dynamics.thruster_x), 0.0, sdf_value(dynamics.thruster_z), 0.0, 0.0, 0.0)

    def test_a_rudder_models_thruster_is_fixed_to_the_hull(self, vessel, control_layer):
        root = model(steered(vessel, "rudder"), control_layer)
        assert child_text(joint(root, "motor_center_joint"), "parent") == "base_link"

    def test_a_vectored_thruster_hangs_on_the_steering_link(self, vessel, control_layer):
        """So its thrust turns with the helm, about the point where it sits."""
        root = model(steered(vessel, "vectored_thrust"), control_layer)
        assert child_text(joint(root, "motor_center_joint"), "parent") == STEERING_LINK
        assert child_floats(link(root, "motor_center_link"), "pose") == child_floats(link(root, STEERING_LINK), "pose")

    def test_every_thruster_pushes_along_its_joint_axis_with_the_dynamics_values(self, vessel, steering, control_layer):
        vessel = steered(vessel, steering)
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        root = model(vessel, control_layer, overrides={})
        for name in thruster_names(steering):
            motor_joint = joint(root, f"motor_{name}_joint")
            assert motor_joint.get("type") == "revolute"
            assert child_text(motor_joint, "child") == f"motor_{name}_link"
            assert child_floats(motor_joint, "axis/xyz") == (1.0, 0.0, 0.0), "forward"
            system = plugin_for(root, THRUSTER_SYSTEM, "joint_name", f"motor_{name}_joint")
            assert child_float(system, "thrust_coefficient") == sdf_value(dynamics.thrust_coefficient)
            assert child_float(system, "propeller_diameter") == sdf_value(dynamics.propeller_diameter)
            assert child_float(system, "fluid_density") == 1025
            assert child_float(system, "max_thrust_cmd") == sdf_value(dynamics.max_thrust)
            assert child_float(system, "min_thrust_cmd") == sdf_value(-dynamics.max_thrust)
            assert (child_text(system, "velocity_control"), child_text(system, "use_angvel_cmd")) == ("1", "0")
            assert child_float(link(root, f"motor_{name}_link"), "inertial/mass") == sdf_value(dynamics.thruster_mass)

    def test_the_thrusters_together_give_the_full_thrust(self, vessel, steering):
        vessel = steered(vessel, steering)
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        limits = [child_float(system, "max_thrust_cmd") for system in plugins(model(vessel, overrides={}), THRUSTER_SYSTEM)]
        assert sum(limits) == pytest.approx(dynamics.total_thrust, rel=1e-5)


class TestSteeringGear:
    def test_the_steering_joint_turns_about_the_vertical(self, vessel, helm_steering, control_layer):
        steering_joint = joint(model(steered(vessel, helm_steering), control_layer, overrides={}), STEERING_JOINT)
        assert steering_joint.get("type") == "revolute"
        assert (child_text(steering_joint, "parent"), child_text(steering_joint, "child")) == ("base_link", STEERING_LINK)
        assert child_floats(steering_joint, "axis/xyz") == (0.0, 0.0, 1.0), "counterclockwise seen from above"

    def test_the_steering_joints_stops_lie_five_degrees_beyond_hard_over(self, vessel, helm_steering, control_layer):
        """A velocity commanded joint that reaches its stop stays on it, so the stops lie beyond the largest angle commanded."""
        vessel = steered(vessel, helm_steering)
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        steering_joint = joint(model(vessel, control_layer, overrides={}), STEERING_JOINT)
        assert STEERING_STOP_MARGIN == pytest.approx(math.radians(5.0))
        assert child_float(steering_joint, "axis/limit/lower") == sdf_value(-dynamics.steering_max_angle - STEERING_STOP_MARGIN)
        assert child_float(steering_joint, "axis/limit/upper") == sdf_value(dynamics.steering_max_angle + STEERING_STOP_MARGIN)
        assert child_float(steering_joint, "axis/limit/upper") == pytest.approx(math.radians(40.0 if helm_steering == "rudder" else 35.0), rel=1e-5)
        assert child_float(steering_joint, "axis/limit/lower") == -child_float(steering_joint, "axis/limit/upper")
        assert child_float(steering_joint, "axis/limit/lower") < -dynamics.steering_max_angle < dynamics.steering_max_angle < child_float(steering_joint, "axis/limit/upper")

    def test_the_ardupilot_plugins_helm_commands_end_at_hard_over_inside_the_stops(self, vessel, helm_steering):
        """The servo range, by the channel's multiplier and offset, spans hard over to hard over and no more."""
        vessel = steered(vessel, helm_steering)
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        root = model(vessel, ControlLayerId.ARDUPILOT, overrides={})
        (helm,) = [control for control in plugins(root, "ArduPilotPlugin")[0].iter("control") if child_text(control, "jointName") == STEERING_JOINT]
        multiplier, offset = child_float(helm, "multiplier"), child_float(helm, "offset")
        servo_min, servo_max = child_float(helm, "servo_min"), child_float(helm, "servo_max")
        commands = [((pwm - servo_min) / (servo_max - servo_min) + offset) * multiplier for pwm in (servo_min, servo_max)]
        assert commands == pytest.approx([-dynamics.steering_max_angle, dynamics.steering_max_angle], rel=1e-5), "hard over to port and to starboard"
        steering_joint = joint(root, STEERING_JOINT)
        lower, upper = child_float(steering_joint, "axis/limit/lower"), child_float(steering_joint, "axis/limit/upper")
        assert lower < commands[0] and commands[1] < upper
        assert commands[0] - lower == pytest.approx(STEERING_STOP_MARGIN, rel=1e-3) and upper - commands[1] == pytest.approx(STEERING_STOP_MARGIN, rel=1e-3)

    def test_the_steering_joint_has_an_effort_limit_far_above_any_load(self, vessel, helm_steering):
        """A velocity commanded joint keeps its angle limits only with an effort limit."""
        vessel = steered(vessel, helm_steering)
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        effort = child_float(joint(model(vessel, overrides={}), STEERING_JOINT), "axis/limit/effort")
        assert effort == sdf_value(max(1.0e6, 10.0 * dynamics.total_thrust * dynamics.length))
        assert effort >= 1.0e6 and effort > 10.0 * dynamics.max_yaw_moment

    def test_a_small_vessels_steering_joint_keeps_the_least_effort_limit(self, helm_steering):
        small = scaled_vessel("5m", helm_steering)
        assert child_float(joint(model(small), STEERING_JOINT), "axis/limit/effort") == 1.0e6

    def test_the_helm_controller_moves_the_joint_at_the_helms_speed(self, vessel, helm_steering, control_layer):
        vessel = steered(vessel, helm_steering)
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        (controller,) = plugins(model(vessel, control_layer, overrides={}), HELM_CONTROLLER)
        assert controller.get("name") == "gz::sim::systems::JointPositionController"
        assert child_text(controller, "joint_name") == STEERING_JOINT
        assert child_text(controller, "topic") == steering_topic("boat") == "/model/boat/joint/steering_joint/cmd_pos"
        assert child_text(controller, "use_velocity_commands") == "true"
        assert child_float(controller, "cmd_max") == sdf_value(dynamics.steering_rate)
        assert child_float(controller, "cmd_min") == sdf_value(-dynamics.steering_rate)
        assert child_float(controller, "cmd_max") > 0

    def test_the_steering_link_sits_where_the_helms_force_acts(self, vessel, helm_steering):
        vessel = steered(vessel, helm_steering)
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        steering_link = link(model(vessel, overrides={}), STEERING_LINK)
        assert child_floats(steering_link, "pose") == (sdf_value(dynamics.steering_x), 0.0, sdf_value(dynamics.steering_z), 0.0, 0.0, 0.0)
        assert child_float(steering_link, "inertial/mass") == sdf_value(dynamics.steering_mass)
        assert child_floats(steering_link, "pose")[0] < 0, "aft"
        assert list(steering_link.iter("collision")) == [], "it adds no buoyancy"

    def test_the_rudder_is_a_blade_of_its_chord_and_span(self, vessel):
        vessel = steered(vessel, "rudder")
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        chord, thickness, span = child_floats(link(model(vessel, overrides={}), STEERING_LINK), "visual/geometry/box/size")
        assert (chord, span) == (sdf_value(dynamics.rudder_chord), sdf_value(dynamics.rudder_span))
        assert 0 < thickness < chord
        assert chord * span == pytest.approx(dynamics.rudder_area, rel=1e-5)

    def test_the_rudder_link_has_a_hydrodynamics_system_with_the_normal_force_term_only(self, vessel, control_layer):
        vessel = steered(vessel, "rudder")
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        root = model(vessel, control_layer, overrides={})
        rudder = plugin_for(root, HYDRODYNAMICS_SYSTEM, "link_name", STEERING_LINK)
        assert rudder.get("name") == "gz::sim::systems::Hydrodynamics"
        assert sorted(child_tags(rudder)) == ["disable_added_mass", "disable_coriolis", "link_name", "yVabsU"]
        assert child_float(rudder, "yVabsU") == sdf_value(rudder_normal_force_coefficient(dynamics.rudder_area, dynamics.rudder_lift_slope))
        assert child_float(rudder, "yVabsU") == pytest.approx(-0.5 * 1025.0 * dynamics.rudder_area * 2.5, rel=1e-5)
        assert (child_text(rudder, "disable_coriolis"), child_text(rudder, "disable_added_mass")) == ("true", "true")
        assert len(plugins(root, HYDRODYNAMICS_SYSTEM)) == 2

    def test_only_a_rudder_has_a_hydrodynamics_system_of_its_own(self, vessel, control_layer):
        for steering_type in ("skid", "vectored_thrust"):
            (hull,) = plugins(model(steered(vessel, steering_type), control_layer), HYDRODYNAMICS_SYSTEM)
            assert child_text(hull, "link_name") == "base_link"
            assert hull.find("yVabsU") is None

    def test_a_vectored_thrusters_mount_is_a_cylinder_without_a_force_of_its_own(self, vessel):
        vessel = steered(vessel, "vectored_thrust")
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        mount = link(model(vessel, overrides={}), STEERING_LINK)
        assert child_float(mount, "visual/geometry/cylinder/radius") == sdf_value(dynamics.propeller_diameter / 2)
        assert child_float(mount, "visual/geometry/cylinder/length") == sdf_value(dynamics.motor_length)


class TestArduPilotPlugin:
    def channels(self, vessel) -> dict:
        (plugin,) = plugins(model(vessel, ControlLayerId.ARDUPILOT, overrides={}), "ArduPilotPlugin")
        return {int(control.get("channel")): control for control in plugin.iter("control")}

    def test_skid_steering_commands_the_two_thrusts(self, vessel):
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        channels = self.channels(vessel)
        assert sorted(channels) == [0, 2]
        for channel, name in ((0, "port"), (2, "stbd")):
            control = channels[channel]
            assert child_text(control, "jointName") == f"motor_{name}_joint"
            assert child_text(control, "cmd_topic") == thrust_topic("boat", name)
            assert child_float(control, "multiplier") == sdf_value(2 * dynamics.max_thrust)

    def test_a_helm_takes_channel_zero_and_the_thrust_channel_two(self, vessel, helm_steering):
        vessel = steered(vessel, helm_steering)
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        channels = self.channels(vessel)
        assert sorted(channels) == [0, 2]
        helm, thrust = channels[0], channels[2]
        assert child_text(helm, "jointName") == STEERING_JOINT
        assert child_text(helm, "cmd_topic") == steering_topic("boat")
        assert child_float(helm, "multiplier") == sdf_value(2 * dynamics.steering_max_angle)
        assert child_text(thrust, "jointName") == "motor_center_joint"
        assert child_text(thrust, "cmd_topic") == thrust_topic("boat", "center")
        assert child_float(thrust, "multiplier") == sdf_value(2 * dynamics.max_thrust)

    def test_every_channel_maps_the_servo_range_around_its_middle(self, vessel, steering):
        for control in self.channels(steered(vessel, steering)).values():
            assert child_text(control, "type") == "COMMAND"
            assert child_float(control, "offset") == -0.5
            assert (child_float(control, "servo_min"), child_float(control, "servo_max")) == (1000, 2000)

    def test_servo_outputs_span_hard_over_to_hard_over_and_full_astern_to_full_ahead(self, vessel, helm_steering):
        """PWM 1000 to 2000 is scaled to 0 to 1, shifted by the offset and multiplied; above 1500 the helm angle is positive, to starboard."""
        vessel = steered(vessel, helm_steering)
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        channels = self.channels(vessel)

        def command(control: ET.Element, pwm: float) -> float:
            return ((pwm - 1000.0) / 1000.0 + child_float(control, "offset")) * child_float(control, "multiplier")

        assert command(channels[0], 2000) == pytest.approx(dynamics.steering_max_angle, rel=1e-5)
        assert command(channels[0], 1000) == pytest.approx(-dynamics.steering_max_angle, rel=1e-5)
        assert command(channels[0], 1500) == 0.0
        assert command(channels[2], 2000) == pytest.approx(dynamics.max_thrust, rel=1e-5)
        assert command(channels[2], 1000) == pytest.approx(-dynamics.max_thrust, rel=1e-5)

    def test_the_lockstep_port_follows_the_vessel_id(self, steering):
        for vessel_id in (0, 2, 7):
            (plugin,) = plugins(model(steered(make_vessel(vessel_id, True), steering), ControlLayerId.ARDUPILOT), "ArduPilotPlugin")
            assert child_float(plugin, "fdm_port_in") == 9000 + vessel_id * 10 + 2
            assert child_text(plugin, "lock_step") == "1" and child_text(plugin, "imuName") == "imu_sensor"


class TestHydrodynamics:
    def test_the_hull_carries_the_dynamics_coefficients(self, vessel, steering, control_layer):
        vessel = steered(vessel, steering)
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        hull = plugin_for(model(vessel, control_layer, overrides={}), HYDRODYNAMICS_SYSTEM, "link_name", "base_link")
        for name in HYDRODYNAMIC_COEFFICIENTS:
            assert child_float(hull, name) == sdf_value(getattr(dynamics, name)), name
            assert child_float(hull, name) < 0, name
        assert sorted(child_tags(hull)) == sorted(HYDRODYNAMIC_COEFFICIENTS + ("link_name", "disable_coriolis"))
        assert child_text(hull, "disable_coriolis") == "true"

    def test_the_values_written_keep_six_significant_digits(self, vessel, steering):
        vessel = steered(vessel, steering)
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        hull = plugin_for(model(vessel, overrides={}), HYDRODYNAMICS_SYSTEM, "link_name", "base_link")
        for name in HYDRODYNAMIC_COEFFICIENTS:
            assert child_float(hull, name) == pytest.approx(getattr(dynamics, name), rel=5e-6)
            assert "e" not in child_text(hull, name).lower(), "plain decimals"


class TestBuoyancy:
    def test_flat_water_has_nine_stations_of_three_cells(self, vessel, steering):
        vessel = steered(vessel, steering)
        assert buoyancy_cells(derive_vessel_dynamics(vessel, 0.0, {})) == (HULL_STATIONS, BUOYANCY_GRID) == (9, 3)
        collisions = hull_collisions(model(vessel))
        assert [collision.get("name") for collision in collisions] == [f"collision_hull_{i}_{j}" for i in range(9) for j in range(3)]
        assert len(list(model(vessel).iter("collision"))) == 27, "nothing else is buoyant"

    def test_the_boxes_add_up_to_the_displaced_volume_below_the_waterline(self, vessel, steering):
        vessel = steered(vessel, steering)
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        sizes = [child_floats(collision, "geometry/box/size") for collision in hull_collisions(model(vessel, overrides={}))]
        assert sum(length * breadth * height / 2 for length, breadth, height in sizes) == pytest.approx(dynamics.displaced_volume, rel=1e-5)
        assert sum(length * breadth * height / 2 for length, breadth, height in sizes) == pytest.approx(0.6 * vessel.length * vessel.breadth * vessel.draft, rel=1e-5)
        assert 1025.0 * sum(length * breadth * height / 2 for length, breadth, height in sizes) == pytest.approx(dynamics.total_mass, rel=1e-5)

    def test_the_boxes_have_the_hulls_waterplane_area(self, vessel):
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        sizes = [child_floats(collision, "geometry/box/size") for collision in hull_collisions(model(vessel, overrides={}))]
        assert sum(length * breadth for length, breadth, _ in sizes) == pytest.approx(dynamics.waterplane_area, rel=1e-5)

    def test_every_box_is_centered_on_the_waterline(self, vessel, steering):
        """Replaces the one box centered on the waterline: each reaches as far above it as its part of the hull lies below."""
        vessel = steered(vessel, steering)
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        for collision in hull_collisions(model(vessel, overrides={})):
            station = dynamics.stations[int(collision.get("name").split("_")[2])]
            pose = child_floats(collision, "pose")
            assert pose[2:] == (0.0, 0.0, 0.0, 0.0)
            assert child_floats(collision, "geometry/box/size")[2] == sdf_value(2 * station.depth)
            assert child_floats(collision, "geometry/box/size")[2] / 2 <= vessel.draft

    def test_the_cells_of_a_station_tile_its_breadth(self, vessel):
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        collisions = hull_collisions(model(vessel, overrides={}))
        for index, station in enumerate(dynamics.stations):
            cells = collisions[3 * index : 3 * index + 3]
            poses = [child_floats(cell, "pose") for cell in cells]
            sizes = [child_floats(cell, "geometry/box/size") for cell in cells]
            assert [pose[0] for pose in poses] == [sdf_value(station.x)] * 3
            assert [size[0] for size in sizes] == [sdf_value(station.length)] * 3
            assert [size[1] for size in sizes] == [sdf_value(station.breadth / 3)] * 3
            assert [pose[1] for pose in poses] == [sdf_value(-station.breadth / 3), 0.0, sdf_value(station.breadth / 3)]

    def test_the_boxes_run_from_the_stern_to_the_stem_with_a_finer_bow(self, vessel):
        """The hull's midship lies hull_x ahead of the model's origin, so its ends do too."""
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        collisions = hull_collisions(model(vessel, overrides={}))
        centerline = [collision for collision in collisions if collision.get("name").endswith("_1")]
        positions = [child_floats(collision, "pose")[0] for collision in centerline]
        lengths = [child_floats(collision, "geometry/box/size")[0] for collision in centerline]
        breadths = [child_floats(collision, "geometry/box/size")[1] for collision in centerline]
        assert positions == sorted(positions)
        assert positions == [sdf_value(station.x) for station in dynamics.stations]
        assert [later - earlier for earlier, later in zip(positions, positions[1:])] == pytest.approx([vessel.length / 9] * 8, rel=1e-4)
        assert positions[0] - lengths[0] / 2 == pytest.approx(-vessel.length / 2 + dynamics.hull_x, rel=1e-5), "the stern"
        assert positions[-1] + lengths[-1] / 2 == pytest.approx(vessel.length / 2 + dynamics.hull_x, rel=1e-5), "the stem"
        assert positions[4] == pytest.approx(dynamics.hull_x, rel=1e-5), "the middle box is amidships, ahead of the origin"
        assert breadths[-1] < breadths[0] < breadths[4], "bow, stern, midship"

    def test_the_center_of_buoyancy_of_the_boxes_is_at_the_models_origin(self, steering):
        """Under the hull link's center of mass, for every steering type and size, so the model floats on an even keel.

        The model carries six significant digits, which leaves the center within a ten thousandth of the length.
        """
        for scale in SCALES:
            ship = scaled_vessel(scale, steering)
            root = model(ship, overrides={})
            along, across = center_of_buoyancy(root)
            assert along == pytest.approx(0.0, abs=1e-4 * ship.length), scale
            assert across == pytest.approx(0.0, abs=1e-9), scale
            assert child_floats(link(root, "base_link"), "inertial/pose")[:2] == (0.0, 0.0), "the hull's center of mass is over the origin too"

    def test_without_the_hull_offset_the_boxes_would_be_out_of_balance(self, vessel):
        """What the offset is for: the hull's own center of buoyancy lies aft of its midship."""
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        along, _ = center_of_buoyancy(model(vessel, overrides={}))
        assert along + (-dynamics.hull_x) < -0.01 * vessel.length

    def test_buoyancy_stations_are_the_dynamics_own_in_flat_water(self, vessel):
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        assert buoyancy_stations(dynamics) is dynamics.stations

    def test_under_waves_a_cell_is_at_most_an_eighth_of_the_wavelength(self):
        ship = scaled_vessel("100m")
        dynamics = derive_vessel_dynamics(ship, 0.0, {})
        along, across = buoyancy_cells(dynamics, waves_environment(5.0).wave)
        cell = deep_water_wavelength(5.0) / 8
        assert dynamics.length / along <= cell < dynamics.length / (along - 1)
        assert along > HULL_STATIONS
        assert across == max(3, int(np.ceil(dynamics.breadth / cell)))

    def test_the_cells_are_capped(self):
        ship = scaled_vessel("100m")
        along, _ = buoyancy_cells(derive_vessel_dynamics(ship, 0.0, {}), waves_environment(3.0).wave)
        assert along == MAX_WAVE_CELLS

    def test_long_waves_keep_the_cells_of_flat_water(self):
        small = scaled_vessel("5m")
        assert buoyancy_cells(derive_vessel_dynamics(small, 0.0, {}), waves_environment(8.0).wave) == (HULL_STATIONS, BUOYANCY_GRID)

    def test_under_waves_the_same_hull_is_cut_finer(self):
        ship = scaled_vessel("100m")
        dynamics = derive_vessel_dynamics(ship, 0.0, {})
        wave = waves_environment(5.0).wave
        along, _ = buoyancy_cells(dynamics, wave)
        stations = buoyancy_stations(dynamics, wave)
        assert stations == hull_stations(dynamics.hull, along)[0] and len(stations) == along
        own = dynamics.hull.stations(along)
        assert [(station.length, station.breadth, station.depth) for station in stations] == [(station.length, station.breadth, station.depth) for station in own]
        assert sum(station.volume for station in stations) == pytest.approx(dynamics.displaced_volume, rel=1e-12)
        assert sum(station.waterplane_area for station in stations) == pytest.approx(dynamics.waterplane_area, rel=1e-12)

    def test_the_finer_cut_under_waves_is_balanced_too(self):
        """It is placed by its own center of buoyancy, which lies within a thousandth of the length of the flat water one."""
        ship = scaled_vessel("100m")
        dynamics = derive_vessel_dynamics(ship, 0.0, {})
        wave = waves_environment(5.0).wave
        stations = buoyancy_stations(dynamics, wave)
        assert sum(station.volume * station.x for station in stations) / dynamics.displaced_volume == pytest.approx(0.0, abs=1e-9 * ship.length)
        offset = stations[0].x - dynamics.hull.stations(len(stations))[0].x
        assert offset == pytest.approx(dynamics.hull_x, abs=1e-3 * ship.length)
        assert offset > 0

    def test_the_boxes_of_a_model_under_waves_have_their_center_of_buoyancy_at_the_origin(self, steering):
        ship = scaled_vessel("100m", steering)
        along, across = center_of_buoyancy(model(ship, environment=waves_environment(), overrides={}))
        assert along == pytest.approx(0.0, abs=1e-4 * ship.length)
        assert across == pytest.approx(0.0, abs=1e-9)

    def test_the_wavelength_follows_the_period_in_deep_water(self):
        assert deep_water_wavelength(5.0) == pytest.approx(39.03, abs=0.01)


class TestHullVisual:
    def test_the_hull_shows_the_mesh_next_to_the_model(self, vessel, steering, control_layer):
        root = model(steered(vessel, steering), control_layer, agent_name="unit_7")
        base = link(root, "base_link")
        (visual,) = [visual for visual in base.iter("visual")]
        assert visual.get("name") == "visual_hull"
        assert child_text(visual, "geometry/mesh/uri") == hull_mesh_filename("unit_7") == "unit_7_hull.stl"
        assert visual.find("geometry/box") is None

    def test_the_hull_mesh_is_the_stl_of_the_same_hull(self, vessel, steering):
        vessel = steered(vessel, steering)
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        text = generate_hull_mesh(vessel, "unit_7", overrides={})
        assert text == dynamics.hull.mesh(dynamics.height).moved(dynamics.hull_x).to_stl("unit_7_hull"), "in the model's frame, where the buoyant boxes are"
        assert text != dynamics.hull.mesh(dynamics.height).to_stl("unit_7_hull"), "not in the hull's own frame, origin amidships"
        assert text.startswith("solid unit_7_hull\n") and text.endswith("endsolid unit_7_hull\n")
        assert dynamics.hull == HullForm.from_dimensions(vessel.length, vessel.breadth, vessel.draft, vessel.block_coefficient), "the hull the buoyant boxes are cut from"

    def test_the_mesh_spans_the_hull_from_keel_to_deck(self, vessel):
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        xs, ys, zs = zip(*stl_vertices(generate_hull_mesh(vessel, "boat", overrides={})))
        assert (min(xs), max(xs)) == pytest.approx((-vessel.length / 2 + dynamics.hull_x, vessel.length / 2 + dynamics.hull_x), rel=1e-5), "the hull's midship is hull_x ahead of the origin"
        assert max(xs) - min(xs) == pytest.approx(vessel.length, rel=1e-5)
        assert max(ys) == pytest.approx(-min(ys)) and max(ys) <= vessel.breadth / 2
        assert (min(zs), max(zs)) == pytest.approx((-vessel.draft, vessel.height - vessel.draft)), "the model's origin is at the waterline"

    def test_the_mesh_lies_where_the_buoyant_boxes_are(self, vessel, steering):
        """Stern and stem of the surface the model shows are the ends of the boxes it floats on."""
        vessel = steered(vessel, steering)
        xs = [vertex[0] for vertex in stl_vertices(generate_hull_mesh(vessel, "boat", overrides={}))]
        boxes = [(child_floats(collision, "pose")[0], child_floats(collision, "geometry/box/size")[0]) for collision in hull_collisions(model(vessel, overrides={}))]
        assert min(xs) == pytest.approx(min(x - length / 2 for x, length in boxes), rel=1e-4)
        assert max(xs) == pytest.approx(max(x + length / 2 for x, length in boxes), rel=1e-4)

    def test_the_mesh_does_not_depend_on_the_steering_type(self, vessel):
        meshes = {generate_hull_mesh(steered(vessel, steering_type), "boat", overrides={}) for steering_type in STEERING_TYPES}
        assert len(meshes) == 1

    def test_the_mesh_follows_the_block_coefficient(self, vessel):
        base = generate_hull_mesh(vessel, "boat", overrides={})
        assert generate_hull_mesh(dataclasses.replace(vessel, _block_coefficient=0.8), "boat", overrides={}) != base
        assert generate_hull_mesh(vessel, "boat", overrides={"block_coefficient": 0.8}) == generate_hull_mesh(dataclasses.replace(vessel, _block_coefficient=0.8), "boat", overrides={})

    def test_the_shipped_override_files_apply_to_the_mesh_when_none_are_given(self, vessel, monkeypatch):
        monkeypatch.setattr(vessel_model_generator, "load_vessel_dynamics_overrides", lambda: VesselDynamicsOverrides(by_vessel_id={2: {"block_coefficient": 0.8}}))
        assert generate_hull_mesh(vessel, "boat") == generate_hull_mesh(vessel, "boat", overrides={"block_coefficient": 0.8})

    def test_unknown_override_keys_fail_the_mesh(self, vessel):
        with pytest.raises(ValueError, match="unknown vessel dynamics keys"):
            generate_hull_mesh(vessel, "boat", overrides={"nonsense": 1.0})


class TestEnvironment:
    def test_windage_follows_the_requested_wind_speed(self, vessel):
        calm = windage_mass(generate_vessel_model(vessel, "boat", environment=EnvironmentConfig.calm()))
        windy = windage_mass(generate_vessel_model(vessel, "boat", environment=wind_environment(0.0, 8.0)))
        assert windy == pytest.approx(calm * 8.0, rel=1e-3)

    def test_without_an_environment_the_windage_uses_the_reference_speed(self, vessel):
        assert windage_mass(generate_vessel_model(vessel, "boat")) == windage_mass(generate_vessel_model(vessel, "boat", environment=EnvironmentConfig.calm()))

    def test_waves_do_not_change_the_model_while_wave_forces_are_unavailable(self, vessel, monkeypatch):
        monkeypatch.setattr(gazebo_specs, "GAZEBO_WAVE_FORCES_AVAILABLE", False)
        environment = waves_environment()
        assert generate_vessel_model(vessel, "boat", environment=environment) == generate_vessel_model(vessel, "boat")
        assert "gz-waves1" not in generate_vessel_model(vessel, "boat", environment=environment)

    def test_waves_give_the_hull_the_wave_aware_buoyancy_on_finer_cells(self, steering):
        ship = scaled_vessel("100m", steering)
        root = model(ship, environment=waves_environment())
        (waves,) = plugins(root, "gz-waves1-hydrodynamics-system")
        assert child_text(waves, "enable") == "boat::base_link"
        dynamics = derive_vessel_dynamics(ship, 0.0, {})
        along, across = buoyancy_cells(dynamics, waves_environment().wave)
        assert len(hull_collisions(root)) == along * across
        assert along > HULL_STATIONS and across > BUOYANCY_GRID, "a 100 m hull in 5 s (39 m) waves needs more than the cells of flat water"

    def test_the_finer_cells_still_displace_the_hulls_volume(self):
        ship = scaled_vessel("100m")
        dynamics = derive_vessel_dynamics(ship, 0.0, {})
        sizes = [child_floats(collision, "geometry/box/size") for collision in hull_collisions(model(ship, environment=waves_environment(), overrides={}))]
        assert sum(length * breadth * height / 2 for length, breadth, height in sizes) == pytest.approx(dynamics.displaced_volume, rel=1e-5)
        assert sum(length * breadth for length, breadth, _ in sizes) == pytest.approx(dynamics.waterplane_area, rel=1e-5)

    def test_flat_water_has_no_wave_aware_buoyancy(self, vessel, steering):
        assert plugins(model(steered(vessel, steering), environment=EnvironmentConfig.calm()), "gz-waves1-hydrodynamics-system") == []


class TestOverrides:
    def test_explicit_overrides_replace_the_shipped_ones(self, vessel):
        text = generate_vessel_model(vessel, "boat", overrides={"max_thrust": 4321.0})
        limits = [child_float(plugin, "max_thrust_cmd") for plugin in plugins(parse_sdf(text), THRUSTER_SYSTEM)]
        assert limits == [4321.0, 4321.0]

    def test_overrides_reach_the_steering_gear(self, vessel):
        root = model(steered(vessel, "rudder"), overrides={"rudder_max_angle_deg": 20.0, "steering_rate": 0.25, "rudder_lift_slope": 3.0})
        assert child_float(joint(root, STEERING_JOINT), "axis/limit/upper") == pytest.approx(math.radians(20.0) + STEERING_STOP_MARGIN, rel=1e-5)
        assert child_float(joint(root, STEERING_JOINT), "axis/limit/lower") == pytest.approx(-math.radians(20.0) - STEERING_STOP_MARGIN, rel=1e-5)
        assert child_float(plugins(root, HELM_CONTROLLER)[0], "cmd_max") == 0.25
        dynamics = derive_vessel_dynamics(steered(vessel, "rudder"), 0.0, {})
        assert child_float(plugin_for(root, HYDRODYNAMICS_SYSTEM, "link_name", STEERING_LINK), "yVabsU") == sdf_value(-0.5 * 1025.0 * dynamics.rudder_area * 3.0)

    def test_unknown_override_keys_fail_the_generation(self, vessel):
        with pytest.raises(ValueError, match="unknown vessel dynamics keys"):
            generate_vessel_model(vessel, "boat", overrides={"nonsense": 1.0})

    def test_the_shipped_override_files_apply_when_none_are_given(self, vessel, monkeypatch):
        monkeypatch.setattr(vessel_model_generator, "load_vessel_dynamics_overrides", lambda: VesselDynamicsOverrides(by_vessel_id={2: {"max_thrust": 777.0}}))
        text = generate_vessel_model(vessel, "boat")
        assert child_float(plugins(parse_sdf(text), THRUSTER_SYSTEM)[0], "max_thrust_cmd") == 777.0

    def test_render_writes_the_dynamics_it_is_given(self, vessel, steering, control_layer):
        vessel = steered(vessel, steering)
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        assert render_vessel_model(dynamics, "boat", 2, control_layer) == generate_vessel_model(vessel, "boat", control_layer, overrides={})


class TestShippedVesselTypes:
    @pytest.mark.parametrize("type_name", sorted(name for name in VesselTypeMap() if name is not None))
    def test_a_vessel_of_every_shipped_type_gets_a_model_of_its_steering_type(self, type_name, control_layer):
        vessel_type = VesselTypeMap()[type_name]
        vessel = vessel_of_type(vessel_type, float(vessel_type.min_length))
        root = model(vessel, control_layer)
        thrusters = [child_text(system, "joint_name") for system in plugins(root, THRUSTER_SYSTEM)]
        assert thrusters == [f"motor_{name}_joint" for name in thruster_names(vessel_type.steering_type)]
        assert (STEERING_JOINT in names(root, "joint")) == (vessel_type.steering_type != "skid")
        assert len(plugins(root, HYDRODYNAMICS_SYSTEM)) == (2 if vessel_type.steering_type == "rudder" else 1)
