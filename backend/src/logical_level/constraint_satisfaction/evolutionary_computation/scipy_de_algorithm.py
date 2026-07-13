import time
from typing import List, Tuple

import numpy as np
from scipy.optimize import OptimizeResult, differential_evolution

from logical_level.constraint_satisfaction.aggregates import Aggregate
from logical_level.constraint_satisfaction.csp_evaluation.csp_solver import CSPSolver
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from logical_level.models.logical_scenario import LogicalScenario


class ObjectiveMonitorCallback:
    def __init__(self, aggregate: Aggregate, max_time_sec, verbose: bool):
        self.start_time = time.time()
        self.max_time_sec = max_time_sec
        self.current_best_objective = np.inf
        self.aggregate = aggregate
        self.verbose = verbose

    def __call__(self, xk, convergence):
        runtime = time.time() - self.start_time
        if runtime >= self.max_time_sec:
            if self.verbose:
                print("Termination stopped due to timeout")
            return True  # Stop optimization

        if self.current_best_objective == 0.0:
            if self.verbose:
                print("Optimal solution reached")
            return True  # Stop optimization
        return False

    def objective(self, solution):
        objective = self.aggregate.evaluate(solution)[0]
        if self.current_best_objective > objective:
            self.current_best_objective = objective
        return objective


class SciPyDEAlgorithm(CSPSolver):
    def __init__(self, verbose: bool) -> None:
        self.verbose = verbose
        self.current_best_objective = np.inf

    @classmethod
    def algorithm_desc(cls) -> str:
        return "scipy_DE_algorithm"

    def init_problem(
        self,
        logical_scenario: LogicalScenario,
        initial_population: List[List[float]],
        eval_data: EvaluationData,
    ):
        aggregate = Aggregate.factory(logical_scenario, eval_data.aggregate_strat, minimize=True)

        return (
            list(zip(logical_scenario.xl, logical_scenario.xu)),
            aggregate,
            initial_population,
        )

    def evaluate(
        self,
        some_input: Tuple[List[Tuple[int, int]], Aggregate, List[List[float]]],
        eval_data: EvaluationData,
    ):
        bounds, aggregate, initial_pop = some_input

        objective_monitor = ObjectiveMonitorCallback(aggregate, eval_data.timeout, self.verbose)
        res = differential_evolution(
            objective_monitor.objective,
            bounds,
            popsize=eval_data.population_size,
            maxiter=np.iinfo(np.int64).max,
            tol=-np.inf,  # Relative tolerance for convergence
            atol=-np.inf,
            mutation=eval_data.mutate_prob,  # Mutation constant
            recombination=eval_data.crossover_prob,  # Recombination constant (crossover)
            callback=objective_monitor,  # Custom callback to handle time termination
            disp=self.verbose,
            init=initial_pop,
        )
        runtime = time.time() - objective_monitor.start_time
        if self.verbose:
            print(f"Optimization completed in {runtime:.2f} seconds with {res.nit} iterations.")
            print(f"Best solution: {res.x}, Objective value: {res.fun}")
        return res, runtime

    def convert_results(self, some_results: Tuple[OptimizeResult, float], eval_data: EvaluationData) -> Tuple[List[float], int, float]:
        result, runtime = some_results
        if self.verbose:
            print(result)
        iter_num = result["nit"]
        X: np.ndarray = result["x"]
        # F : np.ndarray = np.array([result['fun']])
        return X.tolist(), iter_num, runtime
