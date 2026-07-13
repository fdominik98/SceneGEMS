from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List

from logical_level.mapping.static_obstacle import StaticObstacleType
from logical_level.mapping.vessel_type import VesselType
from utils.global_constants import EPSILON, MAX_COORD, MAX_HEADING, MIN_COORD, MIN_HEADING
@dataclass(frozen=True)
class ActorVariable(ABC):
    id: int

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return self.name

    @property
    @abstractmethod
    def upper_bounds(self) -> List[float]:
        pass

    @property
    @abstractmethod
    def lower_bounds(self) -> List[float]:
        pass

    @property
    @abstractmethod
    def is_vessel(self) -> bool:
        pass

    def __len__(self) -> int:
        return len(self.lower_bounds)

    @property
    def min_coord(self) -> float:
        return MIN_COORD

    @property
    def max_coord(self) -> float:
        return MAX_COORD

    @property
    @abstractmethod
    def type_name(self) -> str:
        pass
    
    @property
    @abstractmethod
    def min_speed(self) -> float:
        pass

    @property
    @abstractmethod
    def max_speed(self) -> float:
        pass

@dataclass(frozen=True)
class VesselVariable(ActorVariable):
    vessel_type: VesselType

    @property
    def type_name(self) -> str:
        return self.vessel_type.name

    @property
    def min_length(self) -> float:
        return self.vessel_type.min_length - EPSILON

    @property
    def max_length(self) -> float:
        return self.vessel_type.max_length + EPSILON

    @property
    def min_beam(self) -> float:
        return self.vessel_type.min_beam - EPSILON

    @property
    def max_beam(self) -> float:
        return self.vessel_type.max_beam + EPSILON

    @property
    def min_speed(self) -> float:
        return EPSILON

    @property
    def max_speed(self) -> float:
        return self.vessel_type.max_speed + EPSILON

    @property
    def min_heading(self) -> float:
        return MIN_HEADING - EPSILON

    @property
    def max_heading(self) -> float:
        return MAX_HEADING + EPSILON

    @property
    def is_vessel(self) -> bool:
        return True

    @property
    @abstractmethod
    def is_os(self) -> bool:
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    def upper_bounds(self) -> List[float]:
        return [
            self.max_coord,
            self.max_coord,
            self.max_heading,
            self.max_length,
            self.max_speed,
        ]

    @property
    def lower_bounds(self) -> List[float]:
        return [
            self.min_coord,
            self.min_coord,
            self.min_heading,
            self.min_length,
            self.min_speed,
        ]


@dataclass(frozen=True)
class OSVariable(VesselVariable):
    @property
    def min_heading(self) -> float:
        return MAX_HEADING / 2 - EPSILON

    @property
    def max_heading(self) -> float:
        return MAX_HEADING / 2 + EPSILON

    @property
    def min_coord(self) -> float:
        return -EPSILON

    @property
    def max_coord(self) -> float:
        return EPSILON

    @property
    def name(self) -> str:
        return f"OS_{self.id}"

    @property
    def is_os(self) -> bool:
        return True


@dataclass(frozen=True)
class TSVariable(VesselVariable):
    @property
    def name(self) -> str:
        return f"TS_{self.id}"

    @property
    def is_os(self) -> bool:
        return False


@dataclass(frozen=True)
class StaticObstacleVariable(ActorVariable):
    obstacle_type: StaticObstacleType

    @property
    def type_name(self) -> str:
        return self.obstacle_type.name

    @property
    def name(self) -> str:
        return f"SO_{self.id}"

    @property
    def min_radius(self) -> float:
        return self.obstacle_type.min_radius

    @property
    def max_radius(self) -> float:
        return self.obstacle_type.max_radius

    @property
    def upper_bounds(self) -> List[float]:
        return [self.max_coord, self.max_coord, self.max_radius]

    @property
    def lower_bounds(self) -> List[float]:
        return [self.min_coord, self.min_coord, self.min_radius]

    @property
    def is_vessel(self) -> bool:
        return False
    
    @property
    def min_speed(self) -> float:
        return 0.0 - EPSILON
    
    @property
    def max_speed(self) -> float:
        return 0.0 + EPSILON
