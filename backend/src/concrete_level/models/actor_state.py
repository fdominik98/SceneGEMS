from dataclasses import dataclass
from typing import Any, Dict, Optional, Type

import numpy as np

from utils.global_constants import EPSILON
from utils.serializable import Serializable


@dataclass(frozen=True)
class ActorState(Serializable):
    x: float
    y: float
    speed: float
    heading: float

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ActorState):
            return False
        return self.x == other.x and self.y == other.y and self.speed == other.speed and self.heading == other.heading

    @property
    def p(self) -> np.ndarray:
        return np.array([self.x, self.y])

    @property
    def v(self) -> np.ndarray:
        return np.array([np.cos(self.heading), np.sin(self.heading)]) * self.speed

    @property
    def v_norm_forward(self) -> np.ndarray:
        return self.v / self.speed

    @property
    def v_norm_backward(self) -> np.ndarray:
        return -self.v_norm_forward

    @property
    def v_norm_perp_left(self) -> np.ndarray:
        return np.array([-np.sin(self.heading), np.cos(self.heading)])

    @property
    def v_norm_perp_right(self) -> np.ndarray:
        return -self.v_norm_perp_left

    @property
    def heading_deg(self):
        return np.rad2deg(self.heading)

    def point_distance_from_course(self, point: np.ndarray) -> float:
        delta = point - self.p
        forward = self.v_norm_forward
        return float(abs(delta[0] * forward[1] - delta[1] * forward[0]))

    @property
    def heading_360(self) -> float:
        return (self.heading + 2 * np.pi) % (2 * np.pi)

    def right_of(self, other: "ActorState") -> bool:
        return other.v_norm_perp_right @ (self.p - other.p) > 0 + EPSILON

    def left_of(self, other: "ActorState") -> bool:
        return other.v_norm_perp_left @ (self.p - other.p) > 0 + EPSILON

    def in_front_of(self, other: "ActorState") -> bool:
        return other.v_norm_forward @ (self.p - other.p) > 0 + EPSILON

    def behind(self, other: "ActorState") -> bool:
        return other.v_norm_backward @ (self.p - other.p) > 0 + EPSILON

    def modify_copy(
        self,
        x: Optional[float] = None,
        y: Optional[float] = None,
        speed: Optional[float] = None,
        heading: Optional[float] = None,
    ) -> "ActorState":
        return ActorState(
            x if x is not None else self.x,
            y if y is not None else self.y,
            speed if speed is not None else self.speed,
            heading if heading is not None else self.heading,
        )

    @classmethod
    def from_dict(cls: Type["ActorState"], data: Dict[str, Any]) -> "ActorState":
        return ActorState(**data)
