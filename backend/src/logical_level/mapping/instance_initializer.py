import random
from abc import ABC, abstractmethod
from typing import List

import numpy as np

from logical_level.models.actor_variable import ActorVariable


class InstanceInitializer(ABC):
    def __init__(self, name: str, actor_variables: List[ActorVariable]) -> None:
        self.actor_variables = actor_variables
        self.name = name

    @abstractmethod
    def _do_get_population(self) -> List[float]:
        pass

    def get_population(self, pop_size) -> List[List[float]]:
        result: List[List[float]] = []
        for i in range(int(pop_size)):
            result.append(self._do_get_population())
        return result


class RandomInstanceInitializer(InstanceInitializer):
    name = "uniform"

    def __init__(self, actor_variable: List[ActorVariable]) -> None:
        super().__init__(self.name, actor_variable)

    def _do_get_population(self) -> List[float]:
        population: List[float] = []
        for actor_variable in self.actor_variables:
            population += [random.uniform(x, y) for x, y in zip(actor_variable.lower_bounds, actor_variable.upper_bounds)]
        return population


class DeterministicInitializer(InstanceInitializer):
    name = "deterministic"

    def __init__(self, actor_variable: List[ActorVariable]) -> None:
        super().__init__(self.name, actor_variable)

    def _do_get_population(self) -> List[float]:
        population: List[float] = []
        for actor_variable in self.actor_variables:
            population += [(x + y) / 2 for x, y in zip(actor_variable.lower_bounds, actor_variable.upper_bounds)]
        return population


class LatinHypercubeInitializer(InstanceInitializer):
    name = "lhs"

    def __init__(self, actor_variable: List[ActorVariable]) -> None:
        super().__init__(self.name, actor_variable)

    def lhs_sampling(self, n_samples: int, lower_bounds: List[float], upper_bounds: List[float]) -> np.ndarray:
        """
        Generate Latin Hypercube samples within specified bounds for each dimension.

        :param n_samples: Number of samples to generate.
        :param lower_bounds: List of lower bounds for each dimension.
        :param upper_bounds: List of upper bounds for each dimension.
        :return: Array of Latin Hypercube samples.
        """
        n_dim = len(lower_bounds)
        result = np.zeros((n_samples, n_dim))

        # Create intervals for each dimension
        intervals = np.linspace(0, 1, n_samples + 1)

        for i in range(n_dim):
            points = np.random.uniform(intervals[:-1], intervals[1:])
            np.random.shuffle(points)  # Ensure random ordering of points in this dimension
            result[:, i] = lower_bounds[i] + points * (upper_bounds[i] - lower_bounds[i])

        return result

    def _do_get_population(self) -> List[float]:
        population: List[float] = []
        for actor_variable in self.actor_variables:
            population += self.lhs_sampling(1, actor_variable.lower_bounds, actor_variable.upper_bounds)[0]
        return population
