from abc import ABC, abstractmethod
import math
from re import T
from typing import List, Optional

import numpy as np

from concrete_level.models import actor_state
from concrete_level.models.actor_state import ActorState
from utils.math_utils import Direction, calculate_heading, distance, rotate_heading


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
        return RectangularSafetyDomain(self.center, self.heading, 2 * self.radius, 2 * self.radius)

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
    
    
    def get_ray_distances(self, 
                          other_domains: List['CircularSafetyDomain'], 
                          increment: int,
                          min_distance: float,
                          max_distance: float) -> List[float]:
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
            
            shortest_distance = float('inf')
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
        return RectangularSafetyDomain(self.center, self.heading, self.b, self.a)

    @property
    def bounding_circle(self) -> "CircularSafetyDomain":
        return CircularSafetyDomain(self.center, self.heading, self.a)

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
        front_pseudo_state = self.back_pseudo_state
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
        return CircularSafetyDomain(self.center, self.heading, self.a)

    @staticmethod
    def bound_domains(safety_domains: List[SafetyDomain]) -> "RectangularSafetyDomain":
        """
        Compute the minimal bounding oriented rectangle that encloses all given oriented rectangles.
        The resulting rectangle has heading = average heading (by unit vector averaging).

        Args:
            circular_safety_domains: list of CircularSafetyDomain objects
                where center = (x, y), a = half height, b = half width, heading in degrees

        Returns:
            A tuple: (center, a, b, heading)
        """

        if len(safety_domains) == 0:
            return RectangularSafetyDomain(np.array([0.0, 0.0]), 0.0, 0.0, 0.0)

        # --- Step 1: Compute average heading via unit vector averaging
        heading_vectors = np.array([c.v for c in safety_domains])
        avg_vec = np.mean(heading_vectors, axis=0)
        avg_heading = calculate_heading(avg_vec)

        # get circle intersections from center towards avg_heading
        # --- Step 2: Rotation matrix for average heading
        R = np.array([[np.cos(avg_heading), -np.sin(avg_heading)], [np.sin(avg_heading), np.cos(avg_heading)]])
        R_inv = R.T  # rotate points into average-heading frame

        # --- Step 3: Compute bounding extents considering each circle's radius
        all_min = []
        all_max = []

        for c in safety_domains:
            cx, cy = c.center[0], c.center[1]
            r = c.bounding_circle.radius

            # Transform center into avg-heading frame
            transformed_center = np.dot(R_inv, np.array([cx, cy]))
            all_min.append(transformed_center - np.array([r, r]))
            all_max.append(transformed_center + np.array([r, r]))

        all_min = np.min(np.vstack(all_min), axis=0)
        all_max = np.max(np.vstack(all_max), axis=0)

        # --- Step 4: Compute bounding rectangle parameters in local frame
        center_local = (all_min + all_max) / 2
        width = (all_max[0] - all_min[0]) / 2  # b
        height = (all_max[1] - all_min[1]) / 2  # a

        # --- Step 5: Transform center back to world coordinates
        center_world = np.dot(R, center_local)

        return RectangularSafetyDomain(center_world, avg_heading, width, height)


class DomainCollection:
    def __init__(self):
        self.domains: List[SafetyDomain] = list()
        self.__has_changed = True
        self.__bounding_rectangle = None

    @property
    def bounding_rectangle(self) -> RectangularSafetyDomain:
        if self.__has_changed or self.__bounding_rectangle is None:
            self.__bounding_rectangle = RectangularSafetyDomain.bound_domains(self.domains)
            self.__has_changed = False
        return self.__bounding_rectangle

    @staticmethod
    def from_points(points: List[np.ndarray], headings: List[float], radii: List[float]) -> "DomainCollection":
        domain_collection = DomainCollection()
        for point, heading, radius in zip(points, headings, radii):
            domain_collection.add_domain(point, heading, radius)
        return domain_collection

    @staticmethod
    def from_domains(domains: List[SafetyDomain]) -> "DomainCollection":
        domain_collection = DomainCollection()
        for domain in domains:
            domain_collection.add_domain(domain.center, domain.heading, domain.center_end_distance)
        return domain_collection

    def add_domain(self, point: np.ndarray, heading: float, radius: float):
        if radius <= 0:
            return
        self.domains.append(CircularSafetyDomain(point, heading, radius))

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
        return DomainCollection.from_domains(self.domains + other.domains)

    @property
    def empty(self) -> bool:
        return len(self.domains) == 0
