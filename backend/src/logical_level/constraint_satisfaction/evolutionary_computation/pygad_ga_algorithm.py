import time
from typing import List, Optional, Tuple

import numpy as np
import pygad

from functional_level.metamodels.functional_scenario import FunctionalScenario
from logical_level.constraint_satisfaction.aggregates import Aggregate
from logical_level.constraint_satisfaction.csp_evaluation.csp_solver import CSPSolver
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from logical_level.models.logical_scenario import LogicalScenario


class PyGadGAAlgorithm(CSPSolver):
    def __init__(self, verbose: bool) -> None:
        self.verbose = verbose

    @classmethod
    def algorithm_desc(cls) -> str:
        return "pygad_GA_algorithm"

    class OnGenerationCallback:
        def __init__(
            self,
            logical_scenario: LogicalScenario,
            eval_data: EvaluationData,
            start_time: float,
            verbose: bool,
        ):
            self.logical_scenario = logical_scenario
            self.eval_data = eval_data
            self.start_time = start_time
            self.verbose = verbose

        def execute(self, ga_instance: pygad.GA):
            if self.verbose:
                print(f"Generation = {ga_instance.generations_completed}")
                print(f"Best solution = {ga_instance.best_solution()}")
            elapsed_time = time.time() - self.start_time
            solution, solution_fitness, solution_idx = ga_instance.best_solution()
            if abs(solution_fitness) == 0.0:
                if self.verbose:
                    print(f"Terminating due to fitness reaching 0.0.")
                raise StopIteration
            if elapsed_time > self.eval_data.timeout:
                if self.verbose:
                    print(f"Terminating due to timeout of {self.eval_data.timeout} seconds.")
                raise StopIteration

    def init_problem(
        self,
        logical_scenario: LogicalScenario,
        functional_scenario: Optional[FunctionalScenario],
        initial_population: List[List[float]],
        eval_data: EvaluationData,
    ):
        def fitness_func(cls, solution, solution_idx):
            return Aggregate.factory(logical_scenario, eval_data.aggregate_strat, minimize=False).evaluate(solution)[0]

        on_generation_callback = self.OnGenerationCallback(logical_scenario, eval_data, time.time(), self.verbose)

        # Setting up the GA
        ga_instance: pygad.GA = pygad.GA(
            num_generations=np.iinfo(np.int64).max,
            num_parents_mating=eval_data.num_parents_mating,
            fitness_func=fitness_func,
            sol_per_pop=eval_data.population_size,
            num_genes=logical_scenario.all_variable_number,
            gene_space=[{"low": low, "high": high} for low, high in zip(logical_scenario.xl, logical_scenario.xu)],
            initial_population=initial_population,
            on_generation=on_generation_callback.execute,
            mutation_probability=eval_data.mutate_prob,
            crossover_probability=eval_data.crossover_prob,
            parent_selection_type="tournament",
            K_tournament=2,
        )
        return ga_instance

    def evaluate(
        self,
        some_input: Tuple[pygad.GA, OnGenerationCallback],
        eval_data: EvaluationData,
    ):
        try:
            algo, on_generation_callback = some_input
            on_generation_callback.start_time = time.time()
            # Run the GA
            algo.run()
        except StopIteration:
            pass
        finally:
            return some_input, time.time() - on_generation_callback.start_time

    def convert_results(self, some_results: Tuple[pygad.GA, float], eval_data: EvaluationData) -> Tuple[List[float], int, float]:
        ga_instance, runtime = some_results
        # After the GA run, print the best solution found
        solution, solution_fitness, solution_idx = ga_instance.best_solution()
        # if self.verbose:
        #     # Get the best solutions
        #     num_best_solutions = 1
        #     population_fitness = ga_instance.last_generation_fitness
        #     sorted_indices = np.argsort(population_fitness)[::-1]  # Sort in descending order of fitness
        #     best_solutions = [ga_instance.population[idx] for idx in sorted_indices[:num_best_solutions]]
        #     for sol in best_solutions:
        #         ColregPlot(self.logical_scenario.update(sol))
        return list(solution.flatten()), ga_instance.generations_completed, runtime
