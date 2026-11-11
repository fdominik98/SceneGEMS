"""Maneuvering domain: the give-way trapezoid A-B-C-D and where its first turn A lies."""

import math

import numpy as np
import pytest

from concrete_level.colregs_monitoring.colregs_rules.conditions.give_way_early_action_condition import early_action_start_deadline
from concrete_level.trajectory_generation.maneuvering_domain import CorridorShape, ManeuveringDomain, outbound_start_delay
from concrete_level.trajectory_generation.seed_trajectory import latched_domains_from_nodes
from concrete_level.trajectory_generation.trajectory_tree_builder import SceneNode
from tests.concrete_level.colregs_monitoring.monitor_runs import OWN_SHIP, SPEED, TARGET, constants, monitored_run

SLANT = math.radians(30.0)
ORIGIN = np.array([0.0, 0.0])
EAST = np.array([1.0, 0.0])
STARBOARD = np.array([0.0, -1.0])


def _domain(alongs, acrosses, delay_along=200.0, safety_radius=100.0):
    return ManeuveringDomain.from_projected_corners(ORIGIN, EAST, STARBOARD, alongs, acrosses, safety_radius, SLANT, delay_along)


@pytest.fixture
def domain():
    """A collision domain 1000 to 1200 m ahead, 50 m to either side of the track."""
    return _domain([1000.0, 1200.0], [-50.0, 50.0])


class TestOutboundStart:
    def test_the_first_turn_lies_inside_the_window_rule_16_leaves(self):
        """Rule 16 fails a give-way ship that is not turning after IMMEDIATE_HEADING_CHANGE_TIME, and the
        time a turn takes to be readily apparent is no reason to wait: nothing holds the first turn back."""
        delay = outbound_start_delay(constants())
        assert delay == early_action_start_deadline(constants()) == 30.0  # the monitor's own deadline for the first turn
        assert 0.0 < delay < constants().IMMEDIATE_HEADING_CHANGE_TIME

    def test_a_give_way_ship_gets_its_first_turn_that_far_along_its_track(self):
        nodes = [SceneNode(result) for result in monitored_run((3600.0, -3600.0), 60)]
        domains = latched_domains_from_nodes(nodes)
        assert set(domains) == {OWN_SHIP} and TARGET not in domains
        assert domains[OWN_SHIP].t0 == pytest.approx(SPEED * outbound_start_delay(constants()))

    def test_without_give_way_contexts_there_is_no_domain(self):
        assert ManeuveringDomain.for_give_way_ship(OWN_SHIP, []) is None


class TestGeometry:
    def test_the_trapezoid_clears_the_collision_domain_by_the_safety_radius(self, domain):
        run = 150.0 / math.tan(SLANT)
        assert (domain.t0, domain.inner_across, domain.outer_across) == (200.0, 0.0, 150.0)
        assert (domain.along_b, domain.along_c, domain.along_d) == pytest.approx((200.0 + run, 1300.0, 1300.0 + run))
        assert domain.far_along == domain.along_d

    def test_the_vertices_are_in_world_coordinates_on_the_avoidance_side(self, domain):
        a, b, c, d = domain.vertices
        assert (a.tolist(), d.tolist()) == ([200.0, 0.0], [pytest.approx(domain.along_d), 0.0])
        assert (b[1], c[1]) == (-150.0, -150.0)
        assert len(domain.edges) == 4 and domain.edges[3][1] is a

    def test_outbound_and_inbound_turn_by_the_readily_apparent_angle(self, domain):
        assert math.degrees(domain.hold_heading_change) == pytest.approx(-30.0)
        assert math.degrees(domain.inbound_heading_change) == pytest.approx(30.0)

    def test_no_collision_domain_gives_no_trapezoid(self):
        assert _domain([], []) is None

    def test_a_close_collision_domain_pulls_the_first_turn_back(self):
        """The delay would cut the domain at the readily apparent angle, so A moves toward the ship."""
        close = _domain([300.0], [0.0])
        assert close.t0 == pytest.approx(300.0 - 100.0 / math.tan(SLANT))
        assert math.degrees(close.hold_heading_change) == pytest.approx(-30.0)

    def test_a_collision_domain_too_close_for_that_steepens_the_slant(self):
        steep = _domain([100.0], [0.0])
        assert steep.t0 == 0.0
        assert math.degrees(steep.hold_heading_change) == pytest.approx(-45.0)


class TestPoints:
    @pytest.mark.parametrize("point, inside", [((800.0, -100.0), True), ((800.0, 10.0), False), ((800.0, -200.0), False), ((100.0, 0.0), False), ((300.0, -100.0), False)])
    def test_a_point_is_inside_between_the_track_and_the_outer_edge(self, domain, point, inside):
        assert domain.contains(np.array(point)) is inside

    def test_local_coordinates_are_along_the_course_and_across_to_the_avoidance_side(self, domain):
        assert domain.local(np.array([800.0, -100.0])) == (800.0, 100.0)

    def test_the_distance_is_to_the_polyline_the_seed_follows(self, domain):
        assert domain.distance_to_avoidance_polyline(np.array([800.0, -100.0])) == pytest.approx(50.0)
        assert domain.distance_to_avoidance_polyline(np.array([800.0, -150.0])) == pytest.approx(0.0)

    def test_inside_costs_more_than_the_same_distance_outside_and_far_away_saturates(self, domain):
        inside = domain.magnet_cost(np.array([800.0, -100.0]), 100.0)
        outside = domain.magnet_cost(np.array([800.0, -200.0]), 100.0)
        assert inside == ManeuveringDomain.INSIDE_WEIGHT * 0.5 and outside == ManeuveringDomain.OUTSIDE_WEIGHT * 0.5
        far = ManeuveringDomain.OUTSIDE_WEIGHT * ManeuveringDomain.FAR_CAP_FRACTION
        assert domain.magnet_cost(np.array([800.0, -5000.0]), 100.0) == domain.magnet_cost(np.array([800.0, -9000.0]), 100.0) == far

    def test_the_corners_are_reached_with_a_tolerance_of_a_tenth_of_the_offset(self, domain):
        assert domain.near_outer(136.0) and not domain.near_outer(130.0)
        assert domain.near_track(14.0) and not domain.near_track(20.0)
        assert domain.reached_b(domain.along_b, 150.0) and not domain.reached_b(domain.along_b - 50.0, 150.0)
        assert domain.reached_d(domain.along_c, 0.0) and not domain.reached_d(domain.along_c, 100.0)


class TestReshaping:
    """The corridor of the fixture: A at 200 m, 150 m wide at the readily apparent slant, C at 1300 m."""

    def test_the_default_shape_is_the_corridor_itself(self, domain):
        assert domain.reshaped(None) is domain
        assert domain.reshaped(CorridorShape()) is domain

    def test_a_width_factor_widens_the_corridor_at_the_slant_it_has(self, domain):
        wide = domain.reshaped(CorridorShape(width_factor=2.0))
        run = 300.0 / math.tan(SLANT)
        assert (wide.t0, wide.inner_across, wide.outer_across) == (200.0, 0.0, 300.0)
        assert (wide.along_b, wide.along_c, wide.along_d) == pytest.approx((200.0 + run, 1300.0, 1300.0 + run))
        assert math.degrees(wide.hold_heading_change) == pytest.approx(-30.0)

    def test_an_outbound_angle_steepens_both_slanted_legs(self, domain):
        steep = domain.reshaped(CorridorShape(outbound_angle=math.radians(60.0)))
        run = 150.0 / math.tan(math.radians(60.0))
        assert (steep.t0, steep.outer_across) == (200.0, 150.0)
        assert (steep.along_b, steep.along_c, steep.along_d) == pytest.approx((200.0 + run, 1300.0, 1300.0 + run))
        assert math.degrees(steep.hold_heading_change) == pytest.approx(-60.0)
        assert math.degrees(steep.inbound_heading_change) == pytest.approx(60.0)

    def test_an_angle_below_the_slant_of_the_corridor_keeps_that_slant(self, domain):
        assert math.degrees(domain.reshaped(CorridorShape(math.radians(10.0), 2.0)).hold_heading_change) == pytest.approx(-30.0)
        steep = _domain([100.0], [0.0])  # too close for the readily apparent angle: 45 degrees
        assert math.degrees(steep.reshaped(CorridorShape(math.radians(30.0), 2.0)).hold_heading_change) == pytest.approx(-45.0)

    def test_the_parallel_leg_never_ends_before_it_begins(self, domain):
        """Wide enough, the outbound leg reaches past the frozen domains: C moves out to B."""
        huge = domain.reshaped(CorridorShape(width_factor=6.0))
        assert huge.along_b > 1300.0
        assert huge.along_c == huge.along_b and huge.along_d == pytest.approx(huge.along_c + (huge.along_b - huge.t0))

    def test_the_frame_of_the_corridor_is_kept(self, domain):
        other = domain.reshaped(CorridorShape(math.radians(80.0), 3.0))
        assert other.origin.tolist() == domain.origin.tolist() and other.forward.tolist() == domain.forward.tolist() and other.across.tolist() == domain.across.tolist()
        assert other.vertex_a.tolist() == domain.vertex_a.tolist()

    def test_a_give_way_ship_gets_its_corridor_in_the_shape_asked_for(self):
        contexts = list(monitored_run((3600.0, -3600.0), 2)[0].situation_context_set.values())
        default = ManeuveringDomain.for_give_way_ship(OWN_SHIP, contexts)
        shaped = ManeuveringDomain.for_give_way_ship(OWN_SHIP, contexts, CorridorShape(math.radians(60.0), 2.0))
        assert shaped.outer_across == pytest.approx(2.0 * default.outer_across)
        assert math.degrees(abs(shaped.hold_heading_change)) == pytest.approx(60.0)
        assert ManeuveringDomain.for_give_way_ship(TARGET, contexts, CorridorShape(math.radians(60.0), 2.0)) is None

    def test_lost_progress_orders_the_shapes_from_the_mildest(self):
        """Per unit of width: twice the tangent of half the angle for the two slanted legs, and a tenth for the width."""
        assert CorridorShape().lost_progress(SLANT) == pytest.approx(2.0 * math.tan(SLANT / 2.0) + 0.1)
        assert CorridorShape(width_factor=3.0).lost_progress(SLANT) == pytest.approx(3.0 * CorridorShape().lost_progress(SLANT))
        assert CorridorShape(math.radians(10.0)).lost_progress(SLANT) == CorridorShape().lost_progress(SLANT)
        assert CorridorShape(math.radians(45.0), 2.0).lost_progress(SLANT) > CorridorShape(math.radians(80.0)).lost_progress(SLANT) > CorridorShape(width_factor=2.0).lost_progress(SLANT)


def test_the_monitor_payload_carries_the_vertices_and_the_hold_turn(domain):
    payload = domain.to_monitor_payload()
    assert payload["vertices"] == payload["holdPolyline"] == [[float(x), float(y)] for x, y in domain.vertices]
    assert payload["holdHeadingChangeDeg"] == pytest.approx(-30.0)
