import math
import unittest

import numpy as np

from utils.math_utils import (
    abs_heading_diff,
    calculate_heading,
    compute_angle,
    compute_start_point,
    find_center_and_radius,
    heading_diff,
    imply,
    rotate_heading,
)


class TestMathUtils(unittest.TestCase):
    """Test cases for math_utils module functions."""

    def test_find_center_and_radius_basic(self):
        """Test find_center_and_radius with basic square points."""
        points = np.array([[0, 0], [2, 0], [2, 2], [0, 2]])
        center, radius = find_center_and_radius(points)

        expected_center = np.array([1, 1])
        expected_radius = math.sqrt(2)  # Distance from center to corner

        np.testing.assert_array_almost_equal(center, expected_center)
        self.assertAlmostEqual(radius, expected_radius)

    def test_find_center_and_radius_single_point(self):
        """Test find_center_and_radius with single point."""
        points = np.array([[5, 3]])
        center, radius = find_center_and_radius(points)

        expected_center = np.array([5, 3])
        expected_radius = 0.0

        np.testing.assert_array_almost_equal(center, expected_center)
        self.assertAlmostEqual(radius, expected_radius)

    def test_find_center_and_radius_triangle(self):
        """Test find_center_and_radius with triangle points."""
        points = np.array([[0, 0], [3, 0], [1.5, 3]])
        center, radius = find_center_and_radius(points)

        expected_center = np.array([1.5, 1.0])
        # Distance from center to any vertex should be the radius
        distances = np.linalg.norm(points - center, axis=1)
        self.assertAlmostEqual(radius, np.max(distances))

    def test_compute_angle_parallel_vectors(self):
        """Test compute_angle with parallel vectors."""
        vec1 = np.array([1, 0])
        vec2 = np.array([2, 0])

        angle = compute_angle(vec1, vec2)
        self.assertAlmostEqual(angle, 0.0)

    def test_compute_angle_perpendicular_vectors(self):
        """Test compute_angle with perpendicular vectors."""
        vec1 = np.array([1, 0])
        vec2 = np.array([0, 1])

        angle = compute_angle(vec1, vec2)
        self.assertAlmostEqual(angle, np.pi / 2)

    def test_compute_angle_opposite_vectors(self):
        """Test compute_angle with opposite vectors."""
        vec1 = np.array([1, 0])
        vec2 = np.array([-1, 0])

        angle = compute_angle(vec1, vec2)
        self.assertAlmostEqual(angle, math.pi)

    def test_compute_angle_45_degrees(self):
        """Test compute_angle with 45-degree angle."""
        vec1 = np.array([1, 0])
        vec2 = np.array([1, 1])

        angle = compute_angle(vec1, vec2)
        self.assertAlmostEqual(angle, math.pi / 4)

    def test_calculate_heading_east(self):
        """Test calculate_heading with eastward velocity."""
        heading = calculate_heading(np.array([1.0, 0.0]))
        self.assertAlmostEqual(heading, 0.0)

    def test_calculate_heading_north(self):
        """Test calculate_heading with northward velocity."""
        heading = calculate_heading(np.array([0.0, 1.0]))
        self.assertAlmostEqual(heading, math.pi / 2)

    def test_calculate_heading_west(self):
        """Test calculate_heading with westward velocity."""
        heading = calculate_heading(np.array([-1.0, 0.0]))
        self.assertAlmostEqual(heading, math.pi)

    def test_calculate_heading_south(self):
        """Test calculate_heading with southward velocity."""
        heading = calculate_heading(np.array([0.0, -1.0]))
        self.assertAlmostEqual(heading, -math.pi / 2)

    def test_calculate_heading_45_degrees(self):
        """Test calculate_heading with 45-degree northeast velocity."""
        heading = calculate_heading(np.array([1.0, 1.0]))
        self.assertAlmostEqual(heading, math.pi / 4)

    def test_compute_start_point_basic(self):
        """Test compute_start_point with basic parameters."""
        position = (10, 5)
        velocity = (1, 0)  # Moving east
        speed = 2.0
        acceleration = 1.0

        start_point = compute_start_point(position, velocity, speed, acceleration)

        # Distance = v^2 / (2*a) = 4 / 2 = 2
        # Start position = (10, 5) - (1, 0) * 2 = (8, 5)
        expected_start = (8.0, 5.0)

        self.assertAlmostEqual(start_point[0], expected_start[0])
        self.assertAlmostEqual(start_point[1], expected_start[1])

    def test_compute_start_point_diagonal(self):
        """Test compute_start_point with diagonal movement."""
        position = (0, 0)
        velocity = (1, 1)  # Moving northeast
        speed = math.sqrt(8)  # sqrt(2^2 + 2^2)
        acceleration = 1.0

        start_point = compute_start_point(position, velocity, speed, acceleration)

        # Distance = 8 / 2 = 4
        # Start position = (0, 0) - (1, 1) * 4 = (-4, -4)
        expected_start = (-4.0, -4.0)

        self.assertAlmostEqual(start_point[0], expected_start[0])
        self.assertAlmostEqual(start_point[1], expected_start[1])

    def test_compute_start_point_zero_acceleration(self):
        """Test compute_start_point with zero acceleration raises ValueError."""
        position = (10, 5)
        velocity = (1, 0)
        speed = 2.0
        acceleration = 0.0

        with self.assertRaises(ValueError):
            compute_start_point(position, velocity, speed, acceleration)

    def test_compute_start_point_negative_acceleration(self):
        """Test compute_start_point with negative acceleration raises ValueError."""
        position = (10, 5)
        velocity = (1, 0)
        speed = 2.0
        acceleration = -1.0

        with self.assertRaises(ValueError):
            compute_start_point(position, velocity, speed, acceleration)

    def test_abs_heading_diff_same_angle(self):
        """Test abs_heading_diff with same angles."""
        angle1 = math.pi / 4
        angle2 = math.pi / 4
        diff = abs_heading_diff(angle1, angle2)
        self.assertAlmostEqual(diff, 0.0)

    def test_abs_heading_diff_opposite_angles(self):
        """Test abs_heading_diff with opposite angles."""
        angle1 = math.pi / 4
        angle2 = math.pi / 4 + math.pi
        diff = abs_heading_diff(angle1, angle2)
        self.assertAlmostEqual(diff, math.pi)

    def test_abs_heading_diff_90_degrees(self):
        """Test abs_heading_diff with 90-degree difference."""
        angle1 = 0
        angle2 = math.pi / 2
        diff = abs_heading_diff(angle1, angle2)
        self.assertAlmostEqual(diff, math.pi / 2)

    def test_abs_heading_diff_crossing_zero(self):
        """Test abs_heading_diff crossing zero boundary."""
        angle1 = math.pi / 6  # 30 degrees
        angle2 = -math.pi / 6  # -30 degrees
        diff = abs_heading_diff(angle1, angle2)
        self.assertAlmostEqual(diff, math.pi / 3)  # 60 degrees

    def test_heading_diff_same_angle(self):
        """Test heading_diff with same angles."""
        angle1 = math.pi / 4
        angle2 = math.pi / 4
        diff = heading_diff(angle1, angle2)
        self.assertAlmostEqual(diff, 0.0)

    def test_heading_diff_positive_difference(self):
        """Test heading_diff with positive difference."""
        angle1 = 0
        angle2 = math.pi / 2
        diff = heading_diff(angle2, angle1)
        self.assertAlmostEqual(diff, math.pi / 2)

    def test_heading_diff_negative_difference(self):
        """Test heading_diff with negative difference."""
        angle1 = math.pi / 2
        angle2 = 0
        diff = heading_diff(angle2, angle1)
        self.assertAlmostEqual(diff, -math.pi / 2)

    def test_heading_diff_crossing_zero(self):
        """Test heading_diff crossing zero boundary."""
        angle1 = math.pi / 6  # 30 degrees
        angle2 = -math.pi / 6  # -30 degrees
        diff = heading_diff(angle2, angle1)
        # Should normalize to [-pi, pi] range
        self.assertGreaterEqual(diff, -math.pi)
        self.assertLessEqual(diff, math.pi)

    def test_heading_add_basic(self):
        """Test heading_add with basic addition."""
        angle1 = math.pi / 4
        angle2 = math.pi / 4
        result = rotate_heading(angle1, angle2)
        self.assertAlmostEqual(result, math.pi / 2)

    def test_heading_add_crossing_boundary(self):
        """Test heading_add crossing -pi/pi boundary."""
        angle1 = math.pi
        angle2 = math.pi / 2
        result = rotate_heading(angle1, angle2)
        # Should normalize to [-pi, pi] range
        self.assertGreaterEqual(result, -math.pi)
        self.assertLessEqual(result, math.pi)

    def test_heading_add_zero(self):
        """Test heading_add with zero angle."""
        angle1 = math.pi / 3
        angle2 = 0
        result = rotate_heading(angle1, angle2)
        self.assertAlmostEqual(result, math.pi / 3)

    def test_heading_add_negative_angles(self):
        """Test heading_add with negative angles."""
        angle1 = -math.pi / 4
        angle2 = -math.pi / 4
        result = rotate_heading(angle1, angle2)
        self.assertAlmostEqual(result, -math.pi / 2)

    def test_imply_true_true(self):
        """Test imply with both arguments True."""
        result = imply(True, True)
        self.assertTrue(result)

    def test_imply_true_false(self):
        """Test imply with first True, second False."""
        result = imply(True, False)
        self.assertFalse(result)

    def test_imply_false_true(self):
        """Test imply with first False, second True."""
        result = imply(False, True)
        self.assertTrue(result)

    def test_imply_false_false(self):
        """Test imply with both arguments False."""
        result = imply(False, False)
        self.assertTrue(result)

    def test_imply_edge_cases(self):
        """Test imply with various edge cases."""
        # Test with different boolean values
        self.assertTrue(imply(True, True))
        self.assertFalse(imply(True, False))
        self.assertTrue(imply(False, True))
        self.assertTrue(imply(False, False))


if __name__ == "__main__":
    unittest.main()
