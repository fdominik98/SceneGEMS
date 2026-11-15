"""size_thrusters and the ArduPilotPlugin multipliers: one or two thrusters that together hold the design speed."""

import math

import pytest

from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.hydrodynamics import RHO_WATER, damping_force
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.thrust_calculation import (
    ThrusterSizing,
    ardupilot_steering_multiplier,
    ardupilot_thrust_multiplier,
    size_thrusters,
)


def sizing(count: int, **changes) -> ThrusterSizing:
    arguments = dict(
        length=10.0,
        breadth=4.0,
        propeller_diameter=1.0,
        design_speed=5.0,
        xU=-10.0,
        xUabsU=-20.0,
        thruster_beam_ratio=0.5,
        thruster_aft_ratio=1.0,
        propeller_kt=0.3,
    )
    arguments.update(changes)
    return size_thrusters(count=count, **arguments)


def servo_command(pwm: float, multiplier: float, offset: float = -0.5) -> float:
    """What the ArduPilotPlugin commands for a servo output: PWM 1000 to 2000 scaled to 0 to 1, shifted, multiplied."""
    return ((pwm - 1000.0) / 1000.0 + offset) * multiplier


class TestSizeThrusters:
    def test_two_thrusters_share_the_thrust_that_holds_the_design_speed(self):
        two = sizing(2)
        assert two.count == 2
        assert two.max_thrust == pytest.approx((10.0 * 5.0 + 20.0 * 25.0) / 2)
        assert two.total_thrust == pytest.approx(damping_force(-10.0, -20.0, 5.0))

    def test_two_thrusters_sit_aft_on_both_sides(self):
        two = sizing(2)
        assert two.thruster_x == -5.0
        assert two.thruster_y == 1.0, "the port one; the starboard one is mirrored"

    def test_one_thruster_gives_all_the_thrust_on_the_centerline(self):
        one = sizing(1)
        assert one.count == 1
        assert one.max_thrust == pytest.approx(10.0 * 5.0 + 20.0 * 25.0)
        assert one.total_thrust == pytest.approx(one.max_thrust)
        assert (one.thruster_x, one.thruster_y) == (-5.0, 0.0)

    def test_one_or_two_thrusters_give_the_same_total_thrust(self):
        assert sizing(1).total_thrust == pytest.approx(sizing(2).total_thrust)
        assert sizing(1).max_thrust == pytest.approx(2.0 * sizing(2).max_thrust)

    @pytest.mark.parametrize("count", [1, 2])
    def test_the_positions_follow_the_ratios(self, count):
        placed = sizing(count, length=30.0, breadth=9.0, thruster_aft_ratio=0.9, thruster_beam_ratio=0.8)
        assert placed.thruster_x == pytest.approx(-13.5)
        assert placed.thruster_y == pytest.approx(3.6 if count == 2 else 0.0)

    @pytest.mark.parametrize("count", [1, 2])
    def test_the_thrust_coefficient_is_the_propellers_in_radians_per_second(self, count):
        sized = sizing(count)
        assert sized.thrust_coefficient == pytest.approx(0.3 / (2 * math.pi) ** 2)

    @pytest.mark.parametrize("count", [1, 2])
    def test_the_propeller_gives_the_max_thrust_at_its_max_speed(self, count):
        sized = sizing(count, propeller_diameter=0.8)
        assert sized.max_propeller_speed > 0
        assert sized.thrust_coefficient * RHO_WATER * sized.max_propeller_speed**2 * 0.8**4 == pytest.approx(sized.max_thrust)

    def test_a_faster_design_speed_needs_more_thrust(self):
        assert sizing(1, design_speed=6.0).max_thrust > sizing(1).max_thrust
        assert sizing(1, design_speed=6.0).max_thrust == pytest.approx(10.0 * 6.0 + 20.0 * 36.0)

    @pytest.mark.parametrize("count", [0, 3, 4, -1])
    def test_other_thruster_counts_are_refused(self, count):
        with pytest.raises(ValueError, match=f"a generated vessel has one or two thrusters, got {count}"):
            sizing(count)


class TestArduPilotMultipliers:
    def test_the_thrust_multiplier_spans_astern_to_ahead(self):
        multiplier = ardupilot_thrust_multiplier(1000.0)
        assert multiplier == 2000.0
        assert servo_command(1000.0, multiplier) == pytest.approx(-1000.0)
        assert servo_command(1500.0, multiplier) == pytest.approx(0.0)
        assert servo_command(2000.0, multiplier) == pytest.approx(1000.0)

    def test_the_steering_multiplier_spans_hard_over_to_hard_over(self):
        max_angle = math.radians(35.0)
        multiplier = ardupilot_steering_multiplier(max_angle)
        assert multiplier == pytest.approx(2.0 * max_angle)
        assert servo_command(1000.0, multiplier) == pytest.approx(-max_angle), "hard over to port"
        assert servo_command(1500.0, multiplier) == pytest.approx(0.0), "amidships"
        assert servo_command(2000.0, multiplier) == pytest.approx(max_angle), "hard over to starboard: a positive helm angle"
        assert servo_command(1750.0, multiplier) == pytest.approx(max_angle / 2.0)
