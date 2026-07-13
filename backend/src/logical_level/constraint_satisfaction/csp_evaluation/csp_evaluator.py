import gc
import traceback
from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import datetime
from typing import Optional

from concrete_level.trajectory_generation.scene_builder import SceneBuilder
from functional_level.metamodels.functional_scenario import FunctionalScenario
from logical_level.constraint_satisfaction.aggregates import Aggregate
from logical_level.constraint_satisfaction.assignments import Assignments
from logical_level.constraint_satisfaction.csp_evaluation.csp_solver import CSPSolver
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from logical_level.models.logical_scenario import LogicalScenario


class CSPEvaluator(ABC):
    @abstractmethod
    def evaluate(
        self,
        logical_scenario: LogicalScenario,
        functional_scenario: Optional[FunctionalScenario],
        save: bool,
        current_eval_time: float,
        max_eval_time: float,
    ) -> EvaluationData:
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass


class CSPEvaluatorImpl(CSPEvaluator):
    def __init__(
        self,
        solver: CSPSolver,
        measurement_name: str,
        test_config: EvaluationData,
        verbose: bool,
    ):
        self.solver = solver
        self.measurement_name = measurement_name
        self.test_config = test_config
        self.verbose = verbose

    def evaluate(
        self,
        logical_scenario: LogicalScenario,
        functional_scenario: Optional[FunctionalScenario],
        save: bool,
        current_eval_time: float,
        max_eval_time: float,
    ) -> EvaluationData:
        try:
            eval_data = deepcopy(self.test_config)
            eval_data.vessel_number = logical_scenario.vessel_number
            eval_data.obstacle_number = logical_scenario.obstacle_number
            eval_data.measurement_name = self.measurement_name
            eval_data.algorithm_desc = self.solver.algorithm_desc()
            eval_data.scenario_name = logical_scenario.name
            eval_data.timestamp = datetime.now().isoformat()
            eval_data.timeout = min(eval_data.timeout, max_eval_time - current_eval_time)

            gc.collect()

            initial_pop = logical_scenario.get_population(eval_data.population_size)
            some_input = self.solver.init_problem(logical_scenario, functional_scenario, initial_pop, eval_data)

            some_results = self.solver.evaluate(some_input, eval_data)

            best_solution, number_of_generations, runtime = self.solver.convert_results(some_results, eval_data)
            eval_data.evaluation_time = runtime

            assignments = Assignments(logical_scenario.actor_variables).update_from_individual(best_solution)
            eval_data.best_scene = SceneBuilder().build_from_assignments(assignments)
            eval_data.number_of_generations = number_of_generations

            aggregate = Aggregate.factory(logical_scenario, eval_data.aggregate_strat, minimize=True)
            penalty = aggregate.derive_penalty(best_solution)
            eval_data.best_fitness = aggregate.evaluate(best_solution)
            eval_data.best_fitness_index = penalty.value

            if not penalty.is_zero:
                eval_data.evaluation_time = eval_data.timeout

            if self.verbose:
                print(penalty.pretty_info())
                print("Best individual is:", best_solution)
                print("Best individual fitness is:", eval_data.best_fitness)

        except Exception as e:
            eval_data.error_message = f"{str(e)}\n{traceback.format_exc()}"
            print(eval_data.error_message)
        finally:
            if save and (current_eval_time + eval_data.evaluation_time) <= max_eval_time + 10:
                eval_data.save_as_measurement()
            return eval_data

    @property
    def name(self):
        return self.measurement_name
