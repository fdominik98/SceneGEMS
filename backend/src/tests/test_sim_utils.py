import math
import unittest

import numpy as np
from haversine import Unit

from concrete_level.models.actor_state import ActorState
from scenegems_tool.waraps_integration.sim_utils import (
    Geofence,
    from_true_north,
    to_true_north,
    true_north_heading,
    waypoint_from_state,
)


class TestSimUtils(unittest.TestCase):
    def setUp(self) -> None:
        self.geofence = Geofence(57.757128, 16.673189, 1000)

    def test_geofence_center_property(self):
        center = self.geofence.center
        np.testing.assert_allclose(center, np.array([57.757128, 16.673189]))

    def test_geofence_contains_center(self):
        self.assertTrue(self.geofence.contains(self.geofence.latitude, self.geofence.longitude))

    def test_to_true_north_degrees(self):
        self.assertAlmostEqual(to_true_north(0.0, Unit.DEGREES), 90.0)
        self.assertAlmostEqual(to_true_north(90.0, Unit.DEGREES), 0.0)
        self.assertAlmostEqual(to_true_north(-90.0, Unit.DEGREES), 180.0)

    def test_to_true_north_radians(self):
        self.assertAlmostEqual(to_true_north(0.0, Unit.RADIANS), math.pi / 2)
        self.assertAlmostEqual(to_true_north(math.pi / 2, Unit.RADIANS), 0.0)

    def test_to_true_north_invalid_unit(self):
        with self.assertRaises(ValueError):
            to_true_north(0.0, Unit.METERS)

    def test_from_true_north_degrees(self):
        self.assertAlmostEqual(from_true_north(0.0, Unit.DEGREES), 90.0)
        self.assertAlmostEqual(from_true_north(90.0, Unit.DEGREES), 0.0)
        self.assertAlmostEqual(from_true_north(270.0, Unit.DEGREES), 180.0)

    def test_from_true_north_radians(self):
        self.assertAlmostEqual(from_true_north(0.0, Unit.RADIANS), math.pi / 2)
        self.assertAlmostEqual(from_true_north(math.pi / 2, Unit.RADIANS), 0.0)

    def test_true_north_heading_axis_aligned(self):
        east = true_north_heading(np.array([0.0, 0.0]), np.array([1.0, 0.0]), unit=Unit.DEGREES)
        north = true_north_heading(np.array([0.0, 0.0]), np.array([0.0, 1.0]), unit=Unit.DEGREES)
        west = true_north_heading(np.array([0.0, 0.0]), np.array([-1.0, 0.0]), unit=Unit.DEGREES)
        south = true_north_heading(np.array([0.0, 0.0]), np.array([0.0, -1.0]), unit=Unit.DEGREES)

        self.assertAlmostEqual(east, 90.0)
        self.assertAlmostEqual(north, 0.0)
        self.assertAlmostEqual(west, 270.0)
        self.assertAlmostEqual(south, 180.0)

    def test_true_north_heading_invalid_unit(self):
        with self.assertRaises(ValueError):
            true_north_heading(np.array([0.0, 0.0]), np.array([1.0, 1.0]), unit=Unit.METERS)

    def test_coord_to_lat_long_returns_center_for_zero_vector(self):
        lat_long = self.geofence.to_lat_long(np.array([0.0, 0.0]))
        np.testing.assert_allclose(lat_long, self.geofence.center)

    def test_lat_long_coord_round_trip(self):
        original = np.array([120.0, -85.0])
        lat_long = self.geofence.to_lat_long(original)
        round_trip = self.geofence.to_coord(lat_long[0], lat_long[1])

        # Geodesic conversion and bearing calculations introduce tiny floating-point drift.
        np.testing.assert_allclose(round_trip, original, atol=0.2)

    def test_lat_long_bearing_cardinal(self):
        lat1, lon1 = self.geofence.latitude, self.geofence.longitude
        north = true_north_heading(np.array([lat1, lon1]), np.array([lat1 + 0.01, lon1]), unit=Unit.DEGREES)
        east = true_north_heading(np.array([lat1, lon1]), np.array([lat1, lon1 + 0.01]), unit=Unit.DEGREES)

        self.assertAlmostEqual(north, 0.0, delta=1e-3)
        self.assertAlmostEqual(east, math.pi / 2, delta=1e-3)

    def test_waypoint_from_state(self):
        state = ActorState(x=100.0, y=50.0, speed=3.0, heading=0.0)
        waypoint = waypoint_from_state(state, self.geofence)

        self.assertEqual(waypoint["altitude"], 0)
        self.assertEqual(waypoint["rostype"], "GeoPoint")
        self.assertIn("latitude", waypoint)
        self.assertIn("longitude", waypoint)

        expected_lat_long = self.geofence.to_lat_long(state.p)
        self.assertAlmostEqual(waypoint["latitude"], expected_lat_long[0])
        self.assertAlmostEqual(waypoint["longitude"], expected_lat_long[1])
        


if __name__ == "__main__":
    unittest.main()
