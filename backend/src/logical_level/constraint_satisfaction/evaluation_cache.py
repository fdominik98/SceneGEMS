from abc import ABC
from typing import Dict, List, Optional, Tuple

import numpy as np

from utils.colregs_approximations import drift_threshold, vis_distance
from logical_level.constraint_satisfaction.assignments import Assignments
from logical_level.models.actor_variable import ActorVariable
from logical_level.models.values import ActorValues
from utils.global_constants import EPSILON, SIDE_ANGLE
from utils.math_utils import compute_angle, magnitude


class GeometricProperties(ABC):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, assignments: Assignments):
        self.val1: ActorValues = assignments[var1]
        self.val2: ActorValues = assignments[var2]

        # Cache properties
        self.__safety_dist: Optional[float] = None
        self.__p12: Optional[np.ndarray] = None
        self.__p21: Optional[np.ndarray] = None
        self.__o_distance: Optional[float] = None
        self.__angle_p21_v2: Optional[float] = None
        self.__sin_half_col_cone_theta: Optional[float] = None
        self.__angle_half_col_cone: Optional[float] = None
        self.__v12: Optional[np.ndarray] = None
        self.__v12_norm_stable: Optional[float] = None
        self.__angle_p12_v1: Optional[float] = None
        self.__tcpa: Optional[float] = None
        self.__dcpa: Optional[float] = None
        self.__vis_distance: Optional[float] = None
        self.__domain_violation_times: Optional[List[float]] = None
        self.__drift_threshold: Optional[float] = None

    @property
    def safety_dist(self) -> float:
        if self.__safety_dist is None:
            self.__safety_dist = max(self.val1.r, self.val2.r)
        return self.__safety_dist
    
    @property
    def drift_threshold(self) -> float:
        if self.__drift_threshold is None:
            self.__drift_threshold = drift_threshold(self.val1.l, self.val2.l)
        return self.__drift_threshold

    @property
    def p12(self) -> np.ndarray:
        if self.__p12 is None:
            self.__p12 = self.val2.p - self.val1.p
        return self.__p12

    @property
    def p21(self) -> np.ndarray:
        if self.__p21 is None:
            self.__p21 = -self.p12
        return self.__p21

    @property
    def o_distance(self) -> float:
        if self.__o_distance is None:
            self.__o_distance = float(max(magnitude(self.p12), EPSILON))
        return self.__o_distance

    @property
    def angle_p21_v2(self) -> float:
        if self.__angle_p21_v2 is None:
            self.__angle_p21_v2 = compute_angle(self.p21, self.val2.v)
        return self.__angle_p21_v2

    @property
    def sin_half_col_cone_theta(self) -> float:
        if self.__sin_half_col_cone_theta is None:
            self.__sin_half_col_cone_theta = np.clip(max(self.val1.r, self.val2.r) / self.o_distance, -1, 1)
        return self.__sin_half_col_cone_theta

    @property
    def angle_half_col_cone(self) -> float:
        if self.__angle_half_col_cone is None:
            self.__angle_half_col_cone = abs(np.arcsin(self.sin_half_col_cone_theta))
        return self.__angle_half_col_cone

    @property
    def v12(self) -> np.ndarray:
        if self.__v12 is None:
            self.__v12 = self.val1.v - self.val2.v
        return self.__v12

    @property
    def v12_norm_stable(self) -> float:
        if self.__v12_norm_stable is None:
            self.__v12_norm_stable = float(max(magnitude(self.v12), EPSILON))
        return self.__v12_norm_stable

    @property
    def angle_p12_v1(self) -> float:
        if self.__angle_p12_v1 is None:
            self.__angle_p12_v1 = compute_angle(self.p12, self.val1.v)
        return self.__angle_p12_v1

    @property
    def tcpa(self) -> float:
        if self.__tcpa is None:
            self.__tcpa = np.dot(self.p12, self.v12) / self.v12_norm_stable**2
        return self.__tcpa

    @property
    def dcpa(self) -> float:
        if self.__dcpa is None:
            self.__dcpa = magnitude(self.p21 + self.v12 * max(0, self.tcpa))
        return self.__dcpa

    @property
    def vis_distance(self) -> float:
        if self.__vis_distance is None:
            self.__vis_distance = vis_distance(
                self.angle_p21_v2 >= SIDE_ANGLE,
                self.val2.l,
                self.angle_p12_v1 >= SIDE_ANGLE,
                self.val1.l,
            )
        return self.__vis_distance

    @property
    def domain_violation_times(self) -> List[float]:
        if self.__domain_violation_times is None:
            self.__domain_violation_times = self._calc_domain_violation_times()
        return self.__domain_violation_times

    def _calc_domain_violation_times(self) -> List[float]:
        # Relative position and velocity
        v_21 = self.val2.v - self.val1.v

        # Coefficients for the quadratic equation
        a = np.dot(v_21, v_21)
        b = 2 * np.dot(self.p12, v_21)
        c = np.dot(self.p12, self.p12) - self.safety_dist**2

        # Calculate discriminant
        discriminant = b**2 - 4 * a * c

        # Check for real solutions (collision possible)
        if discriminant < 0:
            return []

        sqrt_discriminant = np.sqrt(discriminant)
        times: List[float] = []
        # Find times of collision
        t1 = (-b + sqrt_discriminant) / (2 * max(a, EPSILON))
        if t1 >= 0:
            times.append(t1)
        t2 = (-b - sqrt_discriminant) / (2 * max(a, EPSILON))
        if t2 >= 0:
            times.append(t2)
        return times


class EvaluationCache(Dict[Tuple[ActorVariable, ActorVariable], GeometricProperties]):
    def __init__(self, assignments: Assignments = Assignments(), *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.assignments = assignments

    def get_props(self, var1: ActorVariable, var2: ActorVariable) -> GeometricProperties:
        props = self.get((var1, var2), None)
        if props is None:
            props = GeometricProperties(var1, var2, self.assignments)
            self[(var1, var2)] = props
        return props


# class ObstacleToVesselProperties(GeometricProperties):
#     def __init__(
#         self,
#         var1: StaticObstacleVariable,
#         var2: VesselVariable,
#         assignments: Assignments,
#     ):
#         super().__init__(var1, var2, assignments)

#     @property
#     def tcpa(self) -> float:
#         return np.dot(self.p21, self.val2.v_norm)

#     @property
#     def dcpa(self) -> float:
#         return magnitude(self.p21 - self.tcpa * self.val2.v_norm)

#     @property
#     def vis_distance(self) -> float:
#         return o2VisibilityByo1(True, self.val1.r)

#     @property
#     def collision_points(self) -> List[np.ndarray]:
#         # Coefficients for the quadratic equation
#         a = np.dot(self.val2.v, self.val2.v)
#         b = 2 * np.dot(self.p12, self.val2.v)
#         c = np.dot(self.p12, self.p12) - self.safety_dist**2

#         # Calculate discriminant
#         discriminant = b**2 - 4 * a * c

#         # Check for real solutions (collision possible)
#         if discriminant < 0:
#             return []

#         sqrt_discriminant = np.sqrt(discriminant)
#         collision_points = []

#         # Find times of collision
#         t1 = (-b + sqrt_discriminant) / (2 * a)
#         t2 = (-b - sqrt_discriminant) / (2 * a)

#         # Check if times are within the time limit and positive
#         for t in [t1, t2]:
#             if 0 <= t <= np.inf:
#                 # Compute the collision points
#                 collision_point_vessel2 = self.val2.p + self.val2.v * t
#                 collision_points.append(collision_point_vessel2)

#         # Return the list of collision points as standard list of np.ndarray
#         return collision_points
