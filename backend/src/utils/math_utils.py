from enum import Enum
from typing import List, Tuple

import numpy as np


class Direction(Enum):
    LEFT = "left"
    RIGHT = "right"
    FORWARD = "forward"
    BACKWARD = "backward"

    @property
    def custom_name(self) -> str:
        custom_names = {
            Direction.LEFT: "Left",
            Direction.RIGHT: "Right",
            Direction.FORWARD: "Forward",
            Direction.BACKWARD: "Backward",
        }
        return custom_names[self]


def relative_heading_direction(heading1: float, heading2: float) -> Direction:
    diff = heading_diff(heading1, heading2)
    if diff > 0:
        return Direction.LEFT
    elif diff < 0:
        return Direction.RIGHT
    else:
        return Direction.FORWARD


def find_center_and_radius(points_array: List[np.ndarray]) -> Tuple[np.ndarray, float]:
    if len(points_array) == 0:
        return np.array([0, 0]), 0
    # Calculate the center (centroid) by averaging the coordinates
    center = np.mean(points_array, axis=0)
    # Calculate the radius as the maximum distance from the center to any point
    distances = np.linalg.norm(points_array - center, axis=1)
    radius = np.max(distances)
    return center, radius


def compute_angle(vec1: np.ndarray, vec2: np.ndarray):
    """Compute angle between two vectors."""
    magnitude1 = magnitude(vec1)
    magnitude2 = magnitude(vec2)
    if magnitude1 == 0 or magnitude2 == 0:
        return 0

    cos_theta = np.clip(np.dot(vec1, vec2) / (magnitude(vec1) * magnitude(vec2)), -1, 1)
    return np.arccos(cos_theta)


def calculate_heading(v: np.ndarray):
    heading_radians = np.arctan2(v[1], v[0])
    return heading_radians


def distance(p1: np.ndarray, p2: np.ndarray) -> float:
    return float(np.linalg.norm(p1 - p2))


def magnitude(v: np.ndarray) -> float:
    return float(np.linalg.norm(v))


def compute_start_point(position, velocity, speed, acceleration):
    if acceleration <= 0:
        raise ValueError("Acceleration must be positive.")

    if speed < 1e-8:
        return position  # already at rest

    # Distance needed to accelerate from 0 to speed
    distance = speed**2 / (2 * acceleration)

    # Normalize velocity to get direction
    direction = velocity / speed

    # Move backwards along direction
    start_x = position[0] - direction[0] * distance
    start_y = position[1] - direction[1] * distance

    return (start_x, start_y)


def abs_heading_diff(angle1: float, angle2: float):  # [-pi, pi]
    return np.abs(heading_diff(angle1, angle2))


def heading_diff(angle1: float, angle2: float) -> float:
    """
    Compute the smallest signed difference between two headings (in radians),
    result is in the range [-pi, pi].

    Parameters:
    - angle1: First heading angle in radians.
    - angle2: Second heading angle in radians.

    Returns:
    - Signed smallest angular difference in radians.
      Positive: rotate angle2 counter-clockwise to reach angle1.
      Negative: rotate angle2 clockwise to reach angle1.
    """
    return (angle1 - angle2 + np.pi) % (2 * np.pi) - np.pi


def rotate_heading(heading: float, angle: float) -> float:
    """
    Adds two angles and normalizes the result to [-pi, pi].

    Parameters:
    - angle1: First angle in radians.
    - angle2: Second angle in radians.

    Returns:
    - The normalized sum of the two angles in radians.
    """
    x = np.cos(heading)
    y = np.sin(heading)
    # Rotate the vector using a 2D rotation matrix
    cos_a = np.cos(angle)
    sin_a = np.sin(angle)
    x_new = x * cos_a - y * sin_a
    y_new = x * sin_a + y * cos_a
    # Compute the new heading from the rotated vector
    return np.arctan2(y_new, x_new)


def imply(a: bool, b: bool) -> bool:
    return (not a) or b
