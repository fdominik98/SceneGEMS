import unittest

import numpy as np

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from utils.colregs_approximations import vessel_radius
from utils.math_utils import abs_heading_diff, heading_diff


class TestConcreteVesselSimulate(unittest.TestCase):
    """Test cases for ConcreteVessel.simulate method focusing on edge cases and turning limits."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        """Set up a test vessel with known parameters."""
        self.vessel = ConcreteVessel(
            id=1,
            _is_os=True,
            type="test_vessel",
            length=50.0,
            breadth=8.0,
            height=50.0 / 9,
            draft=50.0 / 9 * 0.4,
            mass=1000.0,
            safety_radius=vessel_radius(50.0),
            _rudder_mass=100.0,
            _rudder_length=10.0,
            _rudder_width=10.0,
            _rudder_height=10.0,
            _propeller_diameter=10.0,
            _thruster_mass=100.0,
            _motor_length=10.0,
            _max_speed=10.0,
            _max_angular_speed=0.5,
            _max_acceleration=2.0,
        )

        # Standard initial state
        self.initial_state = ActorState(x=0.0, y=0.0, speed=5.0, heading=0.0)

    def test_basic_simulation(self):
        """Test basic simulation with no limits reached."""
        dt = 1.0
        heading_ref = 0.2  # Small turn within limits
        speed_ref = 6.0

        result = self.vessel.simulate(self.initial_state, (heading_ref, speed_ref), dt)

        # Should be able to reach the reference heading (within angular speed limit)
        self.assertAlmostEqual(result.heading, heading_ref)
        # Speed should increase towards reference
        self.assertAlmostEqual(result.speed, speed_ref)

    def test_heading_limit_exceeded_clockwise(self):
        """Test when vessel is asked to turn more than max angular speed allows."""
        dt = 1.0
        # Request a turn of 1.0 rad (more than max_angular_speed * dt = 0.5)
        heading_ref = 1.0

        result = self.vessel.simulate(self.initial_state, (heading_ref, 5.0), dt)

        # Should only turn by max_angular_speed * dt = 0.5 rad
        expected_heading = 0.5  # 0.0 + 0.5
        assert abs_heading_diff(result.heading, expected_heading) < 0.01

    def test_heading_limit_exceeded_counterclockwise(self):
        """Test when vessel is asked to turn more than max angular speed allows (negative direction)."""
        dt = 1.0
        # Request a turn of -1.0 rad (more than max_angular_speed * dt = 0.5)
        heading_ref = -1.0

        result = self.vessel.simulate(self.initial_state, (heading_ref, 5.0), dt)

        # Should only turn by -max_angular_speed * dt = -0.5 rad
        expected_heading = -0.5  # 0.0 + (-0.5)
        assert abs_heading_diff(result.heading, expected_heading) < 0.01

    def test_heading_limit_exceeded_large_dt(self):
        """Test heading limits with large time step."""
        dt = 10.0  # Large time step
        # Request a turn of 2π rad (full circle)
        heading_ref = 2 * np.pi

        result = self.vessel.simulate(self.initial_state, (heading_ref, 5.0), dt)

        # Should not turn since 360° == 0°, so expected turn is 0
        self.assertAlmostEqual(result.heading, 0.0)

    def test_angle_wrapping_around_pi_boundary(self):
        """Test angle wrapping when crossing the ±π boundary."""
        # Start near π boundary
        initial_state = ActorState(x=0.0, y=0.0, speed=5.0, heading=3.0)  # ~172°
        dt = 1.0
        # Request heading that wraps around the boundary
        heading_ref = -3.0  # ~-172°

        result = self.vessel.simulate(initial_state, (heading_ref, 5.0), dt)

        # Should handle wrapping correctly and turn towards the shorter path
        self.assertAlmostEqual(result.heading, heading_ref)

    def test_angle_wrapping_around_zero_boundary(self):
        """Test angle wrapping when crossing the 0° boundary."""
        # Start near 0° boundary
        initial_state = ActorState(x=0.0, y=0.0, speed=5.0, heading=-0.1)  # ~-6°
        dt = 1.0
        # Request heading that wraps around 0°
        heading_ref = 0.1  # ~6°

        result = self.vessel.simulate(initial_state, (heading_ref, 5.0), dt)

        # Should handle wrapping correctly
        expected_heading = 0.1  # Should reach the reference (small change)
        assert abs(result.heading - expected_heading) < 0.01

    def test_extreme_heading_differences(self):
        """Test extreme heading differences that require significant wrapping."""
        dt = 1.0

        # Test case 1: Nearly opposite headings
        initial_state = ActorState(x=0.0, y=0.0, speed=5.0, heading=0.01)  # Just above 0°
        heading_ref = np.pi - 0.01  # Just below 180°

        result = self.vessel.simulate(initial_state, (heading_ref, 5.0), dt)

        # Should choose the shorter path and be limited by angular speed
        heading_change = abs_heading_diff(result.heading, initial_state.heading)
        assert heading_change <= self.vessel.max_angular_speed * dt + 0.01

        # Test case 2: Full 180° turn request
        heading_ref = np.pi  # 180°
        result = self.vessel.simulate(initial_state, (heading_ref, 5.0), dt)

        # Should turn towards the reference but be limited
        heading_change = abs_heading_diff(result.heading, initial_state.heading)
        assert heading_change <= self.vessel.max_angular_speed * dt + 0.01

    def test_speed_limit_exceeded(self):
        """Test when vessel is asked to accelerate more than max_acceleration allows."""
        dt = 1.0
        # Request speed increase of 5 m/s (more than max_acceleration * dt = 2.0)
        speed_ref = 10.0  # 5.0 + 5.0

        result = self.vessel.simulate(self.initial_state, (0.0, speed_ref), dt)

        # Should only accelerate by max_acceleration * dt = 2.0 m/s
        expected_speed = 7.0  # 5.0 + 2.0
        assert abs(result.speed - expected_speed) < 0.01

    def test_speed_deceleration_limit(self):
        """Test when vessel is asked to decelerate more than max_acceleration allows."""
        # Start with high speed
        initial_state = ActorState(x=0.0, y=0.0, speed=8.0, heading=0.0)
        dt = 1.0
        # Request speed decrease of 6 m/s (more than max_acceleration * dt = 2.0)
        speed_ref = 2.0  # 8.0 - 6.0

        result = self.vessel.simulate(initial_state, (0.0, speed_ref), dt)

        # Should only decelerate by max_acceleration * dt = 2.0 m/s
        expected_speed = 6.0  # 8.0 - 2.0
        assert abs_heading_diff(result.speed, expected_speed) < 0.01

    def test_speed_max_limit_respected(self):
        """Test that speed doesn't exceed max_speed even when requested."""
        dt = 10.0  # Large time step
        # Request speed well above max_speed
        speed_ref = 20.0  # max_speed is 10.0

        result = self.vessel.simulate(self.initial_state, (0.0, speed_ref), dt)

        # Should be clamped to max_speed
        assert result.speed == self.vessel.max_speed

    def test_speed_minimum_zero(self):
        """Test that speed doesn't go below zero."""
        dt = 10.0  # Large time step
        # Request negative speed
        speed_ref = -5.0

        result = self.vessel.simulate(self.initial_state, (0.0, speed_ref), dt)

        # Should be clamped to 0.0
        assert result.speed == 0.0

    def test_multiple_time_steps_heading_limit(self):
        """Test that heading changes are properly limited across multiple time steps."""
        dt = 0.1  # Small time steps
        heading_ref = 2.0  # Large heading change
        current_state = self.initial_state

        # Simulate for multiple time steps
        for _ in range(10):  # 1 second total
            current_state = self.vessel.simulate(current_state, (heading_ref, 5.0), dt)

        # Total heading change should not exceed max_angular_speed * total_time
        total_time = 10 * dt
        max_total_change = self.vessel.max_angular_speed * total_time
        total_change = abs_heading_diff(current_state.heading, self.initial_state.heading)

        assert total_change <= max_total_change + 0.01

    def test_heading_step_minimum_bound(self):
        """Test that max_heading_step respects the minimum bound of π."""
        # Create vessel with very high angular speed
        fast_vessel = ConcreteVessel(
            id=2,
            type="fast_vessel",
            length=50.0,
            breadth=8.0,
            height=50.0 / 9,
            draft=50.0 / 9 * 0.4,
            mass=1000.0,
            safety_radius=vessel_radius(50.0),
            _is_os=True,
            _rudder_mass=100.0,
            _rudder_length=10.0,
            _rudder_width=10.0,
            _rudder_height=10.0,
            _propeller_diameter=10.0,
            _thruster_mass=100.0,
            _motor_length=10.0,
            _max_speed=10.0,
            _max_angular_speed=10.0,  # Very high angular speed
            _max_acceleration=2.0,
        )

        dt = 1.0
        # Request a turn larger than π
        heading_ref = 4.0  # ~229°

        result = fast_vessel.simulate(self.initial_state, (heading_ref, 5.0), dt)

        # Should be limited by π, not by max_angular_speed * dt = 10.0
        heading_change = abs_heading_diff(result.heading, self.initial_state.heading)
        assert heading_change <= np.pi + 0.01

    def test_combined_limits_heading_and_speed(self):
        """Test simulation when both heading and speed limits are reached."""
        dt = 1.0
        # Request both large heading change and large speed change
        heading_ref = 2.0  # Will be limited
        speed_ref = 15.0  # Will be limited

        result = self.vessel.simulate(self.initial_state, (heading_ref, speed_ref), dt)

        # Both should be limited
        expected_heading_change = self.vessel.max_angular_speed * dt
        expected_speed_change = self.vessel.max_acceleration * dt

        assert abs_heading_diff(result.heading, self.initial_state.heading) <= expected_heading_change + 0.01
        assert abs(result.speed - self.initial_state.speed) <= expected_speed_change + 0.01
        assert result.speed <= self.vessel.max_speed
