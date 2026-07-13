from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from logical_level.mapping.instance_initializer import InstanceInitializer
from logical_level.models.actor_variable import (
    ActorVariable,
    StaticObstacleVariable,
    VesselVariable,
)
from logical_level.models.relation_constraints_concept.composites import (
    RelationConstrComposite,
)
from utils.scenario import Scenario


@dataclass(frozen=True)
class LogicalScenario(Scenario):
    initializer: InstanceInitializer
    relation_constraint: RelationConstrComposite
    xl: List[float]
    xu: List[float]

    def __post_init__(self):
        # Convert lists to tuples to ensure immutability and hashability.
        object.__setattr__(self, "xl", tuple(self.xl))
        object.__setattr__(self, "xu", tuple(self.xu))

    @property
    def os_variable(self) -> ActorVariable:
        return next((v for v in self.vessel_variables if v.is_os))

    @property
    def actor_variables(self) -> List[ActorVariable]:
        return self.initializer.actor_variables

    @property
    def ts_variables(self) -> List[VesselVariable]:
        return [var for var in self.vessel_variables if not var.is_os]

    @property
    def vessel_variables(self) -> List[VesselVariable]:
        return [var for var in self.initializer.actor_variables if var.is_vessel]

    @property
    def obstacle_variables(self) -> List[StaticObstacleVariable]:
        return [var for var in self.initializer.actor_variables if not var.is_vessel]

    @property
    def obstacle_number(self) -> int:
        return len(self.obstacle_variables)

    @property
    def vessel_number(self) -> int:
        return len(self.vessel_variables)

    @property
    def all_variable_number(self) -> int:
        return len(self.xl)

    def get_population(self, pop_size: Optional[int]) -> List[List[float]]:
        if pop_size is None:
            pop_size = 1
        population = self.initializer.get_population(pop_size=pop_size)
        return population

    def pop_to_np_array(self, pop: List[List[float]]):
        new_pop = []
        for p in pop:
            new_pop.append(np.array(p))
        return np.array(new_pop)
