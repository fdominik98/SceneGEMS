from abc import ABC, abstractmethod
from typing import List

import numpy as np

from logical_level.constraint_satisfaction.assignments import Assignments
from logical_level.models.logical_scenario import LogicalScenario
from logical_level.models.penalty import Penalty


class Aggregate(ABC):
    name = "unspecified"

    def __init__(self, logical_scenario: LogicalScenario, minimize: bool):
        super().__init__()
        self.logical_scenario = logical_scenario
        self.minimize = minimize

    @property
    def sign(self):
        return 1.0 if self.minimize else -1.0

    @property
    @abstractmethod
    def object_num(self) -> int:
        pass

    @abstractmethod
    def evaluate(self, individual: np.ndarray):
        pass

    def derive_penalty(self, individual: np.ndarray) -> Penalty:
        assignments = Assignments(self.logical_scenario.actor_variables).update_from_individual(individual)
        penalty = self.logical_scenario.relation_constraint.evaluate_penalty(assignments)
        return penalty

    def _signed_penalty(self, penalty) -> float:
        return self.sign * abs(penalty)

    def do_pass(self, individual: np.ndarray) -> bool:
        return sum(self.evaluate(individual)) == 0.0

    @staticmethod
    def factory(logical_scenario: LogicalScenario, name: str, minimize) -> "Aggregate":
        if name == ActorAggregate.name:
            return ActorAggregate(logical_scenario, minimize)
        elif name == AggregateAll.name:
            return AggregateAll(logical_scenario, minimize)
        elif name == AggregateAllSwarm.name:
            return AggregateAllSwarm(logical_scenario, minimize)
        else:
            raise Exception("Unknown aggregate")


class ActorAggregate(Aggregate):
    name = "actor"

    def __init__(self, logical_scenario: LogicalScenario, minimize):
        super().__init__(logical_scenario, minimize)

    @property
    def object_num(self) -> int:
        return int(self.logical_scenario.actor_number)

    def evaluate(self, individual: np.ndarray):
        penalty = self.derive_penalty(individual)
        return tuple((penalty.actor_penalties[var] if var in penalty.actor_penalties else 0 for var in self.logical_scenario.actor_variables))


class AggregateAll(Aggregate):
    name = "all"

    def __init__(self, logical_scenario: LogicalScenario, minimize):
        super().__init__(logical_scenario, minimize)

    @property
    def object_num(self) -> int:
        return 1

    def evaluate(self, individual: np.ndarray):
        fitness = self._signed_penalty(self.derive_penalty(individual).value)
        return (fitness,)


class AggregateAllSwarm(AggregateAll):
    name = "all_swarm"

    def __init__(self, logical_scenario: LogicalScenario, minimize):
        super().__init__(logical_scenario, minimize)

    def evaluate(self, individual: np.ndarray):
        fitnesses: List[float] = []
        for particle in individual:
            fitnesses.append(super().evaluate(particle)[0])
        return np.array(fitnesses)
