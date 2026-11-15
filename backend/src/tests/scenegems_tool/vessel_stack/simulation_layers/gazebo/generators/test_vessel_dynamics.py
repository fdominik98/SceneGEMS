"""derive_vessel_dynamics: the parametric hull, its mass, thrusters and steering gear follow the vessel's dimensions, limits, block coefficient and steering type."""

import dataclasses
import math
from typing import Tuple

import pytest

from logical_level.mapping.vessel_type import VesselTypeMap
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.hull_form import HullForm, waterplane_coefficient_of
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.hydrodynamics import RHO_WATER, damping_force, rudder_force, surge_damping
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import (
    ASSUMPTION_KEYS,
    BUOYANCY_GRID,
    HULL_STATIONS,
    OVERRIDE_KEYS,
    VALUE_KEYS,
    DynamicsAssumptions,
    VesselDynamics,
    check_inertia,
    derive_vessel_dynamics,
    hull_stations,
    steady_turn,
    steady_turn_of,
)
from tests.scenegems_tool.vessel_stack.scenarios import make_vessel
from tests.scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessels import HELM_STEERING_TYPES, SCALES, STEERING_TYPES, scaled_vessel, steered, vessel_of_type

SHIPPED_TYPES = VesselTypeMap()
SHIPPED_VESSELS = sorted((name, float(length)) for name, vessel_type in SHIPPED_TYPES.items() if name is not None for length in {vessel_type.min_length, vessel_type.max_length})


@pytest.fixture(params=sorted(SCALES))
def scale(request) -> str:
    return request.param


@pytest.fixture(params=STEERING_TYPES)
def steering(request) -> str:
    return request.param


@pytest.fixture
def vessel(scale, steering):
    """Every scale with every steering type."""
    return scaled_vessel(scale, steering)


@pytest.fixture
def skid_vessel(scale):
    return scaled_vessel(scale, "skid")


@pytest.fixture(params=HELM_STEERING_TYPES)
def helm_vessel(request, scale):
    """A vessel steered by a helm angle: a rudder or a vectored thruster."""
    return scaled_vessel(scale, request.param)


def unturnable_vessel(steering_type: str = "rudder"):
    """300 m long with a design yaw rate of 0.1 rad/s: no rudder holds that turn at half the max speed."""
    return steered(make_vessel(0, True, length=300.0, max_speed=12.9, max_angular_speed=0.1 / 1.2, max_acceleration=0.05), steering_type)


def signed_damping(linear: float, quadratic: float, speed: float) -> float:
    return abs(linear) * speed + abs(quadratic) * speed * abs(speed)


def settle(d: VesselDynamics, helm_angle: float, thrust: float, steps: int = 15000) -> Tuple[float, float, float]:
    """(surge, sway, yaw rate) a hull settles at from a straight course at the steering speed, with the helm held at an angle.

    Explicit Euler over the surge and sway equations of steady_turn's docstring and the yaw
    equation of the model, with the added masses on the left:

        (m + |xDotU|) u' =  m v r + X - (|xU| u + |xUabsU| u|u|)
        (m + |yDotV|) v' = -m u r + Y - (|yV| v + |yVabsV| v|v|)
        (Izz + |nDotR|) r' = x_helm Y - (|nR| r + |nRabsR| r|r|)

    (X, Y) is the force of thrust and helm, with the helm's own sway v + x_helm r. The step is a
    twentieth of the shortest time constant the damping has up to the design speed and yaw rate.
    """
    mass = d.total_mass
    surge_mass, sway_mass, yaw_inertia = d.surge_mass, mass + abs(d.yDotV), d.yaw_inertia
    stiffest = max(
        (abs(d.xU) + 2.0 * abs(d.xUabsU) * d.design_speed) / surge_mass,
        (abs(d.yV) + 2.0 * abs(d.yVabsV) * d.design_speed) / sway_mass,
        (abs(d.nR) + 2.0 * abs(d.nRabsR) * d.design_yaw_rate) / yaw_inertia,
    )
    step = 0.05 / stiffest
    surge, sway, yaw_rate = d.steering_speed, 0.0, 0.0
    for _ in range(steps):
        x, y = d.helm_force(helm_angle, surge, sway + d.steering_x * yaw_rate, thrust)
        surge_rate = (mass * sway * yaw_rate + x - signed_damping(d.xU, d.xUabsU, surge)) / surge_mass
        sway_rate = (-mass * surge * yaw_rate + y - signed_damping(d.yV, d.yVabsV, sway)) / sway_mass
        yaw_acceleration = (d.steering_x * y - signed_damping(d.nR, d.nRabsR, yaw_rate)) / yaw_inertia
        surge, sway, yaw_rate = surge + step * surge_rate, sway + step * sway_rate, yaw_rate + step * yaw_acceleration
    return surge, sway, yaw_rate


class TestHull:
    def test_displacement_is_shared_by_hull_thrusters_steering_gear_and_windage(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        displacement = RHO_WATER * 0.6 * vessel.length * vessel.breadth * vessel.draft
        assert dynamics.total_mass == pytest.approx(displacement)
        parts = dynamics.hull_mass + dynamics.thruster_count * dynamics.thruster_mass + dynamics.steering_mass + dynamics.windage_mass
        assert parts == pytest.approx(displacement)
        assert min(dynamics.hull_mass, dynamics.thruster_mass, dynamics.windage_mass) > 0

    def test_only_a_vessel_with_a_helm_carries_steering_gear(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        if vessel.steering_type.value == "skid":
            assert dynamics.steering_mass == 0.0
        else:
            assert dynamics.steering_mass == pytest.approx(dynamics.thruster_mass)
            assert dynamics.steering_mass == pytest.approx(0.001 * dynamics.total_mass)

    def test_the_vessel_floats_at_its_design_draft(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        assert dynamics.floating_draft == pytest.approx(vessel.draft, rel=1e-9)

    def test_the_hull_form_is_the_vessels(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        assert dynamics.hull == HullForm.from_dimensions(vessel.length, vessel.breadth, vessel.draft, vessel.block_coefficient)
        assert (dynamics.length, dynamics.breadth, dynamics.height, dynamics.draft) == (vessel.length, vessel.breadth, vessel.height, vessel.draft)
        assert dynamics.steering_type == vessel.steering_type.value

    def test_the_buoyant_boxes_are_the_hulls_stations(self, vessel):
        """Replaces the single box shrunk by the block coefficient: nine boxes along the whole hull hold its volume and its waterplane."""
        dynamics = derive_vessel_dynamics(vessel)
        assert (dynamics.stations, dynamics.hull_x) == hull_stations(dynamics.hull, HULL_STATIONS)
        assert len(dynamics.stations) == HULL_STATIONS == 9
        assert sum(station.length for station in dynamics.stations) == pytest.approx(vessel.length)
        assert dynamics.displaced_volume == pytest.approx(0.6 * vessel.length * vessel.breadth * vessel.draft, rel=1e-12)
        assert dynamics.waterplane_area == pytest.approx(waterplane_coefficient_of(0.6) * vessel.length * vessel.breadth, rel=1e-12)
        assert RHO_WATER * dynamics.displaced_volume == pytest.approx(dynamics.total_mass)

    def test_the_buoyant_boxes_are_the_hulls_own_moved_along_the_model(self, vessel):
        """The hull's stations, origin amidships, keep their shape and lie hull_x further forward in the model's frame."""
        dynamics = derive_vessel_dynamics(vessel)
        for placed, own in zip(dynamics.stations, dynamics.hull.stations(HULL_STATIONS)):
            assert (placed.length, placed.breadth, placed.depth) == (own.length, own.breadth, own.depth)
            assert placed.x == pytest.approx(own.x + dynamics.hull_x)
        assert dynamics.stations[0].x - dynamics.stations[0].length / 2 == pytest.approx(-vessel.length / 2 + dynamics.hull_x), "the stern"
        assert dynamics.stations[-1].x + dynamics.stations[-1].length / 2 == pytest.approx(vessel.length / 2 + dynamics.hull_x), "the stem"

    def test_the_center_of_buoyancy_lies_at_the_models_origin(self, vessel):
        """Under the center of mass of the hull link, so the model floats on an even keel."""
        dynamics = derive_vessel_dynamics(vessel)
        moment = sum(station.volume * station.x for station in dynamics.stations)
        assert moment / dynamics.displaced_volume == pytest.approx(0.0, abs=1e-9 * vessel.length)

    def test_the_hulls_midship_lies_ahead_of_the_origin_by_its_own_center_of_buoyancy(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        own = dynamics.hull.stations(HULL_STATIONS)
        buoyancy_x = sum(station.volume * station.x for station in own) / sum(station.volume for station in own)
        assert dynamics.hull_x == pytest.approx(-buoyancy_x)
        assert buoyancy_x < 0 < dynamics.hull_x, "the bow is finer than the stern, so the center of buoyancy is aft of midship"
        assert 0.01 * vessel.length < dynamics.hull_x < 0.03 * vessel.length

    def test_the_hull_offset_does_not_depend_on_the_steering_type(self, scale):
        offsets = {derive_vessel_dynamics(scaled_vessel(scale, steering)).hull_x for steering in STEERING_TYPES}
        assert len(offsets) == 1

    def test_a_finer_hull_lies_further_ahead_of_the_origin_and_a_box_not_at_all(self):
        vessel = make_vessel(0, True)
        offsets = [derive_vessel_dynamics(dataclasses.replace(vessel, _block_coefficient=block)).hull_x for block in (0.4, 0.5, 0.6, 0.72, 0.82)]
        assert all(fuller < finer for finer, fuller in zip(offsets, offsets[1:]))
        assert offsets[-1] > 0
        box = derive_vessel_dynamics(vessel, overrides={"block_coefficient": 1.0})
        assert box.hull_x == pytest.approx(0.0, abs=1e-9)
        assert [station.x for station in box.stations] == pytest.approx([station.x for station in box.hull.stations(HULL_STATIONS)])

    @pytest.mark.parametrize("count", [1, 2, 9, 21, 24])
    def test_hull_stations_balance_any_cut_of_the_hull(self, count):
        """The finer cut under waves has its own center of buoyancy (a little off the one of nine boxes), and is placed by it."""
        hull = HullForm.from_dimensions(30.0, 10.0, 2.5, 0.5)
        stations, offset = hull_stations(hull, count)
        own = hull.stations(count)
        assert len(stations) == count
        assert sum(station.volume * station.x for station in stations) == pytest.approx(0.0, abs=1e-9 * hull.displaced_volume)
        assert offset == pytest.approx(-sum(station.volume * station.x for station in own) / hull.displaced_volume)
        assert [(station.length, station.breadth, station.depth) for station in stations] == [(station.length, station.breadth, station.depth) for station in own]
        assert [station.x for station in stations] == pytest.approx([station.x + offset for station in own])
        assert sum(station.volume for station in stations) == pytest.approx(hull.displaced_volume, rel=1e-12)
        if count > 1:
            assert offset > 0
        else:
            assert offset == 0.0, "one box has its center of buoyancy amidships"

    def test_the_cuts_of_one_hull_agree_on_its_center_of_buoyancy(self):
        """Within a thousandth of the length: the boxes sample the same sectional area curve."""
        hull = HullForm.from_dimensions(100.0, 33.0, 6.0, 0.6)
        offsets = [hull_stations(hull, count)[1] for count in (9, 21, 24)]
        assert max(offsets) - min(offsets) < 1e-3 * hull.length

    def test_the_buoyant_boxes_reach_from_the_keel_at_most_to_as_far_above_the_waterline(self, vessel):
        """Replaces the box of two drafts centered on the waterline: each box is centered on it and as deep as its part of the hull."""
        dynamics = derive_vessel_dynamics(vessel)
        assert dynamics.keel_z == pytest.approx(-vessel.draft)
        assert all(0 < station.depth <= vessel.draft for station in dynamics.stations)
        assert dynamics.reserve_depth == min(station.depth for station in dynamics.stations)
        assert 0.3 * vessel.draft < dynamics.reserve_depth < vessel.draft, "the vessel can sink this far before a box is under water"
        assert dynamics.reserve_depth < vessel.height - vessel.draft or vessel.height < 2 * vessel.draft

    def test_the_hull_is_stable_in_roll_and_pitch(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        assert dynamics.roll_metacentric_height > 0
        assert dynamics.pitch_metacentric_height > dynamics.roll_metacentric_height > 0

    def test_the_metacentric_heights_follow_the_boxes(self, vessel):
        """Center of buoyancy plus metacentric radius minus center of mass, each box split into three cells across the hull."""
        dynamics = derive_vessel_dynamics(vessel)
        volume = sum(station.volume for station in dynamics.stations)
        buoyancy_z = -sum(station.volume * station.depth / 2 for station in dynamics.stations) / volume
        cells = [(station.x, (cell - 1) * station.breadth / 3, station.length * station.breadth / 3) for station in dynamics.stations for cell in range(3)]
        roll_radius = sum(area * y**2 for _, y, area in cells) / volume
        pitch_radius = sum(area * x**2 for x, _, area in cells) / volume
        assert dynamics.roll_metacentric_height == pytest.approx(buoyancy_z + roll_radius - dynamics.com_z)
        assert dynamics.pitch_metacentric_height == pytest.approx(buoyancy_z + pitch_radius - dynamics.com_z)

    def test_the_inertia_follows_the_radii_of_gyration(self, vessel):
        """Replaces the inertia of the box: 0.35 of the breadth in roll, a quarter of the length in pitch and yaw."""
        dynamics = derive_vessel_dynamics(vessel)
        assert dynamics.hull_ixx == pytest.approx(dynamics.hull_mass * (0.35 * vessel.breadth) ** 2)
        assert dynamics.hull_iyy == pytest.approx(dynamics.hull_mass * (0.25 * vessel.length) ** 2)
        assert dynamics.hull_izz == dynamics.hull_iyy

    def test_inertia_satisfies_the_triangle_inequality(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        check_inertia("hull", dynamics.hull_ixx, dynamics.hull_iyy, dynamics.hull_izz)

    def test_center_of_mass_is_half_a_draft_below_the_waterline(self, vessel):
        assert derive_vessel_dynamics(vessel).com_z == pytest.approx(-vessel.draft / 2)

    def test_buoyancy_grid_is_nine_stations_of_three_cells(self):
        assert (HULL_STATIONS, BUOYANCY_GRID) == (9, 3)

    def test_the_steering_type_changes_neither_hull_nor_mass(self, scale):
        skid, rudder, vectored = (derive_vessel_dynamics(scaled_vessel(scale, steering)) for steering in STEERING_TYPES[1:2] + STEERING_TYPES[:1] + STEERING_TYPES[2:])
        assert skid.steering_type == "skid" and rudder.steering_type == "rudder" and vectored.steering_type == "vectored_thrust"
        for other in (rudder, vectored):
            assert other.hull == skid.hull and other.stations == skid.stations
            assert other.total_mass == pytest.approx(skid.total_mass)
            assert (other.xU, other.xUabsU, other.yV, other.yVabsV, other.zW) == (skid.xU, skid.xUabsU, skid.yV, skid.yVabsV, skid.zW)


class TestThrusters:
    def test_two_thrusters_side_by_side_for_skid_one_on_the_centerline_otherwise(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        assert dynamics.thruster_x == pytest.approx(-0.45 * vessel.length)
        assert dynamics.thruster_z == dynamics.com_z
        if vessel.steering_type.value == "skid":
            assert dynamics.thruster_count == 2
            assert dynamics.thruster_y == pytest.approx(0.4 * vessel.breadth)
        else:
            assert dynamics.thruster_count == 1
            assert dynamics.thruster_y == 0.0

    def test_full_thrust_balances_the_damping_at_the_design_speed(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        assert dynamics.total_thrust == pytest.approx(damping_force(dynamics.xU, dynamics.xUabsU, 1.2 * vessel.max_speed))
        assert dynamics.total_thrust == dynamics.thruster_count * dynamics.max_thrust

    def test_every_steering_type_has_the_same_total_thrust(self, scale):
        totals = [derive_vessel_dynamics(scaled_vessel(scale, steering)).total_thrust for steering in STEERING_TYPES]
        assert totals == pytest.approx([totals[0]] * 3)

    def test_design_speed_and_yaw_rate_have_a_twenty_percent_margin(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        assert dynamics.design_speed == pytest.approx(1.2 * vessel.max_speed)
        assert dynamics.design_yaw_rate == pytest.approx(1.2 * vessel.max_angular_speed)

    def test_the_surge_damping_is_the_resistance_of_the_hulls_wetted_surface(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        assert (dynamics.xU, dynamics.xUabsU) == surge_damping(dynamics.hull.wetted_surface, vessel.max_speed, 0.005, 0.2)
        resistance = 0.5 * RHO_WATER * 0.005 * dynamics.hull.wetted_surface * vessel.max_speed**2
        assert damping_force(dynamics.xU, dynamics.xUabsU, vessel.max_speed) == pytest.approx(resistance)

    def test_propeller_size_falls_back_to_the_draft_when_the_vessel_has_none(self, steering):
        vessel = dataclasses.replace(steered(make_vessel(0, True), steering), _propeller_diameter=0.0, _motor_length=0.0)
        dynamics = derive_vessel_dynamics(vessel)
        assert dynamics.propeller_diameter == pytest.approx(0.6 * vessel.draft)
        assert dynamics.motor_length == pytest.approx(1.5 * dynamics.propeller_diameter)

    def test_the_vessels_own_propeller_is_kept(self, steering):
        vessel = dataclasses.replace(steered(make_vessel(0, True), steering), _propeller_diameter=0.9, _motor_length=2.0)
        dynamics = derive_vessel_dynamics(vessel)
        assert (dynamics.propeller_diameter, dynamics.motor_length) == (0.9, 2.0)


class TestSkidSteering:
    def test_full_differential_thrust_balances_the_yaw_damping_at_the_design_yaw_rate(self, skid_vessel):
        dynamics = derive_vessel_dynamics(skid_vessel)
        moment = 2 * dynamics.max_thrust * dynamics.thruster_y
        assert moment == pytest.approx(damping_force(dynamics.nR, dynamics.nRabsR, dynamics.design_yaw_rate))
        assert dynamics.max_yaw_moment == pytest.approx(moment)
        assert dynamics.max_steady_yaw_rate == dynamics.design_yaw_rate

    def test_the_yaw_damping_is_a_fifth_linear_at_the_design_yaw_rate(self, skid_vessel):
        dynamics = derive_vessel_dynamics(skid_vessel)
        assert abs(dynamics.nR) * dynamics.design_yaw_rate == pytest.approx(0.2 * dynamics.max_yaw_moment)

    def test_a_skid_steered_vessel_has_no_steering_gear(self, skid_vessel):
        dynamics = derive_vessel_dynamics(skid_vessel)
        for field in ("steering_mass", "steering_x", "steering_z", "steering_max_angle", "steering_rate", "rudder_area", "rudder_span", "rudder_chord", "rudder_lift_slope"):
            assert getattr(dynamics, field) == 0.0, field

    def test_a_skid_steered_vessel_turns_at_rest(self, skid_vessel):
        dynamics = derive_vessel_dynamics(skid_vessel)
        assert dynamics.steering_speed == 0.0 and dynamics.steering_thrust == 0.0

    def test_a_skid_steered_vessel_has_no_helm_angle(self, skid_vessel):
        dynamics = derive_vessel_dynamics(skid_vessel)
        with pytest.raises(ValueError, match="a skid steered vessel has no helm angle"):
            dynamics.helm_force(0.1, 1.0, 0.0, 100.0)
        with pytest.raises(ValueError, match="a skid steered vessel has no helm angle"):
            dynamics.helm_moment(0.1, 1.0, 100.0)


class TestSteeringGear:
    def test_the_helm_is_calibrated_at_half_the_max_speed(self, helm_vessel):
        dynamics = derive_vessel_dynamics(helm_vessel)
        assert dynamics.steering_speed == pytest.approx(0.5 * helm_vessel.max_speed)
        assert dynamics.steering_thrust == pytest.approx(damping_force(dynamics.xU, dynamics.xUabsU, dynamics.steering_speed))
        assert 0 < dynamics.steering_thrust < dynamics.total_thrust

    def test_the_steering_thrust_holds_the_steering_speed_on_a_straight_course(self, helm_vessel):
        dynamics = derive_vessel_dynamics(helm_vessel)
        surge, sway, yaw_rate = settle(dynamics, 0.0, dynamics.steering_thrust, steps=2000)
        assert surge == pytest.approx(dynamics.steering_speed, rel=1e-9)
        assert (sway, yaw_rate) == (0.0, 0.0)

    def test_the_steering_thrust_never_exceeds_the_full_thrust(self):
        dynamics = derive_vessel_dynamics(steered(make_vessel(0, True), "rudder"), overrides={"steering_speed_share": 1.5})
        assert dynamics.steering_speed == pytest.approx(1.5 * 20.57778)
        assert dynamics.steering_thrust == dynamics.total_thrust

    def test_a_rudder_sits_at_the_stern_below_the_waterline(self, scale):
        vessel = scaled_vessel(scale, "rudder")
        dynamics = derive_vessel_dynamics(vessel)
        assert dynamics.rudder_area == pytest.approx(0.02 * vessel.length * vessel.draft)
        assert dynamics.rudder_span == pytest.approx(0.7 * vessel.draft)
        assert dynamics.rudder_chord * dynamics.rudder_span == pytest.approx(dynamics.rudder_area)
        assert dynamics.rudder_lift_slope == 2.5
        assert dynamics.steering_x == pytest.approx(-0.485 * vessel.length)
        assert dynamics.steering_x < dynamics.thruster_x < 0, "behind the propeller"
        assert dynamics.steering_z - dynamics.rudder_span / 2 == pytest.approx(-vessel.draft), "its foot at the keel"
        assert dynamics.steering_max_angle == pytest.approx(math.radians(35.0))

    def test_a_vectored_thruster_turns_where_it_sits(self, scale):
        dynamics = derive_vessel_dynamics(scaled_vessel(scale, "vectored_thrust"))
        assert (dynamics.steering_x, dynamics.steering_z) == (dynamics.thruster_x, dynamics.thruster_z)
        assert dynamics.steering_max_angle == pytest.approx(math.radians(30.0))
        assert (dynamics.rudder_area, dynamics.rudder_span, dynamics.rudder_chord, dynamics.rudder_lift_slope) == (0.0, 0.0, 0.0, 0.0)

    def test_the_helm_goes_hard_over_to_hard_over_while_the_vessel_turns_thirty_degrees(self, helm_vessel):
        """At its max turn rate; a slow turning vessel keeps the least helm speed of its gear."""
        dynamics = derive_vessel_dynamics(helm_vessel)
        least = math.radians(5.0 if dynamics.steering_type == "rudder" else 15.0)
        wanted = 2 * dynamics.steering_max_angle * helm_vessel.max_angular_speed / math.radians(30.0)
        assert dynamics.steering_rate == pytest.approx(max(least, wanted))
        travel_time = 2 * dynamics.steering_max_angle / dynamics.steering_rate
        assert travel_time * helm_vessel.max_angular_speed <= math.radians(30.0) * (1 + 1e-9)

    def test_the_helm_rate_rule_has_both_cases(self):
        slow = derive_vessel_dynamics(scaled_vessel("100m", "rudder"))  # 0.008 rad/s: the least helm speed
        fast = derive_vessel_dynamics(scaled_vessel("5m", "rudder"))  # 0.5 rad/s: the helm keeps up with the turn
        assert slow.steering_rate == pytest.approx(math.radians(5.0))
        assert fast.steering_rate == pytest.approx(2 * math.radians(35.0) * 0.5 / (math.pi / 6))
        assert fast.steering_rate > math.radians(5.0)

    def test_the_least_helm_speed_can_be_overridden(self):
        vessel = scaled_vessel("100m", "rudder")
        assert derive_vessel_dynamics(vessel, overrides={"rudder_rate_deg_s": 2.0}).steering_rate == pytest.approx(math.radians(2.0))
        assert derive_vessel_dynamics(steered(vessel, "vectored_thrust"), overrides={"vectored_rate_deg_s": 20.0}).steering_rate == pytest.approx(math.radians(20.0))

    def test_the_max_helm_angle_can_be_overridden(self):
        vessel = scaled_vessel("30m", "rudder")
        assert derive_vessel_dynamics(vessel, overrides={"rudder_max_angle_deg": 25.0}).steering_max_angle == pytest.approx(math.radians(25.0))
        assert derive_vessel_dynamics(steered(vessel, "vectored_thrust"), overrides={"vectored_max_angle_deg": 45.0}).steering_max_angle == pytest.approx(math.radians(45.0))


class TestHelmForce:
    """Body frame x forward, y to port, yaw counterclockwise: a positive helm angle turns the vessel to starboard."""

    def test_a_positive_helm_angle_turns_to_starboard(self, helm_vessel):
        dynamics = derive_vessel_dynamics(helm_vessel)
        angle, speed, thrust = 0.5 * dynamics.steering_max_angle, dynamics.steering_speed, dynamics.steering_thrust
        _, side_force = dynamics.helm_force(angle, speed, 0.0, thrust)
        assert side_force > 0, "the stern is pushed to port"
        assert dynamics.helm_moment(angle, speed, thrust) < 0, "which turns the vessel clockwise"
        assert dynamics.helm_moment(angle, speed, thrust) == pytest.approx(dynamics.steering_x * side_force)

    def test_a_negative_helm_angle_turns_to_port_just_as_hard(self, helm_vessel):
        dynamics = derive_vessel_dynamics(helm_vessel)
        angle, speed, thrust = 0.5 * dynamics.steering_max_angle, dynamics.steering_speed, dynamics.steering_thrust
        assert dynamics.helm_moment(-angle, speed, thrust) > 0
        assert dynamics.helm_moment(-angle, speed, thrust) == pytest.approx(-dynamics.helm_moment(angle, speed, thrust))
        assert dynamics.helm_force(-angle, speed, 0.0, thrust)[0] == pytest.approx(dynamics.helm_force(angle, speed, 0.0, thrust)[0])

    def test_the_helm_amidships_gives_the_thrust_and_no_moment(self, helm_vessel):
        dynamics = derive_vessel_dynamics(helm_vessel)
        assert dynamics.helm_force(0.0, dynamics.steering_speed, 0.0, dynamics.steering_thrust) == pytest.approx((dynamics.steering_thrust, 0.0))
        assert dynamics.helm_moment(0.0, dynamics.steering_speed, dynamics.steering_thrust) == 0.0

    def test_more_helm_turns_harder_up_to_hard_over(self, helm_vessel):
        dynamics = derive_vessel_dynamics(helm_vessel)
        moments = [abs(dynamics.helm_moment(share * dynamics.steering_max_angle, dynamics.steering_speed, dynamics.steering_thrust)) for share in (0.25, 0.5, 0.75, 1.0)]
        assert all(later > earlier for earlier, later in zip(moments, moments[1:]))
        assert dynamics.max_yaw_moment == pytest.approx(moments[-1])

    def test_a_rudder_adds_its_force_to_the_thrust(self, scale):
        dynamics = derive_vessel_dynamics(scaled_vessel(scale, "rudder"))
        angle, speed, sway = 0.3, dynamics.steering_speed, -0.1 * dynamics.steering_speed
        drag, side_force = rudder_force(angle, speed, sway, dynamics.rudder_area, dynamics.rudder_lift_slope)
        assert dynamics.helm_force(angle, speed, sway, 1234.0) == pytest.approx((1234.0 + drag, side_force))
        assert drag < 0

    def test_a_rudder_steers_by_the_speed_and_not_at_rest(self, scale):
        dynamics = derive_vessel_dynamics(scaled_vessel(scale, "rudder"))
        angle = dynamics.steering_max_angle
        assert dynamics.helm_moment(angle, 0.0, dynamics.total_thrust) == 0.0, "no propeller wash on the rudder"
        slow = dynamics.helm_moment(angle, dynamics.steering_speed, 0.0)
        fast = dynamics.helm_moment(angle, 2 * dynamics.steering_speed, 0.0)
        assert slow != 0 and fast == pytest.approx(4 * slow), "with the square of the speed, with or without thrust"
        gain = 0.5 * RHO_WATER * dynamics.rudder_area * dynamics.rudder_lift_slope
        assert slow == pytest.approx(dynamics.steering_x * gain * dynamics.steering_speed**2 * math.sin(angle) * math.cos(angle) ** 2)

    def test_a_vectored_thruster_steers_by_its_thrust_and_not_with_the_engine_stopped(self, scale):
        dynamics = derive_vessel_dynamics(scaled_vessel(scale, "vectored_thrust"))
        angle, thrust = dynamics.steering_max_angle, dynamics.steering_thrust
        assert dynamics.helm_force(angle, 0.0, 0.0, thrust) == pytest.approx((thrust * math.cos(angle), thrust * math.sin(angle)))
        assert dynamics.helm_moment(angle, 0.0, thrust) == pytest.approx(dynamics.steering_x * thrust * math.sin(angle)), "at rest too"
        assert dynamics.helm_moment(angle, dynamics.steering_speed, thrust) == dynamics.helm_moment(angle, 0.0, thrust), "whatever the speed"
        assert dynamics.helm_moment(angle, dynamics.steering_speed, 0.0) == 0.0
        assert dynamics.helm_moment(angle, dynamics.steering_speed, 2 * thrust) == pytest.approx(2 * dynamics.helm_moment(angle, dynamics.steering_speed, thrust))


class TestSteadyTurn:
    """The yaw damping of a vessel with a helm is calibrated on the turn it settles in, drift included."""

    def test_the_helm_hard_over_settles_at_the_max_steady_yaw_rate(self, helm_vessel):
        dynamics = derive_vessel_dynamics(helm_vessel)
        surge, sway, yaw_rate = settle(dynamics, -dynamics.steering_max_angle, dynamics.steering_thrust)
        assert yaw_rate == pytest.approx(dynamics.max_steady_yaw_rate, rel=1e-3), "hard over to port: counterclockwise"
        assert sway < 0, "the hull slides outward, to starboard"
        assert surge < dynamics.steering_speed, "and the turn slows it down"

    def test_hard_over_to_starboard_is_the_mirror_image(self, helm_vessel):
        dynamics = derive_vessel_dynamics(helm_vessel)
        port = settle(dynamics, -dynamics.steering_max_angle, dynamics.steering_thrust)
        starboard = settle(dynamics, dynamics.steering_max_angle, dynamics.steering_thrust)
        assert starboard == pytest.approx((port[0], -port[1], -port[2]))
        assert starboard[2] == pytest.approx(-dynamics.max_steady_yaw_rate, rel=1e-3)

    def test_half_the_helm_turns_slower(self, helm_vessel):
        dynamics = derive_vessel_dynamics(helm_vessel)
        _, _, yaw_rate = settle(dynamics, -0.5 * dynamics.steering_max_angle, dynamics.steering_thrust)
        assert 0.2 * dynamics.max_steady_yaw_rate < yaw_rate < 0.9 * dynamics.max_steady_yaw_rate

    @pytest.mark.parametrize("scale_name", ["30m", "100m"])
    @pytest.mark.parametrize("steering_type", HELM_STEERING_TYPES)
    def test_a_helm_that_can_hold_the_design_yaw_rate_reaches_it(self, scale_name, steering_type):
        dynamics = derive_vessel_dynamics(scaled_vessel(scale_name, steering_type))
        assert dynamics.max_steady_yaw_rate == dynamics.design_yaw_rate
        _, _, yaw_rate = settle(dynamics, -dynamics.steering_max_angle, dynamics.steering_thrust)
        assert yaw_rate == pytest.approx(dynamics.design_yaw_rate, rel=1e-3)

    def test_a_vectored_thruster_always_holds_the_design_yaw_rate(self, scale):
        """Its turning force does not depend on the hull's motion, so the yaw damping is its full moment at the design yaw rate."""
        dynamics = derive_vessel_dynamics(scaled_vessel(scale, "vectored_thrust"))
        assert dynamics.max_steady_yaw_rate == dynamics.design_yaw_rate
        assert damping_force(dynamics.nR, dynamics.nRabsR, dynamics.design_yaw_rate) == pytest.approx(dynamics.max_yaw_moment)

    def test_a_rudder_loses_moment_to_the_drift_of_the_turn(self):
        """The yaw damping holds what the rudder still gives in the turn, less than its moment on a straight course."""
        dynamics = derive_vessel_dynamics(scaled_vessel("30m", "rudder"))
        in_the_turn = damping_force(dynamics.nR, dynamics.nRabsR, dynamics.design_yaw_rate)
        assert 0.05 * dynamics.max_yaw_moment < in_the_turn < dynamics.max_yaw_moment

    def test_the_yaw_damping_is_a_fifth_linear_at_the_design_yaw_rate(self, helm_vessel):
        dynamics = derive_vessel_dynamics(helm_vessel)
        assert abs(dynamics.nR) * dynamics.design_yaw_rate == pytest.approx(0.2 * damping_force(dynamics.nR, dynamics.nRabsR, dynamics.design_yaw_rate))
        assert dynamics.nR < 0 and dynamics.nRabsR < 0

    def test_steady_turn_balances_surge_sway_and_yaw(self, helm_vessel):
        """The solution fulfils the two equations of its docstring, and its helm moment is what the yaw damping takes at that rate."""
        dynamics = derive_vessel_dynamics(helm_vessel)
        mass, rate, thrust = dynamics.total_mass, dynamics.max_steady_yaw_rate, dynamics.steering_thrust

        def helm_force(surge: float, sway_at_helm: float) -> Tuple[float, float]:
            return dynamics.helm_force(-dynamics.steering_max_angle, surge, sway_at_helm, thrust)

        surge, sway, moment = steady_turn(rate, helm_force, mass, (dynamics.xU, dynamics.xUabsU), (dynamics.yV, dynamics.yVabsV), dynamics.steering_x, dynamics.design_speed)
        x, y = helm_force(surge, sway + dynamics.steering_x * rate)
        assert mass * sway * rate + x - signed_damping(dynamics.xU, dynamics.xUabsU, surge) == pytest.approx(0.0, abs=1e-6 * thrust)
        assert -mass * surge * rate + y - signed_damping(dynamics.yV, dynamics.yVabsV, sway) == pytest.approx(0.0, abs=1e-6 * thrust)
        assert moment == pytest.approx(dynamics.steering_x * y)
        assert moment == pytest.approx(damping_force(dynamics.nR, dynamics.nRabsR, rate), rel=1e-5)
        assert (surge, sway) == pytest.approx(settle(dynamics, -dynamics.steering_max_angle, thrust)[:2], rel=1e-3)

    def test_steady_turn_without_a_turn_is_the_straight_course(self):
        dynamics = derive_vessel_dynamics(scaled_vessel("30m", "rudder"))

        def helm_force(surge: float, sway_at_helm: float) -> Tuple[float, float]:
            return dynamics.helm_force(0.0, surge, sway_at_helm, dynamics.steering_thrust)

        surge, sway, moment = steady_turn(0.0, helm_force, dynamics.total_mass, (dynamics.xU, dynamics.xUabsU), (dynamics.yV, dynamics.yVabsV), dynamics.steering_x, dynamics.design_speed)
        assert surge == pytest.approx(dynamics.steering_speed, rel=1e-6)
        assert sway == pytest.approx(0.0, abs=1e-6) and moment == pytest.approx(0.0, abs=1e-6 * dynamics.max_yaw_moment)


class TestTurningCircle:
    """A measured turning circle in place of the design yaw rate (turn_diameter_ratio, turn_speed), and steady_turn_of."""

    def test_steady_turn_of_is_the_turn_the_hull_settles_in(self, helm_vessel):
        dynamics = derive_vessel_dynamics(helm_vessel)
        surge, sway, yaw_rate = steady_turn_of(dynamics)
        assert yaw_rate == pytest.approx(dynamics.max_steady_yaw_rate, rel=1e-4)
        assert (surge, sway, yaw_rate) == pytest.approx(settle(dynamics, -dynamics.steering_max_angle, dynamics.steering_thrust), rel=1e-3)

    def test_steady_turn_of_at_another_speed_takes_the_thrust_that_holds_it(self):
        dynamics = derive_vessel_dynamics(scaled_vessel("30m", "rudder"))
        speed = 0.8 * dynamics.steering_speed
        thrust = damping_force(dynamics.xU, dynamics.xUabsU, speed)
        assert steady_turn_of(dynamics, speed) == pytest.approx(settle(dynamics, -dynamics.steering_max_angle, thrust), rel=1e-3)
        assert steady_turn_of(dynamics, speed)[2] < dynamics.max_steady_yaw_rate, "a slower rudder turns slower"

    def test_a_skid_steered_vessel_has_no_steady_turn_of_a_helm(self, skid_vessel):
        with pytest.raises(ValueError, match="a skid steered vessel has no helm to put hard over"):
            steady_turn_of(derive_vessel_dynamics(skid_vessel))

    @pytest.mark.parametrize("scale_name,steering_type,ratio", [("30m", "rudder", 4.0), ("100m", "rudder", 3.0), ("30m", "vectored_thrust", 5.0)])
    def test_the_hull_turns_on_the_given_diameter_at_the_trial_speed(self, scale_name, steering_type, ratio):
        vessel = scaled_vessel(scale_name, steering_type)
        turn_speed = 0.6 * vessel.max_speed
        dynamics = derive_vessel_dynamics(vessel, overrides={"turn_diameter_ratio": ratio, "turn_speed": turn_speed})
        thrust = damping_force(dynamics.xU, dynamics.xUabsU, turn_speed)
        surge, sway, yaw_rate = settle(dynamics, -dynamics.steering_max_angle, thrust, steps=30000)
        assert 2.0 * math.hypot(surge, sway) / yaw_rate == pytest.approx(ratio * vessel.length, rel=2e-3)
        assert dynamics.nR < 0 and dynamics.nRabsR < 0

    def test_without_a_trial_speed_the_turn_is_entered_at_the_steering_speed(self):
        vessel = scaled_vessel("30m", "rudder")
        dynamics = derive_vessel_dynamics(vessel, overrides={"turn_diameter_ratio": 4.0})
        surge, sway, yaw_rate = settle(dynamics, -dynamics.steering_max_angle, dynamics.steering_thrust, steps=30000)
        assert 2.0 * math.hypot(surge, sway) / yaw_rate == pytest.approx(4.0 * vessel.length, rel=2e-3)
        assert yaw_rate == pytest.approx(dynamics.max_steady_yaw_rate, rel=1e-3), "the same turn the max steady yaw rate tells"

    def test_the_max_steady_yaw_rate_is_what_the_helm_reaches_at_the_steering_thrust(self):
        vessel = scaled_vessel("30m", "rudder")
        dynamics = derive_vessel_dynamics(vessel, overrides={"turn_diameter_ratio": 4.0, "turn_speed": 0.8 * vessel.max_speed})
        assert settle(dynamics, -dynamics.steering_max_angle, dynamics.steering_thrust, steps=30000)[2] == pytest.approx(dynamics.max_steady_yaw_rate, rel=1e-3)
        assert dynamics.max_steady_yaw_rate != dynamics.design_yaw_rate, "the turning circle replaces the design yaw rate"

    def test_a_wider_circle_needs_more_yaw_damping(self):
        vessel = scaled_vessel("30m", "rudder")
        tight = derive_vessel_dynamics(vessel, overrides={"turn_diameter_ratio": 3.0})
        wide = derive_vessel_dynamics(vessel, overrides={"turn_diameter_ratio": 6.0})
        assert damping_force(wide.nR, wide.nRabsR, 0.02) > damping_force(tight.nR, tight.nRabsR, 0.02)
        assert wide.max_steady_yaw_rate < tight.max_steady_yaw_rate

    def test_no_turning_circle_keeps_the_design_yaw_rate(self):
        vessel = scaled_vessel("30m", "rudder")
        assert derive_vessel_dynamics(vessel, overrides={"turn_diameter_ratio": 0.0, "turn_speed": 5.0}) == derive_vessel_dynamics(vessel)
        assert (DynamicsAssumptions().turn_diameter_ratio, DynamicsAssumptions().turn_speed) == (0.0, 0.0)


class TestATurnTheRudderCannotHold:
    """A long ship with a high turn rate: the rudder loses its angle of attack before the hull turns that fast."""

    def test_the_max_steady_yaw_rate_falls_short_of_the_design_yaw_rate(self):
        dynamics = derive_vessel_dynamics(unturnable_vessel())
        assert dynamics.design_yaw_rate == pytest.approx(0.1)
        assert 0 < dynamics.max_steady_yaw_rate < 0.5 * dynamics.design_yaw_rate

    def test_the_hull_keeps_the_least_yaw_damping(self):
        dynamics = derive_vessel_dynamics(unturnable_vessel())
        assert damping_force(dynamics.nR, dynamics.nRabsR, dynamics.design_yaw_rate) == pytest.approx(0.05 * dynamics.max_yaw_moment)
        assert dynamics.nR < 0 and dynamics.nRabsR < 0

    def test_the_least_yaw_damping_can_be_overridden(self):
        vessel = unturnable_vessel()
        stiffer = derive_vessel_dynamics(vessel, overrides={"min_yaw_damping_share": 0.2})
        assert damping_force(stiffer.nR, stiffer.nRabsR, stiffer.design_yaw_rate) == pytest.approx(0.2 * stiffer.max_yaw_moment)
        assert stiffer.max_steady_yaw_rate < derive_vessel_dynamics(vessel).max_steady_yaw_rate

    def test_the_helm_hard_over_settles_at_what_the_rudder_does_hold(self):
        dynamics = derive_vessel_dynamics(unturnable_vessel())
        _, _, yaw_rate = settle(dynamics, -dynamics.steering_max_angle, dynamics.steering_thrust)
        assert yaw_rate == pytest.approx(dynamics.max_steady_yaw_rate, rel=1e-3)

    def test_the_model_is_still_valid(self):
        dynamics = derive_vessel_dynamics(unturnable_vessel())
        check_inertia("hull", dynamics.hull_ixx, dynamics.hull_iyy, dynamics.hull_izz)
        assert dynamics.floating_draft == pytest.approx(dynamics.draft)
        assert dynamics.roll_metacentric_height > 0
        assert dynamics.steering_rate > 0 and dynamics.steering_max_angle > 0 and dynamics.max_thrust > 0
        for name in ("xDotU", "yDotV", "zDotW", "nDotR", "xU", "yV", "zW", "kP", "mQ", "nR", "xUabsU", "yVabsV", "nRabsR"):
            assert getattr(dynamics, name) < 0, name

    def test_the_same_vessel_holds_the_turn_with_skid_steering_or_vectored_thrust(self):
        for steering_type in ("skid", "vectored_thrust"):
            dynamics = derive_vessel_dynamics(unturnable_vessel(steering_type))
            assert dynamics.max_steady_yaw_rate == dynamics.design_yaw_rate

    def test_a_faster_steering_speed_gives_the_rudder_more_to_turn_with(self):
        vessel = unturnable_vessel()
        assert derive_vessel_dynamics(vessel, overrides={"steering_speed_share": 1.0}).max_steady_yaw_rate > derive_vessel_dynamics(vessel).max_steady_yaw_rate


class TestHydrodynamics:
    def test_every_coefficient_opposes_the_motion(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        for name in ("xDotU", "yDotV", "zDotW", "nDotR", "xU", "yV", "zW", "kP", "mQ", "nR", "xUabsU", "yVabsV", "nRabsR"):
            assert getattr(dynamics, name) < 0, name

    def test_added_mass_stays_below_the_rigid_body_value(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        displacement = dynamics.total_mass
        assert -dynamics.yDotV <= 0.5 * displacement + 1e-6
        assert -dynamics.zDotW <= 0.5 * displacement + 1e-6
        assert -dynamics.nDotR <= 0.5 * dynamics.hull_izz + 1e-6

    def test_yaw_inertia_and_surge_mass_include_the_added_mass(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        assert dynamics.yaw_inertia == pytest.approx(dynamics.hull_izz - dynamics.nDotR)
        assert dynamics.surge_mass == pytest.approx(dynamics.total_mass - dynamics.xDotU)
        assert dynamics.surge_mass == pytest.approx(1.05 * dynamics.total_mass)


class TestShippedVesselTypes:
    """Vessels as the scene builder makes them from the shipped vessel types, at the shortest and the longest of each type."""

    @pytest.mark.parametrize("type_name,length", SHIPPED_VESSELS)
    def test_every_shipped_vessel_type_gives_a_valid_model(self, type_name, length):
        vessel_type = SHIPPED_TYPES[type_name]
        vessel = vessel_of_type(vessel_type, length)
        dynamics = derive_vessel_dynamics(vessel, overrides={})
        assert dynamics.steering_type == vessel_type.steering_type
        assert dynamics.hull.block_coefficient == vessel_type.block_coefficient
        assert dynamics.total_mass == pytest.approx(RHO_WATER * vessel_type.block_coefficient * vessel.length * vessel.breadth * vessel.draft)
        assert dynamics.floating_draft == pytest.approx(vessel.draft, rel=1e-9)
        assert dynamics.roll_metacentric_height > 0 and dynamics.pitch_metacentric_height > 0
        check_inertia("hull", dynamics.hull_ixx, dynamics.hull_iyy, dynamics.hull_izz)
        assert 0 < dynamics.max_steady_yaw_rate <= dynamics.design_yaw_rate
        assert dynamics.thruster_count == (2 if vessel_type.steering_type == "skid" else 1)
        assert sum(station.volume * station.x for station in dynamics.stations) / dynamics.displaced_volume == pytest.approx(0.0, abs=1e-9 * vessel.length), "on an even keel"
        assert 0 < dynamics.hull_x < 0.03 * vessel.length

    @pytest.mark.parametrize("type_name,length", SHIPPED_VESSELS)
    @pytest.mark.parametrize("steering_type", STEERING_TYPES)
    def test_every_shipped_hull_takes_every_steering_type(self, type_name, length, steering_type):
        dynamics = derive_vessel_dynamics(steered(vessel_of_type(SHIPPED_TYPES[type_name], length), steering_type), overrides={})
        assert dynamics.steering_type == steering_type
        assert dynamics.floating_draft == pytest.approx(dynamics.draft, rel=1e-9)
        if steering_type != "rudder":
            assert dynamics.max_steady_yaw_rate == dynamics.design_yaw_rate

    def test_the_shipped_types_cover_rudder_and_skid_steering(self):
        steering_types = {vessel_type.steering_type for vessel_type in SHIPPED_TYPES.values()}
        assert {"rudder", "skid"} <= steering_types
        assert SHIPPED_TYPES["MiniUSV"].steering_type == "skid" and SHIPPED_TYPES["CargoShip"].steering_type == "rudder"


class TestBlockCoefficient:
    def test_the_block_coefficient_comes_from_the_vessel(self, steering):
        vessel = steered(make_vessel(0, True), steering)
        fuller = dataclasses.replace(vessel, _block_coefficient=0.75)
        base, dynamics = derive_vessel_dynamics(vessel), derive_vessel_dynamics(fuller)
        assert dynamics.hull.block_coefficient == 0.75 and base.hull.block_coefficient == 0.6
        assert dynamics.total_mass == pytest.approx(base.total_mass * 0.75 / 0.6)
        assert dynamics.total_mass == pytest.approx(RHO_WATER * 0.75 * vessel.length * vessel.breadth * vessel.draft)
        assert dynamics.floating_draft == pytest.approx(vessel.draft)

    def test_an_override_wins_over_the_vessels_block_coefficient(self, steering):
        fuller = dataclasses.replace(steered(make_vessel(0, True), steering), _block_coefficient=0.75)
        dynamics = derive_vessel_dynamics(fuller, overrides={"block_coefficient": 0.5})
        assert dynamics.hull.block_coefficient == 0.5
        assert dynamics.total_mass == pytest.approx(RHO_WATER * 0.5 * fuller.length * fuller.breadth * fuller.draft)

    def test_a_fuller_hull_is_wider_at_the_waterline_and_has_more_wetted_surface(self):
        vessel = make_vessel(0, True)
        fine = derive_vessel_dynamics(dataclasses.replace(vessel, _block_coefficient=0.45))
        full = derive_vessel_dynamics(dataclasses.replace(vessel, _block_coefficient=0.8))
        assert full.waterplane_area > fine.waterplane_area
        assert full.hull.wetted_surface > fine.hull.wetted_surface
        assert full.total_thrust > fine.total_thrust, "more wetted surface, more resistance"

    def test_midship_and_waterplane_coefficients_can_be_overridden(self):
        vessel = make_vessel(0, True)
        dynamics = derive_vessel_dynamics(vessel, overrides={"midship_coefficient": 0.9, "waterplane_coefficient": 0.8})
        assert (dynamics.hull.midship_coefficient, dynamics.hull.waterplane_coefficient) == (0.9, 0.8)
        assert dynamics.waterplane_area == pytest.approx(0.8 * vessel.length * vessel.breadth)
        assert dynamics.floating_draft == pytest.approx(vessel.draft)

    def test_the_assumptions_default_to_coefficients_derived_from_the_block_coefficient(self):
        assert (DynamicsAssumptions().midship_coefficient, DynamicsAssumptions().waterplane_coefficient) == (0.0, 0.0)


class TestOverrides:
    def test_assumption_override_flows_into_the_derivation(self):
        vessel = make_vessel(0, True)
        base = derive_vessel_dynamics(vessel)
        denser = derive_vessel_dynamics(vessel, overrides={"block_coefficient": 0.75})
        assert denser.total_mass == pytest.approx(base.total_mass * 0.75 / 0.6)
        assert denser.floating_draft == pytest.approx(vessel.draft)

    def test_value_override_replaces_only_that_value(self, steering):
        vessel = steered(make_vessel(0, True), steering)
        base = derive_vessel_dynamics(vessel)
        changed = derive_vessel_dynamics(vessel, overrides={"max_thrust": 12345.0})
        assert changed.max_thrust == 12345.0
        assert changed == dataclasses.replace(base, max_thrust=12345.0), "nothing derived from it is recomputed"
        assert (changed.nR, changed.nRabsR, changed.max_steady_yaw_rate) == (base.nR, base.nRabsR, base.max_steady_yaw_rate)

    @pytest.mark.parametrize("key", ["steering_x", "steering_rate", "steering_max_angle", "rudder_area", "max_steady_yaw_rate", "nR", "hull_izz", "windage_z"])
    def test_any_derived_value_can_be_replaced_alone(self, key):
        vessel = steered(make_vessel(0, True), "rudder")
        base = derive_vessel_dynamics(vessel)
        value = 1.1 * getattr(base, key)
        assert derive_vessel_dynamics(vessel, overrides={key: value}) == dataclasses.replace(base, **{key: value})

    def test_overriding_the_hull_mass_changes_the_floating_draft(self):
        vessel = make_vessel(0, True)
        base = derive_vessel_dynamics(vessel)
        heavier = derive_vessel_dynamics(vessel, overrides={"hull_mass": base.hull_mass * 1.1})
        assert heavier.floating_draft > base.floating_draft
        sinkage = 0.1 * base.hull_mass / RHO_WATER / base.waterplane_area
        assert heavier.floating_draft == pytest.approx(vessel.draft + sinkage), "the boxes are wall sided"

    def test_unknown_key_is_rejected_with_the_vessel(self):
        with pytest.raises(ValueError, match=r"vessel 0 \(OSPassengerShip\): unknown vessel dynamics keys \['colour'\]"):
            derive_vessel_dynamics(make_vessel(0, True), overrides={"colour": 1.0})

    @pytest.mark.parametrize("key", ["collision_length", "collision_breadth", "collision_height", "collision_z"])
    def test_the_keys_of_the_former_box_hull_are_unknown(self, key):
        with pytest.raises(ValueError, match="unknown vessel dynamics keys"):
            derive_vessel_dynamics(make_vessel(0, True), overrides={key: 1.0})

    @pytest.mark.parametrize("key", ["length", "steering_type", "stations", "hull", "hull_x", "thruster_count", "design_speed", "design_yaw_rate", "steering_speed"])
    def test_fixed_values_cannot_be_overridden(self, key):
        with pytest.raises(ValueError, match="unknown vessel dynamics keys"):
            derive_vessel_dynamics(make_vessel(0, True), overrides={key: 1.0})

    def test_keys_are_assumptions_plus_values(self):
        assert OVERRIDE_KEYS == ASSUMPTION_KEYS | VALUE_KEYS
        assert not ASSUMPTION_KEYS & VALUE_KEYS

    def test_the_keys_cover_the_steering_gear(self):
        assert {"block_coefficient", "midship_coefficient", "waterplane_coefficient", "steering_speed_share", "min_yaw_damping_share", "rudder_area_ratio", "rudder_lift_slope"} <= ASSUMPTION_KEYS
        assert {"steering_mass", "steering_x", "steering_z", "steering_max_angle", "steering_rate", "rudder_area", "rudder_span", "rudder_chord", "max_steady_yaw_rate"} <= VALUE_KEYS

    def test_the_rudders_lift_slope_is_an_assumption_the_derivation_follows(self):
        """The assumption and the derived value share the name: an override goes into the derivation and does not give a hull without a rudder one."""
        rudder = steered(make_vessel(0, True), "rudder")
        base, steeper = derive_vessel_dynamics(rudder), derive_vessel_dynamics(rudder, overrides={"rudder_lift_slope": 3.0})
        assert steeper.rudder_lift_slope == 3.0
        assert steeper.max_yaw_moment == pytest.approx(base.max_yaw_moment * 3.0 / 2.5)
        assert abs(steeper.nR) > abs(base.nR), "the yaw damping is calibrated on the stronger rudder"
        assert derive_vessel_dynamics(make_vessel(0, True), overrides={"rudder_lift_slope": 3.0}).rudder_lift_slope == 0.0


class TestCache:
    def test_the_same_inputs_return_the_same_object(self, steering):
        vessel = steered(make_vessel(0, True), steering)
        assert derive_vessel_dynamics(vessel) is derive_vessel_dynamics(vessel)
        assert derive_vessel_dynamics(vessel, 5.0, {"max_thrust": 1.0e5}) is derive_vessel_dynamics(vessel, 5.0, {"max_thrust": 1.0e5})

    def test_an_equal_vessel_and_equal_overrides_share_the_result(self):
        first = derive_vessel_dynamics(make_vessel(3, False), 0, {"block_coefficient": 0.7, "propeller_kt": 0.25})
        second = derive_vessel_dynamics(make_vessel(3, False), 0.0, {"propeller_kt": 0.25, "block_coefficient": 0.7})
        assert first is second, "whatever the order of the overrides, and an integer as good as a float"
        assert derive_vessel_dynamics(make_vessel(3, False)) is derive_vessel_dynamics(make_vessel(3, False), 0.0, {}) is derive_vessel_dynamics(make_vessel(3, False), overrides=None)

    def test_different_overrides_do_not(self):
        vessel = make_vessel(0, True)
        base = derive_vessel_dynamics(vessel)
        changed = derive_vessel_dynamics(vessel, overrides={"propeller_kt": 0.25})
        assert changed is not base and changed != base
        assert derive_vessel_dynamics(vessel, overrides={"propeller_kt": 0.26}) is not changed

    def test_another_wind_speed_vessel_or_steering_type_does_not(self):
        vessel = make_vessel(0, True)
        base = derive_vessel_dynamics(vessel)
        assert derive_vessel_dynamics(vessel, 7.0) is not base
        assert derive_vessel_dynamics(make_vessel(1, True)) is not base
        assert derive_vessel_dynamics(steered(vessel, "rudder")) is not base
        assert derive_vessel_dynamics(dataclasses.replace(vessel, _block_coefficient=0.7)) is not base

    def test_the_dynamics_cannot_be_changed_behind_the_cache(self):
        dynamics = derive_vessel_dynamics(make_vessel(0, True))
        with pytest.raises(dataclasses.FrozenInstanceError):
            dynamics.max_thrust = 1.0  # type: ignore[misc]

    def test_a_refused_derivation_is_refused_again(self):
        for _ in range(2):
            with pytest.raises(ValueError, match="hull_mass must be positive"):
                derive_vessel_dynamics(make_vessel(0, True), overrides={"hull_mass": -1.0})


class TestValidation:
    def test_a_vessel_without_a_max_speed_is_rejected(self):
        with pytest.raises(ValueError, match="max speed and max angular speed must be positive"):
            derive_vessel_dynamics(make_vessel(0, True, max_speed=0.0))

    def test_a_vessel_that_cannot_turn_is_rejected(self, steering):
        with pytest.raises(ValueError, match="max speed and max angular speed must be positive"):
            derive_vessel_dynamics(steered(make_vessel(0, True, max_angular_speed=0.0), steering))

    def test_a_mass_that_sinks_the_boxes_is_rejected(self):
        vessel = make_vessel(0, True)
        hull_mass = derive_vessel_dynamics(vessel).hull_mass
        with pytest.raises(ValueError, match="would sink"):
            derive_vessel_dynamics(vessel, overrides={"hull_mass": hull_mass * 3})

    def test_a_mass_within_the_reserve_of_the_shallowest_box_floats(self):
        vessel = make_vessel(0, True)
        base = derive_vessel_dynamics(vessel)
        reserve_mass = RHO_WATER * base.waterplane_area * base.reserve_depth
        assert derive_vessel_dynamics(vessel, overrides={"hull_mass": base.hull_mass + 0.9 * reserve_mass}).floating_draft < vessel.draft + base.reserve_depth
        with pytest.raises(ValueError, match="would sink"):
            derive_vessel_dynamics(vessel, overrides={"hull_mass": base.hull_mass + 1.1 * reserve_mass})

    def test_a_non_positive_mass_is_rejected(self):
        with pytest.raises(ValueError, match="hull_mass must be positive"):
            derive_vessel_dynamics(make_vessel(0, True), overrides={"hull_mass": -1.0})

    @pytest.mark.parametrize("field", ["steering_mass", "steering_max_angle", "steering_rate"])
    def test_steering_gear_without_mass_angle_or_speed_is_rejected(self, field):
        for steering_type in HELM_STEERING_TYPES:
            with pytest.raises(ValueError, match=f"{field} must be positive for {steering_type} steering"):
                derive_vessel_dynamics(steered(make_vessel(0, True), steering_type), overrides={field: 0.0})

    @pytest.mark.parametrize("field", ["rudder_area", "rudder_span", "rudder_chord"])
    def test_a_rudder_without_a_size_is_rejected(self, field):
        with pytest.raises(ValueError, match="a rudder needs a positive area, span and chord"):
            derive_vessel_dynamics(steered(make_vessel(0, True), "rudder"), overrides={field: 0.0})

    def test_a_block_coefficient_outside_its_range_is_rejected(self):
        with pytest.raises(ValueError, match="the block coefficient must be in"):
            derive_vessel_dynamics(make_vessel(0, True), overrides={"block_coefficient": 1.2})

    def test_a_hull_with_the_center_of_mass_above_the_waterline_is_rejected(self):
        # The roll stability check in _validate would explain this, but the hydrodynamics derivation
        # takes the square root of the (negative) roll stiffness first, so the error is a bare
        # "math domain error". Reported in the 12.5 results as an open point; only the rejection is pinned.
        with pytest.raises(ValueError):
            derive_vessel_dynamics(make_vessel(0, True), overrides={"com_depth_ratio": -3.0})

    def test_a_value_override_that_lifts_the_center_of_mass_makes_the_hull_unstable_in_roll(self):
        # com_z is a derived value: overriding it recomputes nothing, so the hydrodynamics are derived first and the check catches it.
        with pytest.raises(ValueError, match="unstable in roll"):
            derive_vessel_dynamics(make_vessel(0, True), overrides={"com_z": 5.0})

    def test_broken_inertia_is_rejected(self):
        with pytest.raises(ValueError, match="not a valid rigid body"):
            check_inertia("hull", 1.0, 1.0, 5.0)
        with pytest.raises(ValueError, match="not a valid rigid body"):
            check_inertia("hull", 0.0, 1.0, 1.0)
        check_inertia("hull", 2.0, 3.0, 4.0)

    def test_an_inertia_override_that_breaks_the_triangle_inequality_is_rejected(self):
        with pytest.raises(ValueError, match=r"vessel 0 \(OSPassengerShip\) hull: inertia .* is not a valid rigid body"):
            derive_vessel_dynamics(make_vessel(0, True), overrides={"hull_ixx": 1.0e12})


class TestWindage:
    def test_windage_mass_is_the_linearized_air_drag(self):
        vessel = make_vessel(0, True)
        calm = derive_vessel_dynamics(vessel, wind_speed=0.0)
        windy = derive_vessel_dynamics(vessel, wind_speed=10.0)
        assert windy.windage_mass == pytest.approx(calm.windage_mass * 10.0)
        side_area = vessel.length * (vessel.height - vessel.draft)
        assert calm.windage_mass == pytest.approx(0.5 * 1.225 * 0.9 * side_area * 1.0)

    def test_windage_does_not_change_the_total_mass(self, steering):
        vessel = steered(make_vessel(0, True), steering)
        assert derive_vessel_dynamics(vessel, 0.0).total_mass == pytest.approx(derive_vessel_dynamics(vessel, 12.0).total_mass)

    def test_the_windage_link_sits_at_half_the_freeboard(self):
        vessel = make_vessel(0, True)
        assert derive_vessel_dynamics(vessel).windage_z == pytest.approx((vessel.height - vessel.draft) / 2)
