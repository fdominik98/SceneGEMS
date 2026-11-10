"""ReplayFollower: reference interpolation, and a correction that grows continuously with the position error."""

import math

import pytest

from concrete_level.models.actor_state import ActorState
from scenegems_tool.vessel_stack.asv_system.replay.line_of_sight import MAX_BIAS_CORRECTION
from scenegems_tool.vessel_stack.asv_system.replay.replay_follower import ReplayFollower
from scenegems_tool.vessel_stack.contracts.clock import StepRequest
from scenegems_tool.vessel_stack.contracts.ports import VesselStateObservation
from tests.scenegems_tool.vessel_stack.scenarios import make_vessel

VESSEL = make_vessel(0, True, length=30.0, max_angular_speed=0.5)


def reference_line(count: int = 100, speed: float = 5.0):
    """Straight east at `speed`, one state per second."""
    return [ActorState(x=speed * t, y=0.0, speed=speed, heading=0.0) for t in range(count)]


def observation(state: ActorState, time: float = 0.0) -> VesselStateObservation:
    return VesselStateObservation(sim_time=time, vessel=VESSEL, own_state=state, target_states={})


def request(time: float, dt: float = 1.0, index: int = 0) -> StepRequest:
    return StepRequest(index=index, time=time, target_time=time + dt)


class TestConstruction:
    def test_empty_reference_is_rejected(self):
        with pytest.raises(ValueError, match="empty reference trajectory"):
            ReplayFollower(VESSEL, [], 1.0)

    @pytest.mark.parametrize("time_step", [0, -1.0])
    def test_non_positive_reference_time_step_is_rejected(self, time_step):
        with pytest.raises(ValueError, match="reference_time_step must be positive"):
            ReplayFollower(VESSEL, reference_line(), time_step)

    def test_participant_id_names_the_vessel(self):
        assert ReplayFollower(VESSEL, reference_line(), 1.0).participant_id == "replay/0"

    def test_start_accepts_a_seed_and_clears_the_integral(self):
        follower = ReplayFollower(VESSEL, reference_line(), 1.0)
        follower.on_step(request(time=10.0), observation(ActorState(50.0, 5.0, 5.0, 0.0), 10.0))
        assert follower.cross_track_integral != 0.0
        follower.start(123)
        assert follower.cross_track_integral == 0.0


class TestReferenceState:
    def test_samples_are_returned_exactly(self):
        follower = ReplayFollower(VESSEL, reference_line(), 1.0)
        state = follower.reference_state(10.0)
        assert (state.x, state.speed) == (50.0, 5.0)

    def test_interpolates_between_samples(self):
        follower = ReplayFollower(VESSEL, reference_line(), 1.0)
        assert follower.reference_state(10.25).x == pytest.approx(51.25)

    def test_respects_the_reference_time_step(self):
        follower = ReplayFollower(VESSEL, [ActorState(0.0, 0.0, 1.0, 0.0), ActorState(10.0, 0.0, 1.0, 0.0)], 4.0)
        assert follower.reference_state(2.0).x == pytest.approx(5.0)

    def test_holds_the_first_state_before_the_start(self):
        assert ReplayFollower(VESSEL, reference_line(), 1.0).reference_state(-5.0).x == 0.0

    def test_holds_the_last_state_after_the_end(self):
        follower = ReplayFollower(VESSEL, reference_line(count=10), 1.0)
        assert follower.reference_state(500.0).x == 45.0

    def test_heading_interpolates_along_the_shortest_arc(self):
        states = [ActorState(0.0, 0.0, 1.0, math.radians(170)), ActorState(1.0, 0.0, 1.0, math.radians(-170))]
        heading = ReplayFollower(VESSEL, states, 1.0).reference_state(0.5).heading
        assert abs(abs(heading) - math.pi) < 1e-9


class TestOnTheReference:
    def test_it_commands_the_reference_at_the_target_time_exactly(self):
        reference = [ActorState(x=float(t), y=0.0, speed=1.0 + t, heading=0.1 * t) for t in range(10)]
        follower = ReplayFollower(VESSEL, reference, 1.0)
        command = follower.on_step(request(time=3.0), observation(reference[3], 3.0))
        assert command.heading == reference[4].heading
        assert command.speed == reference[4].speed

    def test_a_reference_speed_above_the_vessel_maximum_is_passed_on_unchanged(self):
        fast = [ActorState(x=50.0 * t, y=0.0, speed=50.0, heading=0.0) for t in range(10)]
        command = ReplayFollower(VESSEL, fast, 1.0).on_step(request(time=2.0), observation(fast[2], 2.0))
        assert command.speed == 50.0


class TestCrossTrack:
    def test_the_correction_grows_continuously_from_zero(self):
        """No switch: a tiny offset gets a tiny correction (the old follower changed mode at 1 m)."""
        corrections = []
        for offset in (0.0, 0.01, 0.5, 0.99, 1.01, 3.0, 10.0):
            follower = ReplayFollower(VESSEL, reference_line(), 1.0, integral_factor=None)
            command = follower.on_step(request(time=10.0), observation(ActorState(50.0, offset, 5.0, 0.0), 10.0))
            corrections.append(-command.heading)
        assert corrections[0] == 0.0
        assert corrections == sorted(corrections)
        assert corrections[1] < 1e-3
        assert corrections[4] - corrections[3] < 1e-3, "nothing jumps at 1 m"

    def test_left_of_the_path_it_turns_right_toward_it(self):
        follower = ReplayFollower(VESSEL, reference_line(), 1.0, integral_factor=None)
        assert follower.on_step(request(time=10.0), observation(ActorState(50.0, 4.0, 5.0, 0.0), 10.0)).heading < 0.0
        assert follower.on_step(request(time=10.0), observation(ActorState(50.0, -4.0, 5.0, 0.0), 10.0)).heading > 0.0

    def test_line_of_sight_aims_at_the_path_one_lookahead_ahead(self):
        follower = ReplayFollower(VESSEL, reference_line(speed=5.0), 1.0, lookahead_s=10.0, integral_factor=None)
        command = follower.on_step(request(time=10.0), observation(ActorState(50.0, 10.0, 5.0, 0.0), 10.0))
        assert command.heading == pytest.approx(-math.atan2(10.0, 50.0))

    def test_the_lookahead_is_at_least_one_vessel_length(self):
        slow = reference_line(speed=0.5)
        follower = ReplayFollower(VESSEL, slow, 1.0, lookahead_s=10.0, integral_factor=None)
        command = follower.on_step(request(time=10.0), observation(ActorState(5.0, 3.0, 0.5, 0.0), 10.0))
        assert command.heading == pytest.approx(-math.atan2(3.0, VESSEL.length))

    def test_the_integral_removes_a_standing_offset(self):
        """A vessel that keeps the same offset gets a growing correction, up to the bias limit."""
        follower = ReplayFollower(VESSEL, reference_line(), 1.0, integral_factor=2.0)
        headings = [follower.on_step(request(time=float(t)), observation(ActorState(5.0 * t, 2.0, 5.0, 0.0), float(t))).heading for t in range(1, 300)]
        assert headings[1] < headings[0] < 0.0
        lookahead = VESSEL.length  # 5 s at 5 m/s is shorter than the 30 m vessel
        assert follower.cross_track_integral == pytest.approx(lookahead * math.tan(MAX_BIAS_CORRECTION))

    def test_the_integral_holds_while_the_reference_turns_within_the_lookahead(self):
        """East for 20 s, then a turn to port at 0.1 rad/s: from 15 s on the reference turns within lookahead_s."""
        reference = reference_line(count=20) + [ActorState(x=100.0, y=0.0, speed=5.0, heading=0.1 * t) for t in range(1, 30)]
        follower = ReplayFollower(VESSEL, reference, 1.0, lookahead_s=5.0, integral_factor=2.0)
        follower.on_step(request(time=10.0), observation(ActorState(50.0, 2.0, 5.0, 0.0), 10.0))
        integral = follower.cross_track_integral
        assert integral > 0.0
        follower.on_step(request(time=16.0), observation(ActorState(80.0, 2.0, 5.0, 0.0), 16.0))
        assert follower.cross_track_integral == integral

    def test_without_the_integral_a_standing_offset_keeps_one_correction(self):
        follower = ReplayFollower(VESSEL, reference_line(), 1.0, integral_factor=None)
        headings = {follower.on_step(request(time=float(t)), observation(ActorState(5.0 * t, 2.0, 5.0, 0.0), float(t))).heading for t in range(1, 20)}
        assert len(headings) == 1


class TestAlongTrack:
    def test_behind_the_reference_point_it_speeds_up(self):
        follower = ReplayFollower(VESSEL, reference_line(speed=5.0), 1.0, catch_up_s=10.0)
        command = follower.on_step(request(time=10.0), observation(ActorState(40.0, 0.0, 5.0, 0.0), 10.0))
        assert command.speed == pytest.approx(5.0 + 10.0 / 10.0)

    def test_ahead_of_it_it_slows_down_but_never_reverses(self):
        follower = ReplayFollower(VESSEL, reference_line(speed=5.0), 1.0, catch_up_s=10.0)
        assert follower.on_step(request(time=10.0), observation(ActorState(60.0, 0.0, 5.0, 0.0), 10.0)).speed == pytest.approx(4.0)
        assert follower.on_step(request(time=10.0), observation(ActorState(500.0, 0.0, 5.0, 0.0), 10.0)).speed == 0.0

    def test_catch_up_is_limited_to_the_vessel_maximum(self):
        slow_vessel = make_vessel(0, True, max_speed=6.0)
        follower = ReplayFollower(slow_vessel, reference_line(), 1.0)
        command = follower.on_step(request(time=10.0), observation(ActorState(-500.0, 0.0, 5.0, 0.0), 10.0))
        assert command.speed == 6.0

    def test_after_the_end_of_the_reference_it_stops_on_the_path_instead_of_turning_back(self):
        follower = ReplayFollower(VESSEL, reference_line(count=10), 1.0)
        command = follower.on_step(request(time=20.0), observation(ActorState(200.0, 0.0, 5.0, 0.0), 20.0))
        assert command.heading == 0.0
        assert command.speed == 0.0

    def test_a_large_gap_closes_no_faster_than_the_vessel_can_brake(self):
        """100 m behind at 0.4 m/s^2: sqrt(0.4 * 100) = 6.3 m/s extra, not the 10 m/s of closing it in catch_up_s."""
        follower = ReplayFollower(VESSEL, reference_line(speed=5.0), 1.0, catch_up_s=10.0)
        command = follower.on_step(request(time=30.0), observation(ActorState(50.0, 0.0, 5.0, 0.0), 30.0))
        assert command.speed == pytest.approx(5.0 + math.sqrt(VESSEL.max_acceleration * 100.0))


def test_repeating_the_same_steps_after_start_repeats_the_commands():
    follower = ReplayFollower(VESSEL, reference_line(), 1.0)
    steps = [(float(t), ActorState(5.0 * t - 3.0, 1.5, 5.0, 0.1)) for t in range(1, 30)]
    first = [follower.on_step(request(time=t), observation(state, t)) for t, state in steps]
    follower.start(0)
    second = [follower.on_step(request(time=t), observation(state, t)) for t, state in steps]
    assert first == second
