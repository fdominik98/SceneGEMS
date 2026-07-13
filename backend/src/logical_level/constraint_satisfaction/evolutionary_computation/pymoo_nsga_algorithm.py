from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

import matplotlib
import matplotlib.pyplot as plt
from pymoo.core.problem import ElementwiseProblem
from pymoo.core.result import Result
from pymoo.optimize import minimize

from functional_level.metamodels.functional_scenario import FunctionalScenario
from logical_level.constraint_satisfaction.aggregates import Aggregate
from logical_level.constraint_satisfaction.csp_evaluation.csp_solver import CSPSolver
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from logical_level.models.logical_scenario import LogicalScenario

matplotlib.cm.get_cmap = matplotlib.colormaps.get_cmap
import time

from pymoo.algorithms.base.genetic import GeneticAlgorithm
from pymoo.core.callback import Callback
from pymoo.core.termination import Termination


# Define the custom multi-objective optimization problem
class NSGAProblem(ElementwiseProblem):
    def __init__(self, logical_scenario: LogicalScenario, eval_data: EvaluationData):
        self.aggregate = Aggregate.factory(logical_scenario, eval_data.aggregate_strat, minimize=True)
        super().__init__(
            n_var=logical_scenario.all_variable_number,  # Number of decision variables
            n_obj=self.aggregate.object_num,  # Number of objective functions
            n_constr=0,  # Number of constraints
            xl=logical_scenario.xl,  # Lower bounds for variables
            xu=logical_scenario.xu,
        )  # Upper bounds for variables

    def _evaluate(self, x, out, *args, **kwargs):
        out["F"] = self.aggregate.evaluate(x)


class OptimumTermination(Termination):
    def __init__(self, max_time, verbose):
        super().__init__()
        self.verbose = verbose
        self.max_time = max_time
        self.start_time = time.time()

    def _update(self, algorithm: GeneticAlgorithm):
        # Check for timeout
        runtime = time.time() - self.start_time
        if runtime >= self.max_time:
            if self.verbose:
                print("Stopping due to timeout.")
            return 1.0

        if len(algorithm.callback.best_objective) == 0:
            return 0.0

        f_dist = sum(algorithm.callback.best_objective)
        if f_dist == 0.0:
            if self.verbose:
                print("Stopping as a solution with the desired fitness value is found.")
            return 1.0

        return 0.0


class BestSolutionCallback(Callback):
    def __init__(self, start_time, verbose: bool):
        super().__init__()
        self.verbose = verbose
        self.best_solution: List[float] = []
        self.best_objective: List[float] = []
        self.best_dist = None
        self.number_of_generations = 0
        self.start_time = start_time

    def notify(self, algorithm: GeneticAlgorithm):
        current_pop = algorithm.pop
        for ind in current_pop:
            f_dist = sum(ind.F)
            if self.best_dist == None or (f_dist < self.best_dist):
                self.best_solution = ind.X
                self.best_objective = ind.F
                self.best_dist = f_dist
                if self.verbose:
                    print(f"{int(time.time() - self.start_time)} - New best solution found: {ind.X} with objective: {ind.F}")
        self.number_of_generations += 1


class PyMooNSGAAlgorithm(CSPSolver, ABC):
    def __init__(self, verbose: bool) -> None:
        self.verbose = verbose

    @abstractmethod
    def init_problem(
        self,
        logical_scenario: LogicalScenario,
        functional_scenario: Optional[FunctionalScenario],
        initial_population: List[List[float]],
        eval_data: EvaluationData,
    ):
        pass

    def evaluate(self, some_input, eval_data: EvaluationData):
        # Perform the optimization
        problem, algorithm = some_input

        termination = OptimumTermination(eval_data.timeout, self.verbose)
        callback = BestSolutionCallback(termination.start_time, self.verbose)

        res: Result = minimize(
            problem,
            algorithm,
            save_history=self.verbose,
            verbose=self.verbose,
            termination=termination,
            callback=callback,
        )
        runtime = time.time() - termination.start_time
        return res, callback, runtime

    def convert_results(
        self,
        some_results: Tuple[Result, BestSolutionCallback, float],
        eval_data: EvaluationData,
    ) -> Tuple[List[float], int, float]:
        res, callback, runtime = some_results
        if self.verbose and False:
            # Plot the convergence
            n_evals = []  # corresponding number of function evaluations
            opt = []  # the optima for each evaluation

            for entry in res.history:
                n_evals.append(entry.evaluator.n_eval)
                opt.append(entry.opt[0].F)

            fig, ax = plt.subplots(figsize=(7, 5))
            ax.plot(n_evals, opt, marker="o")
            ax.set_title("Convergence")
            ax.set_xlabel("Number of Evaluations")
            ax.set_ylabel("Optimum Value")
            fig.show()

        # X = res.X.tolist()
        # X = sorted(X, key=self.logical_scenario.evaluate)
        # Extract the decision variables (X) and objective values (F)
        # return X[0], self.aggregate.evaluate(X[0])
        eval_data.num_parents_mating = 2
        return list(callback.best_solution), callback.number_of_generations, runtime
