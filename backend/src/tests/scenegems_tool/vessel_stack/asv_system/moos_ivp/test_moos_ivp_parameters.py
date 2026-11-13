"""MoosIvpParameters.from_reference: how SceneGEMS derives the helm's configuration from a scenario."""

import pytest

from concrete_level.models.actor_state import ActorState
from scenegems_tool.vessel_stack.asv_system.moos_ivp.moos_ivp_parameters import MoosIvpParameters, parameters_for
from tests.scenegems_tool.vessel_stack.scenarios import SPEED, encounter_trajectories, make_vessel
from utils.colregs_approximations import vis_distance


@pytest.fixture
def head_on():
    trajectories = encounter_trajectories("head_on", 100)
    return trajectories, trajectories.initial_scene.os


def defaults(trajectories, own, dt: float = 1.0) -> MoosIvpParameters:
    return MoosIvpParameters.from_reference(own, trajectories.state_list(own), trajectories.initial_scene.actors, dt)


def test_goal_and_speed_come_from_the_generated_trajectory(head_on):
    parameters = defaults(*head_on)
    assert parameters.goal == (pytest.approx(100 * SPEED), 0.0)
    assert parameters.speed == SPEED
    assert parameters.max_speed == head_on[1].max_speed


def test_speed_is_capped_at_the_vessel_maximum():
    own = make_vessel(0, True, max_speed=5.0)
    states = [ActorState(0.0, 0.0, 9.0, 0.0), ActorState(9.0, 0.0, 9.0, 0.0)]
    assert MoosIvpParameters.from_reference(own, states, [own], 1.0).speed == 5.0


def test_speed_falls_back_to_the_mean_when_the_vessel_starts_at_rest():
    own = make_vessel(0, True)
    states = [ActorState(0.0, 0.0, 0.0, 0.0), ActorState(4.0, 0.0, 4.0, 0.0), ActorState(8.0, 0.0, 8.0, 0.0)]
    assert MoosIvpParameters.from_reference(own, states, [own], 1.0).speed == pytest.approx(4.0)


def test_a_vessel_that_never_moves_is_rejected():
    own = make_vessel(0, True)
    with pytest.raises(ValueError, match="no positive reference speed"):
        MoosIvpParameters.from_reference(own, [ActorState(0.0, 0.0, 0.0, 0.0)], [own], 1.0)
    with pytest.raises(ValueError, match="empty reference trajectory"):
        MoosIvpParameters.from_reference(own, [], [own], 1.0)


def test_a_closest_approach_inside_the_largest_safety_radius_has_no_utility():
    """Neither vessel's domain may be entered, so the helm avoids every closest point of approach within the larger of the two."""
    own, target = make_vessel(0, True, length=30.0), make_vessel(1, False, length=100.0)
    states = [ActorState(0.0, 0.0, SPEED, 0.0), ActorState(8.0, 0.0, SPEED, 0.0)]
    parameters = MoosIvpParameters.from_reference(own, states, [own, target], 1.0)
    assert parameters.min_util_cpa_dist == 400.0 == target.safety_radius
    assert parameters.max_util_cpa_dist == 800.0


def test_the_avoidance_behaviour_acts_from_the_visibility_distance(head_on):
    trajectories, own = head_on
    parameters = defaults(trajectories, own)
    visibility = vis_distance(False, 30.0, False, 30.0)
    assert parameters.pwt_outer_dist == pytest.approx(visibility) and visibility > 4 * 240.0
    assert parameters.pwt_inner_dist == pytest.approx(visibility / 2)
    assert parameters.completed_dist == pytest.approx(1.1 * visibility)


def test_a_vessel_alone_still_has_ordered_distances():
    own = make_vessel(0, True)
    states = [ActorState(0.0, 0.0, SPEED, 0.0), ActorState(8.0, 0.0, SPEED, 0.0)]
    parameters = MoosIvpParameters.from_reference(own, states, [own], 1.0)
    assert (parameters.min_util_cpa_dist, parameters.max_util_cpa_dist) == (120.0, 240.0)
    assert (parameters.pwt_inner_dist, parameters.pwt_outer_dist, parameters.completed_dist) == (240.0, 480.0, pytest.approx(528.0))


@pytest.mark.parametrize("dt, radius", [(1.0, 60.0), (15.0, 240.0)])
def test_the_goal_is_reached_within_two_lengths_and_never_within_less_than_two_steps(head_on, dt, radius):
    assert defaults(*head_on, dt=dt).capture_radius == radius


def test_the_default_avoidance_is_the_colregs_behaviour_with_upstreams_other_parameters(head_on):
    parameters = defaults(*head_on)
    assert parameters.avoidance == "colregs" and parameters.behaviour_options == ()


@pytest.mark.parametrize(
    "change, message",
    [
        ({"avoidance": "evasive"}, "avoidance must be one of colregs, cpa"),
        ({"speed": 0.0}, "speed must be positive"),
        ({"speed": 30.0}, "at most max_speed"),
        ({"min_util_cpa_dist": 500.0}, "min_util_cpa_dist must not exceed max_util_cpa_dist"),
        ({"pwt_inner_dist": 2000.0}, "the distances must be ordered"),
        ({"completed_dist": 100.0}, "the distances must be ordered"),
        ({"capture_radius": 0.0}, "capture_radius must be positive"),
    ],
)
def test_parameters_that_contradict_each_other_are_refused(change, message):
    valid = dict(goal=(1.0, 2.0), speed=8.0, max_speed=20.0, min_util_cpa_dist=120.0, max_util_cpa_dist=240.0, pwt_outer_dist=1500.0, pwt_inner_dist=750.0, completed_dist=1650.0, capture_radius=60.0)
    MoosIvpParameters(**valid)
    with pytest.raises(ValueError, match=message):
        MoosIvpParameters(**{**valid, **change})


def test_the_parameters_as_the_run_record_keeps_them(head_on):
    parameters = MoosIvpParameters(
        goal=(1.0, 2.0),
        speed=8.0,
        max_speed=20.0,
        min_util_cpa_dist=120.0,
        max_util_cpa_dist=240.0,
        pwt_outer_dist=1500.0,
        pwt_inner_dist=750.0,
        completed_dist=1650.0,
        capture_radius=60.0,
        avoidance="cpa",
        behaviour_options=(("pwt_grade", "quasi"),),
    )
    assert parameters.as_dict() == {
        "goal": [1.0, 2.0],
        "speed": 8.0,
        "max_speed": 20.0,
        "avoidance": "cpa",
        "min_util_cpa_dist": 120.0,
        "max_util_cpa_dist": 240.0,
        "pwt_outer_dist": 1500.0,
        "pwt_inner_dist": 750.0,
        "completed_dist": 1650.0,
        "capture_radius": 60.0,
        "behaviour_options": [["pwt_grade", "quasi"]],
    }


def test_the_callers_parameters_win_over_the_defaults(head_on):
    trajectories, own = head_on
    chosen = defaults(trajectories, own, dt=15.0)
    assert parameters_for(own, trajectories, 1.0, {own.id: chosen}) is chosen
    assert parameters_for(own, trajectories, 1.0, {99: chosen}) == defaults(trajectories, own)
    assert parameters_for(own, trajectories, 1.0) == defaults(trajectories, own)
