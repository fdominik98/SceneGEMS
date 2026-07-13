import os
from abc import ABC, abstractmethod
from itertools import cycle, islice
from typing import List, Set, Tuple

import psutil

from concrete_level.concrete_scene_abstractor import ConcreteSceneAbstractor
from functional_level.metamodels.functional_scenario import FunctionalScenario
from functional_level.models.model_parser import ModelParser
from logical_level.constraint_satisfaction.csp_evaluation.csp_evaluator import CSPEvaluator
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from logical_level.mapping.logical_scenario_builder import LogicalScenarioBuilder
from logical_level.mapping.static_obstacle import StaticObstacleTypeMap
from logical_level.mapping.vessel_type import VesselTypeMap
from logical_level.models.logical_scenario import LogicalScenario
from utils.colregs_approximations import COLREGSConstraints
from utils.general_utils import set_seed
from utils.global_constants import FOUR_MINUTES_IN_SEC
from utils.scenario import Scenario


class CSPScheduler(ABC):
    @abstractmethod
    def run(self, core_id: int):
        pass

    @staticmethod
    def print_status(seed, covered_fecs, total_fecs, evaluator_name, eval_time, max_eval_time):
        print(f"Seed: {seed}, FECs: {covered_fecs}/{total_fecs} with {evaluator_name}. Time: {round(eval_time)}/{max_eval_time}.")

    @staticmethod
    def print_warmup_status(seed, warmup_number, total_warmups, evaluator_name):
        print(f"Seed: {seed}, Warmup {warmup_number}/{total_warmups} completed with {evaluator_name}.")


class MSRScheduler(CSPScheduler):
    def __init__(
        self,
        evaluator: CSPEvaluator,
        functional_scenarios: List[FunctionalScenario],
        random_seed: int,
        warmups: int,
        average_time_per_scene: int,
        init_method: str,
    ) -> None:
        self.evaluator = evaluator
        self.scenarios: List[Tuple[LogicalScenario, FunctionalScenario]] = [
            (
                LogicalScenarioBuilder.build_from_functional(scenario,
                                                            VesselTypeMap(),
                                                            StaticObstacleTypeMap(),
                                                            COLREGSConstraints.default_general_maritime(),
                                                             init_method),
                scenario,
            )
            for scenario in functional_scenarios
        ]
        self.warmups = warmups
        self.max_eval_time = average_time_per_scene * len(self.scenarios)
        self.random_seed = random_seed
        set_seed(random_seed)

    def run(self, core_id: int):
        p = psutil.Process(os.getpid())  # Ensure dedicated cpu
        p.cpu_affinity([core_id])

        for i, (logical_scenario, functional_scenario) in enumerate(islice(cycle(self.scenarios), self.warmups)):
            self.evaluator.evaluate(logical_scenario, functional_scenario, False, 0, self.max_eval_time)
            self.print_warmup_status(self.random_seed, i + 1, self.warmups, self.evaluator.name)

        coverage = {logical_scenario: False for logical_scenario, _ in self.scenarios}
        eval_time = 0
        for logical_scenario, functional_scenario in cycle(self.scenarios):
            covered = list(coverage.values()).count(True)
            if covered == len(self.scenarios) or eval_time >= self.max_eval_time:
                break

            if coverage[logical_scenario]:
                continue

            eval_data = self.evaluator.evaluate(
                logical_scenario,
                functional_scenario,
                True,
                eval_time,
                self.max_eval_time,
            )
            eval_time += eval_data.evaluation_time
            if eval_data.is_valid:
                coverage[logical_scenario] = True
                self.print_status(
                    self.random_seed,
                    covered + 1,
                    len(self.scenarios),
                    self.evaluator.name,
                    eval_time,
                    self.max_eval_time,
                )
                continue


class OneStepScheduler(CSPScheduler):
    def __init__(
        self,
        evaluator: CSPEvaluator,
        logical_scenario: LogicalScenario,
        random_seed: int,
        warmups: int,
        average_time_per_scene: int,
    ) -> None:
        self.evaluator = evaluator
        self.logical_scenario = logical_scenario
        self.actor_number = (
            self.logical_scenario.vessel_number,
            self.logical_scenario.obstacle_number,
        )
        self.total_fecs = ModelParser.TOTAL_REL_FECS[self.actor_number]
        self.max_eval_time = average_time_per_scene * self.total_fecs
        self.warmups = warmups
        self.random_seed = random_seed
        set_seed(random_seed)

    def run(self, core_id: int):
        p = psutil.Process(os.getpid())  # Ensure dedicated cpu
        p.cpu_affinity([core_id])

        for i in range(self.warmups):
            self.evaluator.evaluate(
                self.logical_scenario,
                None,
                False,
                self.max_eval_time - FOUR_MINUTES_IN_SEC,  # Limit warmup time to avoid long waits
                self.max_eval_time,
            )
            self.print_warmup_status(self.random_seed, i + 1, self.warmups, self.evaluator.name)

        covered_hashes: Set[int] = set()

        eval_time = 0
        while eval_time < self.max_eval_time and len(covered_hashes) < self.total_fecs:
            eval_data = self.evaluator.evaluate(self.logical_scenario, None, True, eval_time, self.max_eval_time)
            eval_time += eval_data.evaluation_time
            if eval_data.is_valid:
                scenario = ConcreteSceneAbstractor.get_abstractions_from_eval(eval_data)
                fec_hash = scenario.functional_scenario.fec_shape_hash()
                if scenario.functional_scenario.is_relevant_by_fec and fec_hash not in covered_hashes:
                    covered_hashes.add(fec_hash)
                    self.print_status(
                        self.random_seed,
                        len(covered_hashes),
                        self.total_fecs,
                        self.evaluator.name,
                        eval_time,
                        self.max_eval_time,
                    )


class CSPSchedulerFactory:
    @staticmethod
    def factory(
        evaluator: CSPEvaluator,
        scenarios: List[Scenario],
        random_seed: int,
        warmups: int,
        average_time_per_scene: int,
        init_method: str,
    ) -> CSPScheduler:
        if len(scenarios) == 0:
            raise ValueError("No scenarios provided for CSPScheduler.")

        if len(scenarios) == 1 and isinstance(scenarios[0], LogicalScenario):
            return OneStepScheduler(evaluator, scenarios[0], random_seed, warmups, average_time_per_scene)
        elif isinstance(scenarios[0], FunctionalScenario):
            return MSRScheduler(
                evaluator,
                scenarios,
                random_seed,
                warmups,
                average_time_per_scene,
                init_method,
            )
        else:
            raise ValueError(f"Unsupported scenario type: {type(scenarios[0])}. Expected LogicalScenario or FunctionalScenario.")
