import math
from abc import ABC, abstractmethod
from re import T
from typing import List, Optional

import numpy as np

from concrete_level.models.actor_state import ActorState
from utils.global_constants import EPSILON
from utils.math_utils import Direction, calculate_heading, distance, rotate_heading

# How finely a step is sampled when a domain has no closed-form segment clearance.
SEGMENT_CLEARANCE_SAMPLES = 16


class SafetyDomain(ABC):
    def __init__(self, center: np.ndarray, heading: float):
        self.center = center
        self.heading = heading

    @property
    @abstractmethod
    def bounding_rectangle(self) -> "RectangularSafetyDomain":
        pass

    @property
    @abstractmethod
    def bounding_circle(self) -> "CircularSafetyDomain":
        pass

    @property
    def v(self) -> np.ndarray:
        return np.array([np.cos(self.heading), np.sin(self.heading)])

    @property
    def v_perp_left(self) -> np.ndarray:
        return np.array([-np.sin(self.heading), np.cos(self.heading)])

    @property
    def left_heading(self) -> float:
        return rotate_heading(self.heading, np.pi / 2)

    @property
    def right_heading(self) -> float:
        return rotate_heading(self.heading, -np.pi / 2)

    @property
    def v_perp_right(self) -> np.ndarray:
        return -self.v_perp_left

    @abstractmethod
    def intersection_of_line_from_center(self, line_direction: float) -> np.ndarray:
        pass

    def intersection_distance_from_center(self, line_direction: float) -> float:
        return distance(self.intersection_of_line_from_center(line_direction), self.center)

    def signed_clearance(self, point: np.ndarray) -> float:
        """Signed distance from ``point`` to this domain's boundary.

        Negative inside the domain, zero on the boundary, positive outside. The
        generic implementation measures along the ray from the center, which is exact
        on that ray and always sign-correct for a convex domain. Shapes with a cheap
        closed form override it.
        """
        delta = point - self.center
        radial_distance = float(np.linalg.norm(delta))
        if radial_distance < EPSILON:
            return -self.intersection_distance_from_center(self.heading)
        boundary_distance = self.intersection_distance_from_center(calculate_heading(delta))
        return radial_distance - boundary_distance

    def direction_normal(self, direction: Direction) -> np.ndarray:
        if direction == Direction.RIGHT:
            return self.v_perp_right
        if direction == Direction.LEFT:
            return self.v_perp_left
        if direction == Direction.FORWARD:
            return self.v
        if direction == Direction.BACKWARD:
            return -self.v
        raise ValueError(f"Invalid direction: {direction}")

    def signed_side_offset(self, point: np.ndarray, direction: Direction) -> float:
        """How far ``point`` lies beyond the domain boundary on the given side.

        Positive means the point is clear of the domain on that side, zero means it is
        level with the boundary there, negative means it has not cleared it. Unlike
        ``distance_from_direction`` this carries a sign, so passing on the wrong side is
        distinguishable from passing on the right one.
        """
        normal = self.direction_normal(direction)
        extent = self.intersection_distance_from_center(calculate_heading(normal))
        return float(np.dot(point - self.center, normal)) - extent

    def min_signed_clearance_over_segment(self, p_start: np.ndarray, p_end: np.ndarray, samples: int = SEGMENT_CLEARANCE_SAMPLES) -> float:
        """Smallest ``signed_clearance`` anywhere on the segment from p_start to p_end.

        This is what makes the domain check sound between two sampled scenes: testing
        only the endpoints lets a fast relative motion tunnel straight through the
        domain. The generic implementation samples the segment; ``CircularSafetyDomain``
        solves it exactly.
        """
        steps = max(1, samples)
        return min(self.signed_clearance(p_start + (p_end - p_start) * (i / steps)) for i in range(steps + 1))

    @abstractmethod
    def shift(self, distance: float, direction: float) -> "SafetyDomain":
        pass

    @abstractmethod
    def contains_point(self, point: np.ndarray) -> bool:
        pass

    @property
    @abstractmethod
    def back_point(self) -> np.ndarray:
        pass

    @property
    def back_pseudo_state(self) -> ActorState:
        return ActorState(self.back_point[0], self.back_point[1], 1.0, self.heading)

    @property
    @abstractmethod
    def front_point(self) -> np.ndarray:
        pass

    @property
    def front_pseudo_state(self) -> ActorState:
        return ActorState(self.front_point[0], self.front_point[1], 1.0, self.heading)

    @property
    @abstractmethod
    def left_point(self) -> np.ndarray:
        pass

    @property
    def left_pseudo_state(self) -> ActorState:
        return ActorState(self.left_point[0], self.left_point[1], 1.0, self.heading)

    @property
    @abstractmethod
    def right_point(self) -> np.ndarray:
        pass

    @property
    def right_pseudo_state(self) -> ActorState:
        return ActorState(self.right_point[0], self.right_point[1], 1.0, self.heading)

    @property
    @abstractmethod
    def center_end_distance(self) -> float:
        pass

    @property
    @abstractmethod
    def center_left_side_distance(self) -> float:
        pass

    @property
    @abstractmethod
    def points_for_plotting(self) -> List[np.ndarray]:
        pass

    @property
    def rotation_matrix(self) -> np.ndarray:
        cos_theta, sin_theta = np.cos(self.heading), np.sin(self.heading)
        return np.array([[cos_theta, -sin_theta], [sin_theta, cos_theta]])

    @property
    def rotation_matrix_inv(self) -> np.ndarray:
        cos_theta, sin_theta = np.cos(-self.heading), np.sin(-self.heading)
        return np.array([[cos_theta, -sin_theta], [sin_theta, cos_theta]])


class CircularSafetyDomain(SafetyDomain):
    def __init__(self, center: np.ndarray, heading: float, radius: float):
        super().__init__(center, heading)
        self.radius = radius

    def intersection_of_line_from_center(self, line_direction: float) -> np.ndarray:
        direction_vector = np.array([np.cos(line_direction), np.sin(line_direction)])
        return self.center + self.radius * direction_vector

    def shift(self, distance: float, direction: float) -> "CircularSafetyDomain":
        direction_vector = np.array([np.cos(direction), np.sin(direction)])
        shifted_center = self.center + distance * direction_vector
        return CircularSafetyDomain(shifted_center, self.heading, self.radius)

    def contains_point(self, point: np.ndarray) -> bool:
        return distance(point, self.center) <= self.radius

    def signed_clearance(self, point: np.ndarray) -> float:
        return distance(point, self.center) - self.radius

    def min_signed_clearance_over_segment(self, p_start: np.ndarray, p_end: np.ndarray, samples: int = SEGMENT_CLEARANCE_SAMPLES) -> float:
        # Exact: the closest point of a segment to the center, minus the radius.
        segment = p_end - p_start
        segment_length_sq = float(np.dot(segment, segment))
        if segment_length_sq < EPSILON:
            return self.signed_clearance(p_start)
        t = float(np.dot(self.center - p_start, segment)) / segment_length_sq
        t = min(1.0, max(0.0, t))
        return distance(p_start + segment * t, self.center) - self.radius

    @property
    def back_point(self) -> np.ndarray:
        return self.center - self.radius * self.v

    @property
    def front_point(self) -> np.ndarray:
        return self.center + self.radius * self.v

    @property
    def left_point(self) -> np.ndarray:
        return self.center + self.radius * self.v_perp_left

    @property
    def right_point(self) -> np.ndarray:
        return self.center + self.radius * self.v_perp_right

    @property
    def center_end_distance(self) -> float:
        return self.radius

    @property
    def center_left_side_distance(self) -> float:
        return self.radius

    @property
    def bounding_rectangle(self) -> "RectangularSafetyDomain":
        # a and b are HALF extents, so the square circumscribing the circle has both
        # half extents equal to the radius (2 * radius made the box twice too large).
        return RectangularSafetyDomain(self.center, self.heading, self.radius, self.radius)

    @property
    def v(self) -> np.ndarray:
        return np.array([np.cos(self.heading), np.sin(self.heading)])

    @property
    def bounding_circle(self) -> "CircularSafetyDomain":
        return self

    @property
    def points_for_plotting(self) -> List[np.ndarray]:
        # Create parameter t for the circle
        t = np.linspace(0, 2 * np.pi, 100)
        return self.center + self.radius * np.column_stack([np.cos(t), np.sin(t)])

    def get_ray_distances(self, other_domains: List["CircularSafetyDomain"], increment: int, min_distance: float, max_distance: float) -> List[float]:
        """
        Casts rays from the edge of this domain to find the closest edge
        among a list of other safety domains, bounded by min and max distances.

        :param other_domains: A list of CircularSafetyDomain objects to check against.
        :param increment: Degree step for the rays (integer).
        :param min_distance: The minimum distance threshold (blind spot limit).
        :param max_distance: The maximum distance threshold (sensor range limit).
        :return: A list of distances for each angle step, bounded by min_distance
                 and max_distance. Returns max_distance if no collision occurs.
        """
        x1, y1 = self.center
        distances = []

        # ==========================================
        # BROAD PHASE: Calculate active angle intervals
        # ==========================================
        active_intervals = []
        check_all_angles = False

        for other in other_domains:
            x2, y2 = other.center
            r2 = other.radius

            dx_center = x2 - x1
            dy_center = y2 - y1
            distance_to_center = math.hypot(dx_center, dy_center)

            # If the ego center is inside the target circle, we must check all angles
            if distance_to_center <= r2:
                check_all_angles = True
                break

            # Calculate angle to the target and the width of its bounding cone
            phi = math.degrees(math.atan2(dy_center, dx_center)) % 360
            alpha = math.degrees(math.asin(r2 / distance_to_center))

            # Wrap angles to 0-360 to handle intervals crossing the 0-degree line
            start_angle = (phi - alpha) % 360
            end_angle = (phi + alpha) % 360
            active_intervals.append((start_angle, end_angle))

        # ==========================================
        # NARROW PHASE: Raycasting
        # ==========================================
        for angle_deg in range(0, 360, increment):
            # Normalize the ray angle to 0-360 for our interval checks
            theta_deg = (angle_deg + 0) % 360

            # 1. Culling Check: Is this angle near any safety domain?
            needs_check = check_all_angles
            if not needs_check:
                for start, end in active_intervals:
                    if start <= end:
                        # Normal interval (e.g., 45 to 90 degrees)
                        if start <= theta_deg <= end:
                            needs_check = True
                            break
                    else:
                        # Wrapped interval (e.g., 350 to 20 degrees)
                        if theta_deg >= start or theta_deg <= end:
                            needs_check = True
                            break

            # If it's outside all bounding cones, it hits nothing
            if not needs_check:
                distances.append(float(max_distance))
                continue

            # 2. Exact Intersection Math (Only runs if a domain is in the ray's path)
            theta_rad = math.radians(theta_deg)
            dx = math.cos(theta_rad)
            dy = math.sin(theta_rad)

            px = x1 + self.radius * dx
            py = y1 + self.radius * dy

            shortest_distance = float("inf")
            hit_found = False

            for other in other_domains:
                x2, y2 = other.center
                r2 = other.radius

                vx = px - x2
                vy = py - y2

                b = 2 * (vx * dx + vy * dy)
                c = (vx * vx + vy * vy) - (r2 * r2)

                discriminant = (b * b) - (4 * c)

                if discriminant >= 0:
                    sqrt_disc = math.sqrt(discriminant)
                    t1 = (-b - sqrt_disc) / 2
                    t2 = (-b + sqrt_disc) / 2

                    valid_distances = [t for t in (t1, t2) if t >= 0]

                    if valid_distances:
                        closest_to_this_other = min(valid_distances)
                        if closest_to_this_other < shortest_distance:
                            shortest_distance = closest_to_this_other
                            hit_found = True

            # Apply Min/Max constraints
            if not hit_found or shortest_distance >= max_distance:
                distances.append(float(max_distance))
            else:
                clamped_distance = max(min_distance, shortest_distance)
                distances.append(float(clamped_distance))

        return distances


class EllipticalSafetyDomain(SafetyDomain):
    def __init__(self, center: np.ndarray, heading: float, a: float, b: float):
        super().__init__(center, heading)
        self.a = a
        self.b = b

    def intersection_of_line_from_center(self, line_direction: float) -> np.ndarray:
        """
        Compute intersection point of a ray from the center of a rotated ellipse in the given direction.

        Parameters
        ----------
        line_direction : float
            Angle in radians of the ray from the center.

        Returns
        -------
        np.ndarray
            The intersection point as a 2D coordinate in global space.
        """

        # Direction vector in global coordinates
        direction = np.array([np.cos(line_direction), np.sin(line_direction)])

        # Rotate the direction vector *into* the ellipse's local coordinate system (i.e., un-rotate it)
        local_direction = self.rotation_matrix_inv @ direction

        # Solve for t such that the point (t * dx, t * dy) lies on the unrotated ellipse
        dx, dy = local_direction
        t = 1 / np.sqrt((dx**2) / self.a**2 + (dy**2) / self.b**2)

        # Compute intersection in local ellipse frame
        local_intersection = t * local_direction

        # Rotate back to global frame
        global_intersection = self.center + self.rotation_matrix @ local_intersection

        return global_intersection

    def shift(self, distance: float, direction: float) -> "EllipticalSafetyDomain":
        direction_vector = np.array([np.cos(direction), np.sin(direction)])
        shifted_center = self.center + distance * direction_vector
        return EllipticalSafetyDomain(
            shifted_center,
            self.heading,
            self.a,
            self.b,
        )

    def contains_point(self, point: np.ndarray) -> bool:
        """
        Check if a single point is inside the rotated ellipse.

        Parameters
        ----------
        point : np.ndarray
            A single 2D point with shape (2,)

        Returns
        -------
        bool
            True if the point is inside the ellipse, False otherwise.
        """
        # Vector from center to point
        d = point - self.center

        # Rotate by -heading to align with unrotated ellipse
        cos_theta = np.cos(-self.heading)
        sin_theta = np.sin(-self.heading)
        x_rot = d[0] * cos_theta - d[1] * sin_theta
        y_rot = d[0] * sin_theta + d[1] * cos_theta

        # Check ellipse equation
        value = (x_rot**2) / (self.a**2) + (y_rot**2) / (self.b**2)

        return value <= 1

    @property
    def back_point(self) -> np.ndarray:
        return self.center - self.a * self.v

    @property
    def front_point(self) -> np.ndarray:
        return self.center + self.a * self.v

    @property
    def left_point(self) -> np.ndarray:
        return self.center + self.b * self.v_perp_left

    @property
    def right_point(self) -> np.ndarray:
        return self.center + self.b * self.v_perp_right

    @property
    def center_end_distance(self) -> float:
        return self.a

    @property
    def center_left_side_distance(self) -> float:
        return self.b

    @property
    def bounding_rectangle(self) -> "RectangularSafetyDomain":
        # a is the along-heading semi axis and b the cross-heading one, matching
        # RectangularSafetyDomain's own a/b convention (they were swapped here).
        return RectangularSafetyDomain(self.center, self.heading, self.a, self.b)

    @property
    def bounding_circle(self) -> "CircularSafetyDomain":
        return CircularSafetyDomain(self.center, self.heading, max(self.a, self.b))

    @property
    def points_for_plotting(self) -> List[np.ndarray]:
        # Create parameter t for the ellipse
        t = np.linspace(0, 2 * np.pi, 200)

        # Parametric equations for ellipse centered at origin (vectorized)
        ellipse_points = np.column_stack([self.a * np.cos(t), self.b * np.sin(t)])

        # Apply rotation using matrix multiplication
        rotated_points = ellipse_points @ self.rotation_matrix.T

        # Translate to center using vectorized addition
        return rotated_points + self.center


class RectangularSafetyDomain(SafetyDomain):
    def __init__(self, center: np.ndarray, heading: float, a: float, b: float):
        super().__init__(center, heading)
        self.a = a
        self.b = b

    def distance_from_point(self, point: np.ndarray) -> float:
        center_to_actor_heading = calculate_heading(point - self.center)
        intersection = self.intersection_of_line_from_center(center_to_actor_heading)
        return distance(intersection, point)

    def distance_from_right_side(self, point: np.ndarray) -> float:
        right_pseudo_state = self.right_pseudo_state
        return right_pseudo_state.point_distance_from_course(point)

    def distance_from_left_side(self, point: np.ndarray) -> float:
        left_pseudo_state = self.left_pseudo_state
        return left_pseudo_state.point_distance_from_course(point)

    def distance_from_front_side(self, point: np.ndarray) -> float:
        front_pseudo_state = self.front_pseudo_state
        return front_pseudo_state.point_distance_from_course(point)

    def distance_from_back_side(self, point: np.ndarray) -> float:
        back_pseudo_state = self.back_pseudo_state
        return back_pseudo_state.point_distance_from_course(point)

    def distance_from_direction(self, point: np.ndarray, direction: Direction) -> float:
        if direction == Direction.RIGHT:
            return self.distance_from_right_side(point)
        elif direction == Direction.FORWARD:
            return self.distance_from_front_side(point)
        elif direction == Direction.LEFT:
            return self.distance_from_left_side(point)
        elif direction == Direction.BACKWARD:
            return self.distance_from_back_side(point)
        raise ValueError(f"Invalid direction: {direction}")

    def intersection_of_line_from_center(self, line_direction: float) -> np.ndarray:
        """
        Compute intersection point of a ray from the center of a rotated rectangle in the given direction.

        Parameters
        ----------
        line_direction : float
            Angle in radians of the ray from the center.

        Returns
        -------
        np.ndarray
            The intersection point as a 2D coordinate in global space.
        """
        # Direction vector in global coordinates
        direction = np.array([np.cos(line_direction), np.sin(line_direction)])

        # Rotate the direction vector into the rectangle's local coordinate system
        local_direction = self.rotation_matrix_inv @ direction

        dx, dy = local_direction

        # Find which edge the ray intersects
        # Calculate t values for each edge intersection
        t_x = None
        t_y = None

        # Calculate t to hit x edges (x = ±b)
        if abs(dx) > 1e-10:  # Avoid division by zero or near-zero
            t_x = self.a / abs(dx)

        # Calculate t to hit y edges (y = ±a)
        if abs(dy) > 1e-10:  # Avoid division by zero or near-zero
            t_y = self.b / abs(dy)

        # Determine which edge is hit first (smallest positive t)
        if t_x is None and t_y is None:
            # Edge case: direction is (0, 0) or both components are near zero
            # Return a point on the boundary (arbitrary choice - use right edge)
            local_intersection = np.array([self.a, 0])
        elif t_y is None:
            # Only x-edge can be hit (ray is parallel to y-axis)
            # Intersection is on x-edge: x = sign(dx) * a, y = t_x * dy
            local_intersection = np.array([np.sign(dx) * self.a, t_x * dy])
        elif t_x is None:
            # Only y-edge can be hit (ray is parallel to x-axis)
            # Intersection is on y-edge: x = t_y * dx, y = sign(dy) * b
            local_intersection = np.array([t_y * dx, np.sign(dy) * self.b])
        else:
            # Both edges could be hit - choose the closer one
            if t_x < t_y:
                # Hits x-edge first: x = sign(dx) * a, y = t_x * dy
                local_intersection = np.array([np.sign(dx) * self.a, t_x * dy])
            else:
                # Hits y-edge first: x = t_y * dx, y = sign(dy) * b
                local_intersection = np.array([t_y * dx, np.sign(dy) * self.b])

        # Rotate back to global frame
        global_intersection = self.center + self.rotation_matrix @ local_intersection

        return global_intersection

    @property
    def points_for_plotting(self) -> List[np.ndarray]:
        # Define rectangle corners in local coordinate system (before rotation)
        # a is half-length along heading, b is half-width perpendicular
        corners_local = np.array(
            [
                [-self.a, -self.b],  # Bottom-left
                [self.a, -self.b],  # Bottom-right
                [self.a, self.b],  # Top-right
                [-self.a, self.b],  # Top-left
                [-self.a, -self.b],  # Close the rectangle
            ]
        )

        # Apply rotation using matrix multiplication
        rotated_corners = corners_local @ self.rotation_matrix.T

        # Translate to center using vectorized addition
        return rotated_corners + self.center

    def contains_point(self, point: np.ndarray) -> bool:
        """
        Check if a point (px, py) is inside a rotated rectangle.

        Parameters:
            px, py : float
                Coordinates of the point.
            cx, cy : float
                Center of the rectangle.
            half_height : float
                Half of the rectangle's height (extent along the local y-axis).
            half_width : float
                Half of the rectangle's width (extent along the local x-axis).
            orientation : float
                Angle (in radians) of the rectangle’s height axis from the x-axis.

        Returns:
            bool : True if the point lies inside the rectangle, False otherwise.
        """
        # Translate point to rectangle-centered coordinate system
        dx = point[0] - self.center[0]
        dy = point[1] - self.center[1]

        # Rotate point by -orientation to align with rectangle axes
        cos_t = np.cos(-self.heading)
        sin_t = np.sin(-self.heading)
        local_x = dx * cos_t - dy * sin_t
        local_y = dx * sin_t + dy * cos_t

        # Check within bounds
        return abs(local_x) <= self.a and abs(local_y) <= self.b

    def signed_clearance(self, point: np.ndarray) -> float:
        # Exact signed distance to an oriented box.
        local = self.rotation_matrix_inv @ (point - self.center)
        outside = np.array([abs(local[0]) - self.a, abs(local[1]) - self.b])
        outside_distance = float(np.linalg.norm(np.maximum(outside, 0.0)))
        inside_distance = min(float(np.max(outside)), 0.0)
        return outside_distance + inside_distance

    def shift(self, distance: float, direction: float) -> "RectangularSafetyDomain":
        direction_vector = np.array([np.cos(direction), np.sin(direction)])
        shifted_center = self.center + distance * direction_vector
        return RectangularSafetyDomain(shifted_center, self.heading, self.a, self.b)

    @property
    def back_point(self) -> np.ndarray:
        return self.center - self.a * self.v

    @property
    def front_point(self) -> np.ndarray:
        return self.center + self.a * self.v

    @property
    def left_point(self) -> np.ndarray:
        return self.center + self.b * self.v_perp_left

    @property
    def right_point(self) -> np.ndarray:
        return self.center + self.b * self.v_perp_right

    @property
    def center_end_distance(self) -> float:
        return self.a

    @property
    def center_left_side_distance(self) -> float:
        return self.b

    @property
    def bounding_rectangle(self) -> "RectangularSafetyDomain":
        return self

    @property
    def bounding_circle(self) -> "CircularSafetyDomain":
        # The circumscribing circle has to reach the corners, not just the front edge.
        return CircularSafetyDomain(self.center, self.heading, float(math.hypot(self.a, self.b)))

    @staticmethod
    def bound_domains(safety_domains: List[SafetyDomain], heading: Optional[float] = None) -> "RectangularSafetyDomain":
        """The smallest oriented rectangle enclosing every one of ``safety_domains``.

        ``heading`` fixes the frame the rectangle is measured in. Pass the course the
        result will be read against; leave it out and the frame is the domains' average
        heading, which only means something when they roughly agree. Two domains pointing
        opposite ways average to nothing, and the frame then comes out of an arbitrary
        arctangent of numerical noise: a head-on pair, whose domains are by definition
        reciprocal, produced a rectangle whose "along" axis lay across both tracks.

        Each domain is enclosed by its own outline projected into that frame, not by its
        circumscribed circle. The circle throws away the shape it was built from, which
        is the whole point of having shapes: it gives an elongated head-on domain the
        beam of its own length, and a vessel told to go around that is sent half as far
        again as the encounter asks for.
        """

        if len(safety_domains) == 0:
            return RectangularSafetyDomain(np.array([0.0, 0.0]), 0.0, 0.0, 0.0)

        if heading is None:
            heading_vectors = np.array([c.v for c in safety_domains])
            avg_vec = np.mean(heading_vectors, axis=0)
            heading = calculate_heading(avg_vec)

        R = np.array([[np.cos(heading), -np.sin(heading)], [np.sin(heading), np.cos(heading)]])
        R_inv = R.T  # rotate points into the reference frame

        all_min = []
        all_max = []

        for c in safety_domains:
            outline = np.asarray(c.points_for_plotting)
            if outline.size == 0:
                # Nothing to project: fall back to the circumscribed circle so the
                # domain is still bounded rather than silently skipped.
                transformed_center = np.dot(R_inv, c.center)
                r = c.bounding_circle.radius
                all_min.append(transformed_center - np.array([r, r]))
                all_max.append(transformed_center + np.array([r, r]))
                continue
            transformed = outline @ R_inv.T
            all_min.append(np.min(transformed, axis=0))
            all_max.append(np.max(transformed, axis=0))

        all_min = np.min(np.vstack(all_min), axis=0)
        all_max = np.max(np.vstack(all_max), axis=0)

        center_local = (all_min + all_max) / 2
        along_half = (all_max[0] - all_min[0]) / 2  # a: extent along the reference heading
        across_half = (all_max[1] - all_min[1]) / 2  # b: extent across it

        center_world = np.dot(R, center_local)

        return RectangularSafetyDomain(center_world, heading, along_half, across_half)


class DomainCollection:
    def __init__(self, reference_heading: Optional[float] = None):
        self.domains: List[SafetyDomain] = list()
        # The course this collection is read against, which is what has_passed and
        # in_front_of ask about. Without it the bounding rectangle falls back to the
        # domains' average heading, and domains that disagree leave it with no frame.
        self.reference_heading = reference_heading
        self.__has_changed = True
        self.__bounding_rectangle = None

    @property
    def bounding_rectangle(self) -> RectangularSafetyDomain:
        if self.__has_changed or self.__bounding_rectangle is None:
            self.__bounding_rectangle = RectangularSafetyDomain.bound_domains(self.domains, self.reference_heading)
            self.__has_changed = False
        return self.__bounding_rectangle

    @staticmethod
    def from_points(points: List[np.ndarray], headings: List[float], radii: List[float]) -> "DomainCollection":
        domain_collection = DomainCollection()
        for point, heading, radius in zip(points, headings, radii):
            domain_collection.add_domain(point, heading, radius)
        return domain_collection

    @staticmethod
    def from_domains(domains: List[SafetyDomain], reference_heading: Optional[float] = None) -> "DomainCollection":
        # Keep the domains as they are. Rebuilding each one as a circle of radius
        # center_end_distance threw away the cross-heading extent, so a union was
        # lossy and an ellipse or rectangle silently became a circle.
        domain_collection = DomainCollection(reference_heading)
        for domain in domains:
            domain_collection.add_safety_domain(domain)
        return domain_collection

    def add_safety_domain(self, domain: SafetyDomain):
        if domain.bounding_circle.radius <= 0:
            return
        self.domains.append(domain)
        self.__has_changed = True

    def add_domain(self, point: np.ndarray, heading: float, radius: float):
        if radius <= 0:
            return
        self.domains.append(CircularSafetyDomain(point, heading, radius))
        self.__has_changed = True

    def has_passed(self, actor_state: ActorState) -> bool:
        if self.empty:
            return True
        domain = self.bounding_rectangle
        return actor_state.right_of(domain.right_pseudo_state) or actor_state.left_of(domain.left_pseudo_state) or actor_state.in_front_of(domain.front_pseudo_state)

    def in_front_of(self, actor_state: ActorState) -> bool:
        if self.empty:
            return True
        domain = self.bounding_rectangle
        return actor_state.in_front_of(domain.front_pseudo_state)

    @property
    def heading(self) -> float:
        return self.bounding_rectangle.heading

    def union(self, other: "DomainCollection") -> "DomainCollection":
        # The frame belongs to the actor the collection is about, and a union is only
        # ever taken across that one actor's encounters, so either operand's frame is
        # the right one: the first that has one wins.
        reference_heading = self.reference_heading if self.reference_heading is not None else other.reference_heading
        return DomainCollection.from_domains(self.domains + other.domains, reference_heading)

    @property
    def empty(self) -> bool:
        return len(self.domains) == 0
