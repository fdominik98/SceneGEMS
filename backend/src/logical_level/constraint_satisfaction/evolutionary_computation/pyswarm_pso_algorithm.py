import time
from typing import List, Tuple

import numpy as np
import pyswarms as ps

from logical_level.constraint_satisfaction.aggregates import Aggregate
from logical_level.constraint_satisfaction.csp_evaluation.csp_solver import CSPSolver
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from logical_level.models.logical_scenario import LogicalScenario


class ObjectiveMonitor:
    def __init__(
        self,
        logical_scenario: LogicalScenario,
        eval_data: EvaluationData,
        max_time,
        verbose,
    ) -> None:
        self.verbose = verbose
        self.max_time = max_time
        self.start_time = time.time()
        self.best_solution: np.ndarray = np.array([])
        self.best_fitness: float = np.inf
        self.iter_count = 0
        self.aggregate = Aggregate.factory(logical_scenario, eval_data.aggregate_strat, minimize=True)

    def objective(self, x):
        self.iter_count += 1
        runtime = time.time() - self.start_time
        if runtime >= self.max_time:
            if self.verbose:
                print("Stopping due to timeout.")
            raise StopIteration()
        F = self.aggregate.evaluate(x)
        for i, f in enumerate(F):
            if f < self.best_fitness:
                self.best_fitness = f
                self.best_solution = x[i]
        if self.best_fitness == 0.0:
            if self.verbose:
                print("Optimal fitness reached.")
            raise StopIteration()
        return F

    def print(self):
        if self.verbose:
            print(f"Best Position: {self.best_solution}")
            print(f"Best Cost: {self.best_fitness}")
            print(f"Iter count: {self.iter_count}")


class PySwarmPSOAlgorithm(CSPSolver):
    def __init__(self, verbose: bool) -> None:
        self.verbose = verbose

    @classmethod
    def algorithm_desc(cls) -> str:
        return "pyswarm_PSO_algorithm"

    def init_problem(
        self,
        logical_scenario: LogicalScenario,
        initial_population: List[List[float]],
        eval_data: EvaluationData,
    ):
        pos = np.array([np.array(ind) for ind in initial_population])
        # Create a PSO instance
        optimizer = ps.single.GlobalBestPSO(
            options={"c1": eval_data.c_1, "c2": eval_data.c_2, "w": eval_data.w},
            n_particles=eval_data.population_size,
            dimensions=logical_scenario.all_variable_number,
            bounds=(np.array(logical_scenario.xl), np.array(logical_scenario.xu)),
            init_pos=pos,
        )
        monitor = ObjectiveMonitor(logical_scenario, eval_data, eval_data.timeout, self.verbose)

        return optimizer, monitor

    def evaluate(
        self,
        some_input: Tuple[ps.single.GlobalBestPSO, ObjectiveMonitor],
        eval_data: EvaluationData,
    ):
        optimizer, monitor = some_input
        try:
            optimizer.optimize(monitor.objective, iters=np.iinfo(np.int64).max, verbose=self.verbose)
        except StopIteration:
            pass
        finally:
            return monitor, time.time() - monitor.start_time

    def convert_results(self, some_results: Tuple[ObjectiveMonitor, float], eval_data: EvaluationData) -> Tuple[List[float], int, float]:
        monitor, runtime = some_results
        monitor.print()
        return monitor.best_solution.tolist(), monitor.iter_count, runtime
