import random
from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import List, Optional, Tuple

import numpy as np
from shapely import Point, Polygon

from concrete_level.colregs_monitoring.colregs_monitor_state import COLREGSMonitorState
from concrete_level.models.actor_state import ActorState
from utils.math_utils import distance, magnitude


class TrajectoryState(Enum):
    START = auto()
    STAND_ON_1 = auto()
    GIVE_WAY_ARC = auto()
    GIVE_WAY_ARC_ADJUST = auto()
    STAND_ON_2 = auto()
    RETURN_ARC = auto()
    RETURN_ARC_ADJUST = auto()
    STAND_ON_3 = auto()


class RandomPoint:
    def __init__(self, p: np.ndarray, towards_goal: bool) -> None:
        self.p = p
        self.towards_goal = towards_goal

    @staticmethod
    def get(sample_area: List[Tuple[float, float]]):
        return RandomPoint(
            np.array([random.uniform(*sample_area[0]), random.uniform(*sample_area[1])]),
            False,
        )


class RRTNode:
    """
    RRT Node
    """

    def __init__(self, actor_state: ActorState, monitor_state: COLREGSMonitorState):
        self.actor_state = actor_state
        self.monitor_state = monitor_state
        self.cost: int = 0
        self.parent: Optional[int] = None
        self.children: set[int] = set()


class Obstacle(ABC):
    MARGIN = 0.02

    def __init__(self, x: float, y: float) -> None:
        super().__init__()
        self.p = np.array([x, y])

    @abstractmethod
    def check_no_collision(self, state: ActorState) -> bool:
        pass


class CircularObstacle(Obstacle):
    def __init__(self, p: np.ndarray, radius: float) -> None:
        super().__init__(p[0], p[1])
        self.radius = radius

    def check_no_collision(self, state: ActorState) -> bool:
        d = distance(state.p, self.p)
        if d <= self.radius + self.radius * self.MARGIN:
            return False  # collision
        return True  # safe

    def __str__(self) -> str:
        return f"Circle"


class PolygonalObstacle(Obstacle):
    def __init__(self, p1: np.ndarray, p2: np.ndarray, p3: np.ndarray, p4: np.ndarray) -> None:
        super().__init__(p1[0], p1[1])
        self.polygon = [p1, p2, p3, p4]
        # Create a Polygon object
        self.polygon_shape = Polygon(self.polygon)

    def check_no_collision(self, state: ActorState) -> bool:
        point = Point(state.p[0], state.p[1])
        return not self.polygon_shape.contains(point)

    def __str__(self) -> str:
        return f"Polygon"


class LineObstacle(Obstacle):
    def extend(self):
        return LineObstacle(self.p[0], self.p[1], self.dir_vec, self.above_initial_point, self.shift * 2)

    def __init__(self, x: float, y: float, dir_vec: np.ndarray, above_initial_point: bool, shift) -> None:
        super().__init__(x, y)
        self.shift = shift
        self.dir_vec = dir_vec
        self.above_initial_point = above_initial_point
        if above_initial_point:
            perpendicular = np.array([-dir_vec[1], dir_vec[0]])
        else:
            perpendicular = np.array([dir_vec[1], -dir_vec[0]])

        # Normalize the perpendicular vector
        self.perpendicular = perpendicular / magnitude(perpendicular)

        # Compute the shifted point on the line
        self.shifted_point = self.p + self.shift * self.perpendicular

    def __str__(self) -> str:
        return f'Line {"above" if self.above_initial_point else "below"} initial'

    def check_no_collision(self, state: ActorState) -> bool:
        # Compute the cross product to determine the position relative to the shifted line
        # Line equation is implicit: (P - shifted_point) dotted with the perpendicular vector should be checked
        position_value = np.dot(self.perpendicular, state.p - self.shifted_point)

        if self.above_initial_point:
            if position_value > 0:
                return False  # collision
            else:
                return True  # safe
        else:
            if position_value < 0:
                return True  # collision
            else:
                return False  # safe
        # Determine if point is above or below the shifted line
