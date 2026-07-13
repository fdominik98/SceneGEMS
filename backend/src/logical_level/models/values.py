from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from utils.colregs_approximations import vessel_radius


@dataclass(frozen=True)
class ActorValues(ABC):
    _x: float
    _y: float

    @property
    def x(self) -> float:
        return self._x

    @property
    def y(self) -> float:
        return self._y

    @property
    def p(self) -> np.ndarray:
        return np.array([self.x, self.y])

    @property
    @abstractmethod
    def r(self) -> float:
        pass

    @property
    @abstractmethod
    def v(self) -> np.ndarray:
        pass

    @property
    @abstractmethod
    def v_norm(self) -> np.ndarray:
        pass

    @property
    @abstractmethod
    def v_norm_perp(self) -> np.ndarray:
        pass

    @property
    @abstractmethod
    def h(self) -> float:
        pass

    @property
    @abstractmethod
    def l(self) -> float:
        pass

    @property
    @abstractmethod
    def sp(self) -> float:
        pass


@dataclass(frozen=True)
class VesselValues(ActorValues):
    _h: float
    _l: float
    _sp: float

    @property
    def h(self) -> float:
        return self._h

    @property
    def l(self) -> float:
        return self._l

    @property
    def sp(self) -> float:
        return self._sp

    @property
    def r(self) -> float:
        return vessel_radius(self.l)

    @property
    def v(self) -> np.ndarray:
        return np.array([np.cos(self.h), np.sin(self.h)]) * self.sp

    @property
    def v_norm(self) -> np.ndarray:
        return self.v / self.sp

    @property
    def v_norm_perp(self) -> np.ndarray:
        return np.array([self.v_norm[1], -self.v_norm[0]])


@dataclass(frozen=True)
class ObstacleValues(ActorValues):
    _r: float

    @property
    def v(self) -> np.ndarray:
        return np.array([0, 0])

    @property
    def v_norm(self) -> np.ndarray:
        return np.array([0, 0])

    @property
    def v_norm_perp(self) -> np.ndarray:
        return np.array([0, 0])

    @property
    def h(self) -> float:
        return 0.0

    @property
    def r(self) -> float:
        return self._r

    @property
    def l(self) -> float:
        return self._r

    @property
    def sp(self) -> float:
        return 0.0
