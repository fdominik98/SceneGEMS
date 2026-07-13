from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from functional_level.metamodels.functional_scenario import FuncObject


@dataclass(frozen=True)
class Interpretation(ABC):
    name: str = ""
    _data: Set[tuple] = field(default_factory=set)

    def __len__(self):
        return len(self._data)

    def __iter__(self):
        return iter(self._data)

    def __repr__(self):
        return f"{self.__class__.__name__}({self._data})"

    @abstractmethod
    def contains(self, objects) -> bool:
        pass

    @abstractmethod
    def _add(self, objects):
        pass


@dataclass(frozen=True)
class UnaryInterpretation(Interpretation, ABC):
    _data: Set[Tuple[FuncObject]] = field(default_factory=set)
    _data_values: Dict[FuncObject, str] = field(default_factory=lambda: defaultdict(str))

    def contains(self, object: FuncObject) -> bool:
        return (object,) in self._data

    def _add(self, objects: Tuple[FuncObject]):
        self._data.add(objects)

    def add(self, object: FuncObject, value: str = ""):
        self._add((object,))
        self._data_values[object] = value

    @property
    def first(self) -> FuncObject:
        return next(iter(self._data))[0]

    def get_value(self, o: FuncObject) -> str:
        return self._data_values[o]

    def name_with_value(self, object: FuncObject) -> str:
        return f"{self.name}_{self.get_value(object)}"

    @classmethod
    def union(cls, i1: "UnaryInterpretation", i2: "UnaryInterpretation") -> "UnaryInterpretation":
        new_data = i1._data.union(i2._data)
        new_data_values = i1._data_values | i2._data_values
        new_interpretation = cls()
        for (data,) in new_data:
            new_interpretation.add(data, new_data_values[data])
        return new_interpretation


@dataclass(frozen=True)
class BinaryInterpretation(Interpretation, ABC):
    _data: Set[Tuple[FuncObject, FuncObject]] = field(default_factory=set)

    def add(self, o1: FuncObject, o2: FuncObject):
        self._add((o1, o2))

    def contains(self, objects: Tuple[FuncObject, FuncObject]) -> bool:
        return objects in self._data

    def make_two_directional(self):
        data_temp = self._data.copy()
        for o1, o2 in data_temp:
            self._data.add((o2, o1))

    def _add(self, objects: Tuple[FuncObject, FuncObject]):
        self._data.add(objects)

    def add(self, o1: FuncObject, o2: FuncObject):
        self._add((o1, o2))

    def get_relation_descs(self, o: FuncObject) -> Set[Tuple[str, int, FuncObject]]:
        descs: Set[Tuple[str, int, FuncObject]] = set()
        for _o1, _o2 in self._data:
            if _o1 is o:
                descs.add((self.name, 1, _o2))
            elif _o2 is o:
                descs.add((self.name, 2, _o1))
        return descs

    @classmethod
    def intersection(cls, *binary_interpretations: "BinaryInterpretation"):
        datas = set.intersection(*[i._data for i in binary_interpretations])
        new_interpretation = cls(_data=datas)
        return new_interpretation


@dataclass(frozen=True)
class SeaObjectInterpretation(UnaryInterpretation):
    name: str = field(default="SeaObject", init=False)


@dataclass(frozen=True)
class VesselInterpretation(UnaryInterpretation):
    name: str = field(default="Vessel", init=False)


@dataclass(frozen=True)
class OSInterpretation(UnaryInterpretation):
    name: str = field(default="OS", init=False)


@dataclass(frozen=True)
class TSInterpretation(UnaryInterpretation):
    name: str = field(default="TS", init=False)


@dataclass(frozen=True)
class StaticObstacleInterpretation(UnaryInterpretation):
    name: str = field(default="StaticObstacle", init=False)


@dataclass(frozen=True)
class StaticObstacleTypeInterpretation(UnaryInterpretation):
    name: str = field(default="StaticObstacleType", init=False)


@dataclass(frozen=True)
class VesselTypeInterpretation(UnaryInterpretation):
    name: str = field(default="VesselType", init=False)


@dataclass(frozen=True)
class inPortSideSectorOfInterpretation(BinaryInterpretation):
    name: str = field(default="inPortSideSector", init=False)


@dataclass(frozen=True)
class inStarboardSideSectorOfInterpretation(BinaryInterpretation):
    name: str = field(default="inStarboardSideSector", init=False)


@dataclass(frozen=True)
class inSternSectorOfInterpretation(BinaryInterpretation):
    name: str = field(default="inSternSector", init=False)


@dataclass(frozen=True)
class inBowSectorOfInterpretation(BinaryInterpretation):
    name: str = field(default="inBowSector", init=False)


@dataclass(frozen=True)
class staticObstacleTypeInterpretation(BinaryInterpretation):
    name: str = field(default="staticObstacleType", init=False)


@dataclass(frozen=True)
class vesselTypeInterpretation(BinaryInterpretation):
    name: str = field(default="vesselType", init=False)


@dataclass(frozen=True)
class outVisibilityDistanceInterpretation(BinaryInterpretation):
    name: str = field(default="outVisibilityDistance", init=False)


@dataclass(frozen=True)
class atVisibilityDistanceInterpretation(BinaryInterpretation):
    name: str = field(default="atVisibilityDistance", init=False)


@dataclass(frozen=True)
class inVisibilityDistanceInterpretation(BinaryInterpretation):
    name: str = field(default="inVisibilityDistance", init=False)


@dataclass(frozen=True)
class mayCollideInterpretation(BinaryInterpretation):
    name: str = field(default="mayCollide", init=False)


@dataclass(frozen=True)
class headOnInterpretation(BinaryInterpretation):
    name: str = field(default="headOn", init=False)


@dataclass(frozen=True)
class overtakingToPortInterpretation(BinaryInterpretation):
    name: str = field(default="overtakingToPort", init=False)


@dataclass(frozen=True)
class overtakingToStarboardInterpretation(BinaryInterpretation):
    name: str = field(default="overtakingToStarboard", init=False)


@dataclass(frozen=True)
class crossingFromPortInterpretation(BinaryInterpretation):
    name: str = field(default="crossingFromPort", init=False)


@dataclass(frozen=True)
class dangerousHeadOnSectorOfInterpretation(BinaryInterpretation):
    name: str = field(default="atDangerousHeadOnSectorOf", init=False)
