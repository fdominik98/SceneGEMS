"""LosWaypointFollower: the replay route of the custom controller, steered by the path's geometry and paced by its timing."""

import math

import pytest

from concrete_level.models.actor_state import ActorState
from scenegems_tool.vessel_stack.asv_system.replay.line_of_sight import MAX_BIAS_CORRECTION
from scenegems_tool.vessel_stack.contracts.clock import StepRequest
from scenegems_tool.vessel_stack.contracts.ports import VesselStateObservation
from scenegems_tool.vessel_stack.control_layers.custom.los_waypoint_follower import LosWaypointFollower
from tests.scenegems_tool.vessel_stack.scenarios import make_vessel

VESSEL = make_vessel(0, True, length=10.0, max_speed=8.0, max_angular_speed=0.5)


def east(count=60, speed=4.0):
    return [ActorState(x=speed * t, y=0.0, speed=speed, heading=0.0) for t in range(count)]


def corner(speed=4.0):
    """40 s east, then 40 s north, one state per second."""
    states = [ActorState(x=speed * t, y=0.0, speed=speed, heading=0.0) for t in range(41)]
    states += [ActorState(x=speed * 40, y=speed * t, speed=speed, heading=math.pi / 2) for t in range(1, 41)]
    return states


def step(follower, time, x, y, dt=1.0):
    observation = VesselStateObservation(sim_time=time, vessel=VESSEL, own_state=ActorState(x, y, 4.0, 0.0), target_states={})
    return follower.on_step(StepRequest(index=int(time), time=time, target_time=time + dt), observation)


class TestConstruction:
    def test_a_mission_needs_two_waypoints(self):
        with pytest.raises(ValueError, match="at least two reference states"):
            LosWaypointFollower(VESSEL, east(1), 1.0)

    def test_participant_id_names_the_vessel(self):
        assert LosWaypointFollower(VESSEL, east(), 1.0).participant_id == "replay/0"


class TestHeading:
    def test_on_the_path_it_steers_the_legs_course(self):
        follower = LosWaypointFollower(VESSEL, east(), 1.0)
        assert step(follower, 10.0, 40.0, 0.0).heading == 0.0

    def test_left_of_the_path_it_turns_right_and_right_of_it_left(self):
        assert step(LosWaypointFollower(VESSEL, east(), 1.0, integral_factor=None), 10.0, 40.0, 3.0).heading < 0
        assert step(LosWaypointFollower(VESSEL, east(), 1.0, integral_factor=None), 10.0, 40.0, -3.0).heading > 0

    def test_line_of_sight_over_the_lookahead(self):
        follower = LosWaypointFollower(VESSEL, east(speed=4.0), 1.0, lookahead_s=5.0, integral_factor=None)
        assert step(follower, 10.0, 40.0, 2.0).heading == pytest.approx(-math.atan2(2.0, 20.0))

    def test_the_corner_is_turned_where_the_path_turns_not_where_the_reference_is_in_time(self):
        """A vessel 60 m behind still follows the eastbound leg, while the reference is already northbound."""
        follower = LosWaypointFollower(VESSEL, corner(), 1.0, integral_factor=None)
        command = step(follower, 50.0, 100.0, 0.0)
        assert command.heading == 0.0
        assert follower.active_leg == 25

    def test_the_active_leg_only_moves_forward(self):
        follower = LosWaypointFollower(VESSEL, corner(), 1.0)
        step(follower, 45.0, 160.0, 10.0)
        leg = follower.active_leg
        assert leg >= 40
        step(follower, 46.0, 100.0, 0.0)
        assert follower.active_leg == leg

    def test_on_a_straight_leg_it_is_the_line_of_sight_with_the_integral(self):
        """Aiming at the path point one lookahead ahead, moved across by the integral, is course - atan((e + i) / lookahead)."""
        follower = LosWaypointFollower(VESSEL, east(), 1.0, lookahead_s=5.0, integral_factor=2.0)
        command = step(follower, 10.0, 40.0, 2.0)
        integral = follower.cross_track_integral
        assert integral == pytest.approx(2.0 * 1.0 * 4.0 / (2.0 * 20.0))
        assert command.heading == pytest.approx(-math.atan2(2.0 + integral, 20.0))

    def test_it_starts_turning_before_the_corner(self):
        """10 m before the corner the path point 20 m ahead is already round it: the vessel turns toward the new leg."""
        follower = LosWaypointFollower(VESSEL, corner(), 1.0, lookahead_s=5.0, integral_factor=None)
        command = step(follower, 37.5, 150.0, 0.0)
        assert command.heading == pytest.approx(math.atan2(10.0, 10.0))

    def test_the_integral_holds_while_the_path_ahead_turns(self):
        follower = LosWaypointFollower(VESSEL, corner(), 1.0, lookahead_s=5.0, integral_factor=2.0)
        step(follower, 30.0, 120.0, 1.0)
        integral = follower.cross_track_integral
        assert integral > 0.0
        step(follower, 37.5, 150.0, 1.0)
        assert follower.cross_track_integral == integral

    def test_path_point_follows_the_legs_and_extends_the_last_one(self):
        follower = LosWaypointFollower(VESSEL, corner(), 1.0)
        assert follower.path_point(100.0) == pytest.approx((100.0, 0.0, 0.0))
        assert follower.path_point(170.0) == pytest.approx((160.0, 10.0, math.pi / 2))
        assert follower.path_point(400.0) == pytest.approx((160.0, 240.0, math.pi / 2))

    def test_the_integral_corrects_a_standing_offset_up_to_the_limit(self):
        follower = LosWaypointFollower(VESSEL, east(count=400), 1.0)
        headings = [step(follower, float(t), 4.0 * t, 2.0).heading for t in range(1, 300)]
        assert headings[50] < headings[0] < 0
        lookahead = max(VESSEL.length, 5.0 * 4.0)
        assert follower.cross_track_integral == pytest.approx(lookahead * math.tan(MAX_BIAS_CORRECTION))


class TestSpeed:
    def test_on_time_it_commands_the_reference_speed(self):
        assert step(LosWaypointFollower(VESSEL, east(), 1.0), 10.0, 40.0, 0.0).speed == 4.0

    def test_behind_the_reference_it_catches_up_and_ahead_it_slows_down(self):
        follower = LosWaypointFollower(VESSEL, east(), 1.0, catch_up_s=10.0)
        assert step(follower, 10.0, 30.0, 0.0).speed == pytest.approx(5.0)
        follower = LosWaypointFollower(VESSEL, east(), 1.0, catch_up_s=10.0)
        assert step(follower, 10.0, 50.0, 0.0).speed == pytest.approx(3.0)

    def test_a_large_gap_closes_no_faster_than_the_vessel_can_brake(self):
        """20 m behind at 0.05 m/s^2: sqrt(0.05 * 20) = 1 m/s extra, not the 2 m/s of closing it in catch_up_s."""
        sluggish = make_vessel(0, True, length=10.0, max_speed=8.0, max_angular_speed=0.5, max_acceleration=0.05)
        follower = LosWaypointFollower(sluggish, east(), 1.0, catch_up_s=10.0)
        assert step(follower, 10.0, 20.0, 0.0).speed == pytest.approx(5.0)

    def test_speed_stays_within_zero_and_the_vessels_maximum(self):
        assert step(LosWaypointFollower(VESSEL, east(), 1.0), 10.0, -500.0, 0.0).speed == VESSEL.max_speed
        assert step(LosWaypointFollower(VESSEL, east(), 1.0), 10.0, 230.0, 0.0).speed == 0.0

    def test_beyond_the_last_waypoint_the_last_leg_extends(self):
        follower = LosWaypointFollower(VESSEL, east(count=10), 1.0)
        command = step(follower, 30.0, 100.0, 0.0)
        assert command.heading == 0.0
        assert command.speed == 0.0


def test_start_resets_the_leg_and_the_integral():
    follower = LosWaypointFollower(VESSEL, corner(), 1.0)
    step(follower, 45.0, 160.0, 10.0)
    follower.start(7)
    assert follower.active_leg == 0 and follower.cross_track_integral == 0.0


def test_the_same_steps_after_start_give_the_same_commands():
    follower = LosWaypointFollower(VESSEL, corner(), 1.0)
    path = [(float(t), 4.0 * min(t, 40) - 1.0, 4.0 * max(t - 40, 0) + 0.5) for t in range(1, 70)]
    first = [step(follower, t, x, y) for t, x, y in path]
    follower.start(0)
    assert [step(follower, t, x, y) for t, x, y in path] == first
