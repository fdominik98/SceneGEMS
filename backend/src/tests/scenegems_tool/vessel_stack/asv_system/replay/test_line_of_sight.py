"""LineOfSight: the cross-track correction of the replay followers."""

import math

import pytest

from scenegems_tool.vessel_stack.asv_system.replay.line_of_sight import MAX_BIAS_CORRECTION, TURN_LIMITED_LOOKAHEAD, LineOfSight, catch_up_speed
from tests.scenegems_tool.vessel_stack.scenarios import make_vessel

SHIP = make_vessel(0, True, length=100.0, max_speed=12.9, max_angular_speed=0.008)


def test_on_the_path_the_correction_is_exactly_zero():
    line = LineOfSight(SHIP, 5.0, 2.0)
    assert line.correction(0.0, 8.0, 1.0) == 0.0
    assert line.integral == 0.0


def test_the_base_lookahead_is_the_travel_of_lookahead_s_but_at_least_a_length():
    line = LineOfSight(SHIP, 5.0, 2.0)
    assert line.base_lookahead(8.0) == 100.0
    assert line.base_lookahead(40.0) == 200.0


def test_a_large_error_stretches_the_lookahead_by_the_turning_radius():
    """At 8 m/s and 0.008 rad/s the turning radius is 1 km; 100 m off, the lookahead is 2 sqrt(1000 * 100)."""
    line = LineOfSight(SHIP, 5.0, 2.0)
    assert line.lookahead(8.0, 100.0) == pytest.approx(TURN_LIMITED_LOOKAHEAD * math.sqrt(1000.0 * 100.0))
    assert line.lookahead(8.0, 1.0) == 100.0


def test_the_heading_demand_changes_slower_than_the_vessel_can_turn():
    """Moving toward the path at the commanded intercept, the demand changes at most a quarter of the max turn rate."""
    line = LineOfSight(SHIP, 5.0, None)
    speed, dt = 8.0, 0.1
    rates = []
    for error in [float(e) for e in range(5, 1000, 5)]:
        lookahead = line.lookahead(speed, error)
        approach = speed * math.sin(math.atan2(error, lookahead))
        rate = abs(line.correction(error - approach * dt, speed, dt) - line.correction(error, speed, dt)) / dt
        rates.append(rate)
    assert max(rates) <= SHIP.max_angular_speed / 4 * 1.01


def test_the_integral_runs_only_while_the_error_is_small():
    line = LineOfSight(SHIP, 5.0, 2.0)
    line.correction(500.0, 8.0, 1.0)
    assert line.integral == 0.0
    line.correction(2.0, 8.0, 1.0)
    assert line.integral == pytest.approx(2.0 * 8.0 / (2.0 * 100.0))


def test_the_integral_runs_only_within_its_own_limit():
    """A turn-limited lookahead needs 2.5 m at 1 km turning radius; the limit, 100 m tan 15 deg, is 26.8 m: with a
    slower turn rate the lookahead stays at its base for errors a bias cannot cause."""
    agile = make_vessel(0, True, length=100.0, max_speed=12.9, max_angular_speed=1.0)
    line = LineOfSight(agile, 5.0, 2.0)
    line.correction(30.0, 8.0, 1.0)
    assert line.lookahead(8.0, 30.0) == 100.0
    assert line.integral == 0.0
    line.correction(20.0, 8.0, 1.0)
    assert line.integral == pytest.approx(20.0 * 8.0 / (2.0 * 100.0))


def test_the_integral_holds_where_the_path_ahead_is_not_straight():
    line = LineOfSight(SHIP, 5.0, 2.0)
    assert line.step(2.0, 8.0, 1.0, straight=False) == 100.0
    assert line.integral == 0.0


def test_the_integral_is_limited_to_the_max_bias_correction():
    line = LineOfSight(SHIP, 5.0, 2.0)
    for _ in range(10_000):
        line.correction(2.0, 8.0, 1.0)
    assert line.integral == pytest.approx(100.0 * math.tan(MAX_BIAS_CORRECTION))


def test_a_vessel_that_cannot_turn_keeps_the_base_lookahead():
    rock = make_vessel(0, True, length=10.0, max_angular_speed=0.0)
    assert LineOfSight(rock, 5.0, 2.0).lookahead(4.0, 1000.0) == 20.0


class TestCatchUpSpeed:
    def test_a_small_gap_closes_in_catch_up_s(self):
        assert catch_up_speed(5.0, 10.0, 0.4) == 0.5
        assert catch_up_speed(-5.0, 10.0, 0.4) == -0.5

    def test_a_large_gap_closes_no_faster_than_the_vessel_can_brake(self):
        """sqrt(a |gap|): from there the vessel brakes to the reference speed within the gap at half its max acceleration."""
        assert catch_up_speed(200.0, 10.0, 0.05) == pytest.approx(math.sqrt(0.05 * 200.0))
        assert catch_up_speed(-200.0, 10.0, 0.05) == pytest.approx(-math.sqrt(0.05 * 200.0))

    def test_no_gap_no_correction(self):
        assert catch_up_speed(0.0, 10.0, 0.4) == 0.0

    def test_a_vessel_without_an_acceleration_limit_closes_in_catch_up_s(self):
        assert catch_up_speed(500.0, 10.0, 0.0) == 50.0
