"""hydrodynamics: the damping splits, the hull's coefficients and the forces of a rudder and of a vectored thruster.

Body frame: x forward, y to port. A helm angle is counterclockwise seen from above, and a
positive one turns the vessel to starboard: the steering gear sits aft, so it has to push the
stern to port (a positive Y).
"""

import math

import pytest

from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.hydrodynamics import (
    GRAVITY,
    RHO_WATER,
    calculate_hydrodynamics,
    damping_force,
    rudder_force,
    rudder_normal_force_coefficient,
    split_damping,
    surge_damping,
    vectored_thrust_force,
)

AREA, LIFT_SLOPE = 1.5, 2.5
GAIN = 0.5 * RHO_WATER * AREA * LIFT_SLOPE  # N per (m/s)^2 of a blade square to the flow at one rad
ANGLES = [math.radians(degrees) for degrees in (5.0, 15.0, 35.0, 60.0)]


def hydrodynamics(**changes):
    arguments = dict(
        length=30.0,
        breadth=10.0,
        draft=1.8,
        displacement_mass=332_000.0,
        hull_ixx=4.0e6,
        hull_iyy=1.8e7,
        hull_izz=1.8e7,
        roll_metacentric_height=4.0,
        pitch_metacentric_height=34.0,
        waterplane_area=220.0,
        max_speed=10.0,
        cross_flow_drag_coefficient=1.0,
        block_coefficient=0.6,
        surge_added_mass_ratio=0.05,
        added_mass_cap=0.5,
        heave_damping_ratio=0.5,
        roll_pitch_damping_ratio=0.3,
    )
    arguments.update(changes)
    return calculate_hydrodynamics(**arguments)


class TestDamping:
    def test_split_damping_sums_to_the_reference_damping(self):
        linear, quadratic = split_damping(100.0, 4.0, 0.25)
        assert abs(linear) * 4.0 + abs(quadratic) * 16.0 == pytest.approx(100.0)
        assert linear < 0 and quadratic < 0

    def test_split_damping_gives_the_linear_term_its_share(self):
        linear, quadratic = split_damping(100.0, 4.0, 0.25)
        assert linear == pytest.approx(-25.0 / 4.0)
        assert quadratic == pytest.approx(-75.0 / 16.0)

    @pytest.mark.parametrize("share", [0.0, 1.0])
    def test_split_damping_can_be_all_quadratic_or_all_linear(self, share):
        linear, quadratic = split_damping(60.0, 2.0, share)
        assert (linear, quadratic) == pytest.approx((-30.0 * share, -15.0 * (1.0 - share)))

    def test_surge_resistance_at_max_speed_uses_the_wetted_surface(self):
        linear, quadratic = surge_damping(wetted_surface=60.0, max_speed=5.0, resistance_coefficient=0.005, linear_damping_share=0.2)
        resistance = 0.5 * RHO_WATER * 0.005 * 60.0 * 25.0
        assert damping_force(linear, quadratic, 5.0) == pytest.approx(resistance)
        assert abs(linear) * 5.0 == pytest.approx(0.2 * resistance)
        assert linear < 0 and quadratic < 0

    def test_surge_resistance_grows_with_the_wetted_surface(self):
        small = surge_damping(60.0, 5.0, 0.005, 0.2)
        large = surge_damping(120.0, 5.0, 0.005, 0.2)
        assert large == pytest.approx((2.0 * small[0], 2.0 * small[1]))

    def test_damping_force_is_a_magnitude(self):
        assert damping_force(-3.0, -2.0, 4.0) == pytest.approx(3.0 * 4.0 + 2.0 * 16.0)
        assert damping_force(3.0, 2.0, 4.0) == damping_force(-3.0, -2.0, 4.0)
        assert damping_force(-3.0, -2.0, 0.0) == 0.0


class TestRudderForce:
    def test_the_normal_force_coefficient_opposes_the_flow_across_the_blade(self):
        assert rudder_normal_force_coefficient(AREA, LIFT_SLOPE) == pytest.approx(-0.5 * RHO_WATER * AREA * LIFT_SLOPE)
        assert rudder_normal_force_coefficient(AREA, LIFT_SLOPE) == -GAIN

    @pytest.mark.parametrize("angle", ANGLES)
    def test_a_positive_helm_angle_pushes_the_stern_to_port_and_slows_the_vessel(self, angle):
        x, y = rudder_force(angle, 6.0, 0.0, AREA, LIFT_SLOPE)
        assert y > 0.0, "to port: a rudder aft then turns the vessel to starboard"
        assert x < 0.0, "a turned rudder is a drag"

    @pytest.mark.parametrize("angle", ANGLES)
    def test_port_and_starboard_helm_are_mirror_images(self, angle):
        x, y = rudder_force(angle, 6.0, 0.0, AREA, LIFT_SLOPE)
        assert rudder_force(-angle, 6.0, 0.0, AREA, LIFT_SLOPE) == pytest.approx((x, -y))

    def test_the_whole_force_field_is_mirrored_with_the_sway(self):
        """Mirroring the helm angle and the sway mirrors the side force and keeps the drag."""
        for angle, sway in ((0.3, 1.2), (-0.5, 0.4), (0.0, -2.0), (0.2, -0.7)):
            x, y = rudder_force(angle, 5.0, sway, AREA, LIFT_SLOPE)
            assert rudder_force(-angle, 5.0, -sway, AREA, LIFT_SLOPE) == pytest.approx((x, -y))

    @pytest.mark.parametrize("angle", [0.0] + ANGLES + [-angle for angle in ANGLES])
    def test_a_rudder_at_rest_gives_no_force(self, angle):
        """No propeller wash is modelled."""
        assert rudder_force(angle, 0.0, 0.0, AREA, LIFT_SLOPE) == (0.0, 0.0)

    def test_a_rudder_amidships_on_a_straight_course_gives_no_force(self):
        assert rudder_force(0.0, 8.0, 0.0, AREA, LIFT_SLOPE) == (0.0, 0.0)

    @pytest.mark.parametrize("angle", ANGLES)
    def test_the_force_grows_with_the_square_of_the_speed(self, angle):
        slow = rudder_force(angle, 3.0, 0.0, AREA, LIFT_SLOPE)
        fast = rudder_force(angle, 6.0, 0.0, AREA, LIFT_SLOPE)
        assert fast == pytest.approx((4.0 * slow[0], 4.0 * slow[1]))
        drifting_slow = rudder_force(angle, 3.0, -0.5, AREA, LIFT_SLOPE)
        drifting_fast = rudder_force(angle, 6.0, -1.0, AREA, LIFT_SLOPE)
        assert drifting_fast == pytest.approx((4.0 * drifting_slow[0], 4.0 * drifting_slow[1]))

    @pytest.mark.parametrize("angle", ANGLES)
    def test_on_a_straight_course_the_force_follows_the_closed_form(self, angle):
        """Y = K u^2 sin(d) cos(d)^2 and X = -K u^2 sin(d)^2 cos(d)."""
        speed = 7.0
        x, y = rudder_force(angle, speed, 0.0, AREA, LIFT_SLOPE)
        assert y == pytest.approx(GAIN * speed**2 * math.sin(angle) * math.cos(angle) ** 2)
        assert x == pytest.approx(-GAIN * speed**2 * math.sin(angle) ** 2 * math.cos(angle))

    @pytest.mark.parametrize("angle,surge,sway", [(0.3, 6.0, 0.0), (-0.6, 4.0, 1.0), (0.2, 5.0, -2.0), (1.1, 3.0, 0.5), (0.0, 5.0, 1.5)])
    def test_the_force_is_normal_to_the_blade(self, angle, surge, sway):
        x, y = rudder_force(angle, surge, sway, AREA, LIFT_SLOPE)
        along_the_blade = x * math.cos(angle) + y * math.sin(angle)
        assert along_the_blade == pytest.approx(0.0, abs=1e-9 * math.hypot(x, y))
        assert math.hypot(x, y) > 0.0

    @pytest.mark.parametrize("angle,surge,sway", [(0.3, 6.0, 0.0), (-0.6, 4.0, 1.0), (0.2, 5.0, -2.0), (0.0, 5.0, 1.5)])
    def test_the_force_is_the_flow_across_the_blade_times_the_flow_along_it(self, angle, surge, sway):
        along = surge * math.cos(angle) + sway * math.sin(angle)
        across = -surge * math.sin(angle) + sway * math.cos(angle)
        x, y = rudder_force(angle, surge, sway, AREA, LIFT_SLOPE)
        normal = -x * math.sin(angle) + y * math.cos(angle)
        assert normal == pytest.approx(-GAIN * across * abs(along)), "it opposes the blade's motion across the water"

    def test_the_force_fades_as_the_blade_turns_broadside(self):
        """The force peaks at 45 degrees and is gone at 90, where no water flows along the blade."""
        magnitudes = [math.hypot(*rudder_force(math.radians(degrees), 6.0, 0.0, AREA, LIFT_SLOPE)) for degrees in (45.0, 60.0, 75.0, 85.0)]
        assert all(later < earlier for earlier, later in zip(magnitudes, magnitudes[1:]))
        assert math.hypot(*rudder_force(math.pi / 2.0, 6.0, 0.0, AREA, LIFT_SLOPE)) == pytest.approx(0.0, abs=1e-9 * GAIN)
        assert math.hypot(*rudder_force(math.radians(30.0), 6.0, 0.0, AREA, LIFT_SLOPE)) < magnitudes[0]

    def test_a_rudder_amidships_resists_the_sway_of_the_stern(self):
        x, y = rudder_force(0.0, 6.0, 1.5, AREA, LIFT_SLOPE)
        assert x == pytest.approx(0.0, abs=1e-9) and y == pytest.approx(-GAIN * 1.5 * 6.0)
        assert rudder_force(0.0, 6.0, -1.5, AREA, LIFT_SLOPE)[1] == pytest.approx(GAIN * 1.5 * 6.0)

    def test_a_blade_in_line_with_the_flow_gives_no_force(self):
        """A stern that slides sideways as fast as the helm angle asks leaves the blade no angle of attack."""
        angle, surge = 0.3, 6.0
        x, y = rudder_force(angle, surge, surge * math.tan(angle), AREA, LIFT_SLOPE)
        assert (x, y) == pytest.approx((0.0, 0.0), abs=1e-9 * GAIN)

    def test_a_stern_swinging_away_from_the_rudders_push_eases_it(self):
        """In a turn to starboard the stern swings to port, which takes angle of attack off the rudder."""
        straight = rudder_force(0.4, 6.0, 0.0, AREA, LIFT_SLOPE)[1]
        turning = rudder_force(0.4, 6.0, 1.0, AREA, LIFT_SLOPE)[1]
        assert 0.0 < turning < straight

    def test_going_astern_the_helm_acts_the_other_way(self):
        ahead = rudder_force(0.3, 4.0, 0.0, AREA, LIFT_SLOPE)
        astern = rudder_force(0.3, -4.0, 0.0, AREA, LIFT_SLOPE)
        assert astern == pytest.approx((-ahead[0], -ahead[1]))

    def test_the_force_is_proportional_to_the_area_and_the_lift_slope(self):
        x, y = rudder_force(0.3, 6.0, 0.5, AREA, LIFT_SLOPE)
        assert rudder_force(0.3, 6.0, 0.5, 3.0 * AREA, LIFT_SLOPE) == pytest.approx((3.0 * x, 3.0 * y))
        assert rudder_force(0.3, 6.0, 0.5, AREA, 2.0 * LIFT_SLOPE) == pytest.approx((2.0 * x, 2.0 * y))
        assert rudder_force(0.3, 6.0, 0.5, 0.0, LIFT_SLOPE) == (0.0, 0.0)


class TestVectoredThrust:
    @pytest.mark.parametrize("angle", ANGLES)
    def test_the_thrust_points_along_the_turned_axis(self, angle):
        x, y = vectored_thrust_force(angle, 1000.0)
        assert (x, y) == pytest.approx((1000.0 * math.cos(angle), 1000.0 * math.sin(angle)))
        assert math.hypot(x, y) == pytest.approx(1000.0)

    @pytest.mark.parametrize("angle", ANGLES)
    def test_a_positive_helm_angle_pushes_the_stern_to_port(self, angle):
        x, y = vectored_thrust_force(angle, 1000.0)
        assert x > 0.0 and y > 0.0
        assert vectored_thrust_force(-angle, 1000.0) == pytest.approx((x, -y))

    def test_the_helm_amidships_gives_all_the_thrust_forward(self):
        assert vectored_thrust_force(0.0, 750.0) == (750.0, 0.0)

    @pytest.mark.parametrize("angle", [0.0] + ANGLES)
    def test_a_stopped_engine_does_not_steer(self, angle):
        assert vectored_thrust_force(angle, 0.0) == (0.0, 0.0)

    def test_reverse_thrust_steers_the_other_way(self):
        x, y = vectored_thrust_force(0.4, 500.0)
        assert vectored_thrust_force(0.4, -500.0) == pytest.approx((-x, -y))


class TestHullCoefficients:
    def test_the_surge_and_yaw_damping_are_left_to_the_caller(self):
        assert set(hydrodynamics()) == {"xDotU", "yDotV", "zDotW", "nDotR", "yV", "zW", "kP", "mQ", "yVabsV"}

    def test_every_coefficient_opposes_the_motion(self):
        for name, value in hydrodynamics().items():
            assert value < 0.0, name

    def test_surge_added_mass_is_a_share_of_the_displacement(self):
        assert hydrodynamics()["xDotU"] == pytest.approx(-0.05 * 332_000.0)

    def test_sway_heave_and_yaw_added_mass_come_from_strip_theory(self):
        coefficients = hydrodynamics(added_mass_cap=100.0)  # a cap that does not bite
        sway = 0.5 * RHO_WATER * math.pi * 1.8**2 * 30.0
        assert coefficients["yDotV"] == pytest.approx(-sway)
        assert coefficients["zDotW"] == pytest.approx(-0.5 * RHO_WATER * math.pi * 5.0**2 * 30.0)
        assert coefficients["nDotR"] == pytest.approx(-sway * 30.0**2 / 12.0)

    def test_added_mass_is_capped_below_the_rigid_body_value(self):
        coefficients = hydrodynamics(added_mass_cap=0.1)
        assert coefficients["yDotV"] == pytest.approx(-0.1 * 332_000.0)
        assert coefficients["zDotW"] == pytest.approx(-0.1 * 332_000.0)
        assert coefficients["nDotR"] == pytest.approx(-0.1 * 1.8e7)

    def test_sway_damping_is_clarkes_hull_lift_and_the_cross_flow_drag(self):
        coefficients = hydrodynamics()
        clarke = math.pi * (1.8 / 30.0) ** 2 * (1.0 + 0.40 * 0.6 * 10.0 / 1.8)
        assert coefficients["yV"] == pytest.approx(-0.5 * RHO_WATER * 30.0**2 * 10.0 * clarke)
        assert coefficients["yVabsV"] == pytest.approx(-0.5 * RHO_WATER * 1.0 * 30.0 * 1.8)

    def test_a_fuller_hull_resists_sway_more(self):
        assert hydrodynamics(block_coefficient=0.8)["yV"] < hydrodynamics(block_coefficient=0.5)["yV"]

    def test_heave_roll_and_pitch_are_damped_at_their_damping_ratio(self):
        coefficients = hydrodynamics()
        heave_stiffness = RHO_WATER * GRAVITY * 220.0
        assert coefficients["zW"] == pytest.approx(-2.0 * 0.5 * math.sqrt(heave_stiffness * (332_000.0 - coefficients["zDotW"])))
        assert coefficients["kP"] == pytest.approx(-2.0 * 0.3 * math.sqrt(332_000.0 * GRAVITY * 4.0 * 4.0e6))
        assert coefficients["mQ"] == pytest.approx(-2.0 * 0.3 * math.sqrt(332_000.0 * GRAVITY * 34.0 * 1.8e7))

    def test_an_unstable_hull_has_no_roll_damping_to_derive(self):
        with pytest.raises(ValueError):
            hydrodynamics(roll_metacentric_height=-1.0)
