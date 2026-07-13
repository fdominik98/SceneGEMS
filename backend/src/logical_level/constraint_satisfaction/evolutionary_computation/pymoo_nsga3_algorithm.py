import time
from typing import List, Optional

from pymoo.algorithms.moo.nsga3 import NSGA3
from pymoo.core.population import Population
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM
from pymoo.util.ref_dirs import get_reference_directions

from functional_level.metamodels.functional_scenario import FunctionalScenario
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from logical_level.constraint_satisfaction.evolutionary_computation.pymoo_nsga_algorithm import (
    BestSolutionCallback,
    NSGAProblem,
    OptimumTermination,
    PyMooNSGAAlgorithm,
)
from logical_level.models.logical_scenario import LogicalScenario
from utils.scenario import Scenario


class PyMooNSGA3Algorithm(PyMooNSGAAlgorithm):
    def __init__(self, verbose: bool) -> None:
        super().__init__(verbose)

    @classmethod
    def algorithm_desc(cls) -> str:
        return "pymoo_NSGA3_algorithm"

    def init_problem(
        self,
        logical_scenario: LogicalScenario,
        functional_scenario: Optional[FunctionalScenario],
        initial_population: List[List[float]],
        eval_data: EvaluationData,
    ):
        # Instantiate the problem
        problem = NSGAProblem(logical_scenario, eval_data)
        initial_population = Population.new("X", initial_population)

        if problem.aggregate.object_num > eval_data.population_size:
            eval_data.population_size = problem.aggregate.object_num

        ref_dirs = get_reference_directions("das-dennis", int(problem.aggregate.object_num), n_partitions=1)
        # Define the NSGA-III algorithm
        algorithm = NSGA3(
            ref_dirs,
            pop_size=int(eval_data.population_size),
            crossover=SBX(
                eta=eval_data.crossover_eta,
                prob=eval_data.crossover_prob,
            ),
            mutation=PM(eta=eval_data.mutate_eta, prob=eval_data.mutate_prob),
            sampling=initial_population,
        )

        return problem, algorithm
