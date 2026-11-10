"""UsvNavigationParameters.from_reference: how SceneGEMS derives the runtime configuration from a scenario."""

import math

import pytest

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor
from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_parameters import (
    DEFAULT_CONTROL_HORIZON_STEPS,
    DEFAULT_PRESCRIBED_TIME_S,
    UPSTREAM_DCPA_BETA1_M,
    UPSTREAM_DCPA_BETA2_M,
    UsvNavigationParameters,
)
from tests.scenegems_tool.vessel_stack.scenarios import SPEED, encounter_trajectories, make_vessel
from utils.global_constants import VISIBILITY_DIST_3, VISIBILITY_DIST_5, VISIBILITY_DIST_6

STATES = [ActorState(0.0, 0.0, SPEED, 0.0), ActorState(8.0, 0.0, SPEED, 0.0)]


@pytest.fixture
def head_on():
    trajectories = encounter_trajectories("head_on", 100)
    own = trajectories.initial_scene.os
    return trajectories, own


def test_goal_is_the_end_of_the_generated_trajectory(head_on):
    trajectories, own = head_on
    parameters = UsvNavigationParameters.from_reference(own, trajectories.state_list(own), trajectories.initial_scene.actors, 1.0)
    assert parameters.goal == (pytest.approx(100 * SPEED), 0.0)


def test_speed_is_the_initial_reference_speed(head_on):
    trajectories, own = head_on
    parameters = UsvNavigationParameters.from_reference(own, trajectories.state_list(own), trajectories.initial_scene.actors, 1.0)
    assert parameters.speed == SPEED


def test_speed_is_capped_at_the_vessel_maximum():
    own = make_vessel(0, True, max_speed=5.0)
    states = [ActorState(0.0, 0.0, 9.0, 0.0), ActorState(9.0, 0.0, 9.0, 0.0)]
    parameters = UsvNavigationParameters.from_reference(own, states, [own], 1.0)
    assert parameters.speed == 5.0


def test_speed_falls_back_to_the_mean_when_the_vessel_starts_at_rest():
    own = make_vessel(0, True)
    states = [ActorState(0.0, 0.0, 0.0, 0.0), ActorState(4.0, 0.0, 4.0, 0.0), ActorState(8.0, 0.0, 8.0, 0.0)]
    parameters = UsvNavigationParameters.from_reference(own, states, [own], 1.0)
    assert parameters.speed == pytest.approx(4.0)


def test_a_vessel_that_never_moves_is_rejected():
    own = make_vessel(0, True)
    with pytest.raises(ValueError, match="no positive reference speed"):
        UsvNavigationParameters.from_reference(own, [ActorState(0.0, 0.0, 0.0, 0.0)], [own], 1.0)


def test_an_empty_reference_is_rejected():
    own = make_vessel(0, True)
    with pytest.raises(ValueError, match="empty reference trajectory"):
        UsvNavigationParameters.from_reference(own, [], [own], 1.0)


def test_safety_radius_is_the_largest_in_the_scene():
    own = make_vessel(0, True, length=30.0)
    large = make_vessel(1, False, length=100.0)
    states = [ActorState(0.0, 0.0, SPEED, 0.0), ActorState(8.0, 0.0, SPEED, 0.0)]
    parameters = UsvNavigationParameters.from_reference(own, states, [own, large], 1.0)
    assert parameters.safety_radius == large.safety_radius == 400.0


def test_control_horizon_is_the_sixty_steps_when_the_vessel_turns_fast():
    own = make_vessel(0, True, max_angular_speed=1.0)
    states = [ActorState(0.0, 0.0, SPEED, 0.0), ActorState(8.0, 0.0, SPEED, 0.0)]
    parameters = UsvNavigationParameters.from_reference(own, states, [own], 2.0)
    assert parameters.control_horizon == DEFAULT_CONTROL_HORIZON_STEPS * 2.0


def test_control_horizon_covers_a_full_turn_of_a_slow_turning_vessel():
    own = make_vessel(0, True, max_angular_speed=0.05)
    states = [ActorState(0.0, 0.0, SPEED, 0.0), ActorState(8.0, 0.0, SPEED, 0.0)]
    parameters = UsvNavigationParameters.from_reference(own, states, [own], 1.0)
    assert parameters.control_horizon == pytest.approx(2 * math.pi / 0.05)


def test_prescribed_time_is_the_upstream_default(head_on):
    trajectories, own = head_on
    parameters = UsvNavigationParameters.from_reference(own, trajectories.state_list(own), trajectories.initial_scene.actors, 1.0)
    assert parameters.prescribed_time == DEFAULT_PRESCRIBED_TIME_S == 3.0


def test_horizon_is_the_visibility_between_the_vessel_and_the_other_actor():
    own = make_vessel(0, True, length=30.0)
    other = make_vessel(1, False, length=100.0)
    assert UsvNavigationParameters.from_reference(own, STATES, [own, other], 1.0).horizon == VISIBILITY_DIST_6, "the more visible vessel sets the distance of the pair"
    assert UsvNavigationParameters.from_reference(other, STATES, [own, other], 1.0).horizon == VISIBILITY_DIST_6, "the pair has one distance, whichever vessel asks"


def test_horizon_is_the_largest_visibility_of_several_actors():
    own = make_vessel(0, True, length=15.0)
    seen_from_near = make_vessel(1, False, length=10.0)
    seen_from_far = make_vessel(2, False, length=30.0)
    assert UsvNavigationParameters.from_reference(own, STATES, [own, seen_from_near], 1.0).horizon == VISIBILITY_DIST_3
    assert UsvNavigationParameters.from_reference(own, STATES, [own, seen_from_near, seen_from_far], 1.0).horizon == VISIBILITY_DIST_5


def test_a_static_obstacle_does_not_extend_the_horizon():
    own = make_vessel(0, True, length=100.0)
    obstacle = ConcreteActor.from_dict({"id": 1, "type": "SmallIsland", "length": 30.0, "safety_radius": 30.0, "is_vessel": False})
    assert UsvNavigationParameters.from_reference(own, STATES, [own, obstacle], 1.0).horizon == VISIBILITY_DIST_5


def test_a_vessel_alone_has_no_horizon():
    own = make_vessel(0, True)
    parameters = UsvNavigationParameters.from_reference(own, STATES, [own], 1.0)
    assert parameters.horizon is None
    assert "horizon" not in parameters.as_dict()


def test_dcpa_bounds_stay_upstream_for_a_small_safety_radius():
    own = make_vessel(0, True, length=30.0)
    parameters = UsvNavigationParameters.from_reference(own, STATES, [own], 1.0)
    assert dict(parameters.runtime_options) == {"dcpa_beta1": UPSTREAM_DCPA_BETA1_M, "dcpa_beta2": UPSTREAM_DCPA_BETA2_M}


def test_dcpa_bounds_grow_with_a_large_safety_radius():
    own = make_vessel(0, True, length=300.0)
    parameters = UsvNavigationParameters.from_reference(own, STATES, [own], 1.0)
    assert parameters.safety_radius == 1200.0
    assert dict(parameters.runtime_options) == {"dcpa_beta1": 1500.0, "dcpa_beta2": 3000.0}


def test_runtime_kwargs_and_as_dict(head_on):
    trajectories, own = head_on
    parameters = UsvNavigationParameters.from_reference(own, trajectories.state_list(own), trajectories.initial_scene.actors, 1.0)
    kwargs = parameters.runtime_kwargs()
    assert set(kwargs) == {"Cs", "v", "tp", "tp_control", "dcpa_beta1", "dcpa_beta2"}, "the horizon is no argument of the runtime"
    assert kwargs["Cs"] == 120.0
    assert parameters.as_dict() == {"goal": list(parameters.goal), **kwargs, "horizon": VISIBILITY_DIST_5}


def test_runtime_options_extend_the_kwargs():
    parameters = UsvNavigationParameters(goal=(1.0, 2.0), speed=3.0, safety_radius=4.0, control_horizon=5.0, runtime_options=(("K", 0.4),))
    assert parameters.runtime_kwargs()["K"] == 0.4
