import random
import time
from itertools import product
from multiprocessing import Process, cpu_count
from typing import Any, List, Tuple

import numpy as np

from functional_level.models.functional_model_manager import FunctionalModelManager
from logical_level.constraint_satisfaction.aggregates import ActorAggregate, AggregateAll, AggregateAllSwarm
from logical_level.constraint_satisfaction.csp_evaluation.csp_evaluator import CSPEvaluatorImpl
from logical_level.constraint_satisfaction.csp_evaluation.csp_scheduler import CSPSchedulerFactory
from logical_level.constraint_satisfaction.csp_evaluation.csp_solver import CSPSolver
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from logical_level.constraint_satisfaction.evolutionary_computation.pygad_ga_algorithm import PyGadGAAlgorithm
from logical_level.constraint_satisfaction.evolutionary_computation.pymoo_nsga2_algorithm import PyMooNSGA2Algorithm
from logical_level.constraint_satisfaction.evolutionary_computation.pymoo_nsga3_algorithm import PyMooNSGA3Algorithm
from logical_level.constraint_satisfaction.evolutionary_computation.pyswarm_pso_algorithm import PySwarmPSOAlgorithm
from logical_level.constraint_satisfaction.evolutionary_computation.scipy_de_algorithm import SciPyDEAlgorithm
from logical_level.models.logical_model_manager import LogicalModelManager
from utils.evaluation_config import DC_SB_III, MSR_SB_II

WARMUPS = 0
RANDOM_SEED = 1235
TIMEOUT = 180
AVERAGE_TIME_PER_SCENE = 180
INIT_METHOD = "uniform"
VERBOSE = False

MEAS_NAME = "parameter_test_base"

LOGICAL_SCENARIO = LogicalModelManager.get_x_vessel_y_obstacle_scenarios(6, 0)
FUNCTIONAL_SCENARIOS = random.sample(FunctionalModelManager.get_x_vessel_y_obstacle_scenarios(6, 0), 5)
# CONFIG_GROUP='SB-O'
CONFIG_GROUP = DC_SB_III


def run_batches(
    combinations_GA_batch,
    combinations_NSGA_batch,
    combinations_PSO_batch,
    combination_DE_batch,
    core_id,
):
    def create_GA_config() -> EvaluationData:
        if len(combinations_GA_batch) == 0:
            return None
        (
            population_size,
            num_parents_mating,
            mutate_prob,
            crossover_prob,
            mutate_eta,
            crossover_eta,
        ) = combinations_GA_batch[0]
        while num_parents_mating > population_size:
            del combinations_GA_batch[0]
            if len(combinations_GA_batch) == 0:
                return None
            (
                population_size,
                num_parents_mating,
                mutate_prob,
                crossover_prob,
                mutate_eta,
                crossover_eta,
            ) = combinations_GA_batch[0]

        return EvaluationData(
            population_size=population_size,
            num_parents_mating=num_parents_mating,
            mutate_eta=mutate_eta,
            mutate_prob=mutate_prob,
            crossover_eta=crossover_eta,
            config_group=CONFIG_GROUP,
            crossover_prob=crossover_prob,
            timeout=TIMEOUT,
            init_method=INIT_METHOD,
            random_seed=RANDOM_SEED,
            aggregate_strat=AggregateAll.name,
        )

    def create_NSGA_vessel_config() -> EvaluationData:
        if len(combinations_NSGA_batch) == 0:
            return None
        (
            population_size,
            mutate_prob,
            crossover_prob,
            mutate_eta,
            crossover_eta,
        ) = combinations_NSGA_batch[0]
        return EvaluationData(
            population_size=population_size,
            mutate_eta=mutate_eta,
            mutate_prob=mutate_prob,
            crossover_eta=crossover_eta,
            crossover_prob=crossover_prob,
            timeout=TIMEOUT,
            config_group=CONFIG_GROUP,
            init_method=INIT_METHOD,
            random_seed=RANDOM_SEED,
            aggregate_strat=ActorAggregate.name,
        )

    def create_NSGA_all_config() -> EvaluationData:
        if len(combinations_NSGA_batch) == 0:
            return None
        (
            population_size,
            mutate_prob,
            crossover_prob,
            mutate_eta,
            crossover_eta,
        ) = combinations_NSGA_batch[0]
        return EvaluationData(
            population_size=population_size,
            mutate_eta=mutate_eta,
            mutate_prob=mutate_prob,
            crossover_eta=crossover_eta,
            crossover_prob=crossover_prob,
            timeout=TIMEOUT,
            config_group=CONFIG_GROUP,
            init_method=INIT_METHOD,
            random_seed=RANDOM_SEED,
            aggregate_strat=AggregateAll.name,
        )

    def create_PSO_config() -> EvaluationData:
        if len(combinations_PSO_batch) == 0:
            return None
        population_size, c_1, c_2, w = combinations_PSO_batch[0]
        return EvaluationData(
            population_size=population_size,
            c_1=c_1,
            c_2=c_2,
            w=w,
            timeout=TIMEOUT,
            config_group=CONFIG_GROUP,
            init_method=INIT_METHOD,
            random_seed=RANDOM_SEED,
            aggregate_strat=AggregateAllSwarm.name,
        )

    def create_DE_config() -> EvaluationData:
        if len(combination_DE_batch) == 0:
            return None
        population_size, mutate_prob, crossover_prob = combination_DE_batch[0]
        while population_size <= 4:
            del combination_DE_batch[0]
            if len(combination_DE_batch) == 0:
                return None
            population_size, mutate_prob, crossover_prob = combination_DE_batch[0]

        return EvaluationData(
            population_size=population_size,
            mutate_prob=mutate_prob,
            crossover_prob=crossover_prob,
            timeout=TIMEOUT,
            init_method=INIT_METHOD,
            random_seed=RANDOM_SEED,
            aggregate_strat=AggregateAll.name,
        )

    solvers: List[Tuple[Any, CSPSolver]] = [
        # (create_GA_config, PyGadGAAlgorithm(verbose=VERBOSE)),
        # (create_NSGA_vessel_config, PyMooNSGA2Algorithm(verbose=VERBOSE)),
        (create_NSGA_vessel_config, PyMooNSGA3Algorithm(verbose=VERBOSE)),
        # (create_NSGA_all_config, PyMooNSGA2Algorithm(verbose=VERBOSE)),
        # (create_NSGA_all_config, PyMooNSGA3Algorithm(verbose=VERBOSE)),
        # (create_PSO_config, PySwarmPSOAlgorithm(verbose=VERBOSE)),
        # (create_DE_config, SciPyDEAlgorithm(verbose=VERBOSE)),
    ]

    while True:
        runs = 0
        for config_fun, solver in solvers:
            config: EvaluationData = config_fun()
            if config is not None:
                evaluator = CSPEvaluatorImpl(solver, MEAS_NAME, config, VERBOSE)

                scheduler = CSPSchedulerFactory.factory(
                    evaluator,
                    LOGICAL_SCENARIO,
                    RANDOM_SEED,
                    WARMUPS,
                    AVERAGE_TIME_PER_SCENE,
                    config.init_method,
                )
                scheduler.run(core_id)
                runs += 1
        if runs == 0:
            break
        if len(combinations_GA_batch) > 0:
            del combinations_GA_batch[0]
        if len(combinations_NSGA_batch) > 0:
            del combinations_NSGA_batch[0]
        if len(combinations_PSO_batch) > 0:
            del combinations_PSO_batch[0]
        if len(combination_DE_batch) > 0:
            del combination_DE_batch[0]


def main():
    population_sizes = [2, 4, 5, 8, 10, 15, 20, 30, 50, 100]
    nums_parents_mating = [2, 4, 8, 10]
    mutate_probs = [0.2, 0.5, 0.8, 1]
    crossover_probs = [0.2, 0.5, 0.8, 1]
    mutate_etas = [1, 5, 10, 15, 20]
    crossover_etas = [1, 5, 10, 15, 20]
    c1_s = [1.0, 1.5, 2.0, 2.5]
    c2_s = [1.0, 1.5, 2.0, 2.5]
    w_s = [0.4, 0.6, 0.9]

    combinations_GA = list(
        product(
            population_sizes,
            nums_parents_mating,
            mutate_probs,
            crossover_probs,
            mutate_etas,
            crossover_etas,
        )
    )
    combinations_NSGA = list(product(population_sizes, mutate_probs, crossover_probs, mutate_etas, crossover_etas))
    combinations_PSO = list(product(population_sizes, c1_s, c2_s, w_s))
    combination_DE = list(product(population_sizes, mutate_probs, crossover_probs))

    random.seed(time.time())
    random.shuffle(combinations_GA)
    random.shuffle(combinations_NSGA)
    random.shuffle(combinations_PSO)
    random.shuffle(combination_DE)

    core_count = cpu_count()

    combinations_GA_batches = np.array_split(combinations_GA, core_count)
    combinations_NSGA_batches = np.array_split(combinations_NSGA, core_count)
    combinations_PSO_batches = np.array_split(combinations_PSO, core_count)
    combination_DE_batches = np.array_split(combination_DE, core_count)

    processes: List[Process] = []
    for i in range(core_count):
        p = Process(
            target=run_batches,
            args=(
                list(combinations_GA_batches[i]),
                list(combinations_NSGA_batches[i]),
                list(combinations_PSO_batches[i]),
                list(combination_DE_batches[i]),
                i,
            ),
        )
        p.start()
        processes.append(p)

    # Wait for all processes to finish
    for p in processes:
        p.join()


if __name__ == "__main__":
    main()
