"""USV Navigation at the SceneGEMS defaults against the default safety domains: neither vessel may enter the other's.

The kinematic runs below hold that requirement. The cases marked xfail are the ones the defaults do
not meet yet: upstream gives no clearance guarantee, it only looks for a virtual waypoint ahead, and
replay targets do not react, so parameters alone cannot close them. They are strict, so a change that
closes one fails here and the mark goes.
"""

import dataclasses
import math

import pytest

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_parameters import UsvNavigationParameters
from scenegems_tool.vessel_stack.calibration.reference_scenarios import ENCOUNTER_TARGETS, VESSEL_SCALES, make_vessel, scaled_vessel
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import KinematicRunResult, run_kinematic_closed_loop
from utils.global_constants import VISIBILITY_DIST_6

STEPS = 1400
LARGE_HULL_YAW_RATE = 0.008  # rad/s, as the 100 m reference hull
OVERTAKING_SPEED_RATIO = 3.0 / 8.0  # the slower target's speed in the reference overtaking


def encounter(name: str, own_scale: str, target_scale: str) -> Trajectories:
    """A reference encounter between two reference hulls, both at the own ship's cruise speed unless the target is the one being overtaken."""
    speed = VESSEL_SCALES[own_scale].cruise_speed
    target = ENCOUNTER_TARGETS[name]
    target_speed = speed * OVERTAKING_SPEED_RATIO if name == "overtaking" else speed
    states = {scaled_vessel(own_scale, 0, True): ActorState(0.0, 0.0, speed, 0.0), scaled_vessel(target_scale, 1, False): ActorState(target.x, target.y, target_speed, target.heading)}
    return TrajectoryBuilder.default_trajectory_from_scene(ConcreteScene(states), 1, STEPS)


def offset_head_on(hull: float, offset_radii: float) -> Trajectories:
    """Reciprocal courses whose straight tracks pass inside the domain, offset_radii of the safety radius apart."""
    own = make_vessel(0, True, length=hull, max_angular_speed=LARGE_HULL_YAW_RATE)
    target = make_vessel(1, False, length=hull, max_angular_speed=LARGE_HULL_YAW_RATE)
    states = {own: ActorState(0.0, 0.0, 8.0, 0.0), target: ActorState(8000.0, offset_radii * own.safety_radius, 8.0, math.pi)}
    return TrajectoryBuilder.default_trajectory_from_scene(ConcreteScene(states), 1, 1200)


def overtaken_from_the_quarter() -> Trajectories:
    """A faster target on a collision course from astern, 30 degrees off the own ship's course, which is not ahead for the own ship to steer around."""
    course = math.radians(30.0)
    speed = 12.0
    cpa_time = 300
    start_x = 8.0 * cpa_time - speed * math.cos(course) * cpa_time
    start_y = -speed * math.sin(course) * cpa_time
    states = {make_vessel(0, True): ActorState(0.0, 0.0, 8.0, 0.0), make_vessel(1, False): ActorState(start_x, start_y, speed, course)}
    return TrajectoryBuilder.default_trajectory_from_scene(ConcreteScene(states), 1, 2 * cpa_time + 200)


def steps_inside_a_domain(result: KinematicRunResult) -> int:
    """Steps at which either vessel is inside the other's default safety domain."""
    first, second = result.actors
    return sum(
        first.get_default_safety_domain(first_state).contains_point(second_state.p) or second.get_default_safety_domain(second_state).contains_point(first_state.p)
        for first_state, second_state in result.states
    )


@pytest.mark.parametrize(
    "name, own_scale, target_scale",
    [
        ("head_on", "5m", "5m"),
        ("head_on", "30m", "30m"),
        ("head_on", "100m", "100m"),
        ("head_on", "30m", "100m"),
        ("head_on", "100m", "30m"),
        ("crossing_from_starboard", "30m", "30m"),
        ("crossing_from_port", "30m", "30m"),
        ("crossing_from_starboard", "100m", "100m"),
        ("overtaking", "5m", "5m"),
        ("overtaking", "30m", "30m"),
        ("overtaking", "100m", "100m"),
        ("overtaking", "30m", "100m"),
        pytest.param("head_on", "5m", "100m", marks=pytest.mark.xfail(strict=True, reason="avoidance starts too late for a slow own ship to clear the large target's radius")),
        pytest.param("overtaking", "5m", "100m", marks=pytest.mark.xfail(strict=True, reason="avoidance starts too late for a slow own ship to clear the large target's radius")),
    ],
)
def test_reference_encounters_keep_both_domains(name, own_scale, target_scale):
    assert steps_inside_a_domain(run_kinematic_closed_loop(encounter(name, own_scale, target_scale))) == 0


@pytest.mark.parametrize(
    "hull, offset_radii",
    [
        (30, 0.5),
        (30, 0.9),
        (100, 0.5),
        (100, 0.9),
        (300, 0.5),
        (300, 0.9),
        (400, 0.9),
        pytest.param(
            400,
            0.5,
            marks=pytest.mark.xfail(
                strict=True, reason="the unsafe set inflated by 1.25 reaches the own ship, so the waypoint lies close by and is reached after 29 s, then the ship steers back to its goal"
            ),
        ),
    ],
)
def test_a_pass_inside_the_domain_is_answered_at_every_hull_size(hull, offset_radii):
    result = run_kinematic_closed_loop(offset_head_on(hull, offset_radii))
    assert result.run_record["usv_navigation"]["transitions"], "upstream's fixed risk bounds never started avoidance above a hull of about 232 m"
    assert steps_inside_a_domain(result) == 0


@pytest.mark.xfail(strict=True, reason="the target is faster and does not give way, and upstream looks for a waypoint only ahead, where the target catches up with the own ship")
def test_being_overtaken_from_the_quarter_keeps_both_domains():
    assert steps_inside_a_domain(run_kinematic_closed_loop(overtaken_from_the_quarter())) == 0


def small_own_ship_against_a_large_target() -> Trajectories:
    own = make_vessel(0, True, length=2.0, max_speed=4.0, max_angular_speed=0.5)
    target = make_vessel(1, False, length=100.0, max_angular_speed=LARGE_HULL_YAW_RATE)
    return TrajectoryBuilder.default_trajectory_from_scene(ConcreteScene({own: ActorState(0.0, 0.0, 3.0, 0.0), target: ActorState(6000.0, 0.0, 3.0, math.pi)}), 1, STEPS)


def test_a_small_own_ship_has_the_horizon_of_the_large_target_it_meets():
    """The pair is in sight once either vessel sees the other, so the large target's range counts and not the 370 m the small hull is seen from."""
    trajectories = small_own_ship_against_a_large_target()
    own = trajectories.initial_scene.os
    parameters = UsvNavigationParameters.from_reference(own, trajectories.state_list(own), trajectories.initial_scene.actors, 1.0)
    assert parameters.horizon == VISIBILITY_DIST_6 > parameters.safety_radius


@pytest.mark.xfail(strict=True, reason="the target is in view from the start, but avoidance starts too late for a slow own ship to clear the large target's radius")
def test_a_small_own_ship_keeps_the_domain_of_a_large_target():
    assert steps_inside_a_domain(run_kinematic_closed_loop(small_own_ship_against_a_large_target())) == 0


def test_a_target_beyond_the_horizon_is_not_answered():
    trajectories = encounter("head_on", "30m", "30m")
    own = trajectories.initial_scene.os
    parameters = UsvNavigationParameters.from_reference(own, trajectories.state_list(own), trajectories.initial_scene.actors, 1.0)
    unlimited = run_kinematic_closed_loop(trajectories, usv_navigation_parameters=dataclasses.replace(parameters, horizon=None))
    limited = run_kinematic_closed_loop(trajectories, usv_navigation_parameters=dataclasses.replace(parameters, horizon=2000.0))
    assert unlimited.run_record["usv_navigation"]["transitions"][0][0] == 154.0, "the risk index alone starts avoidance at about 3.5 km"
    assert limited.run_record["usv_navigation"]["transitions"][0][0] >= (6000.0 - 2000.0) / 16.0, "the ships close at 16 m/s from 6 km"
