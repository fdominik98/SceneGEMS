from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from functional_level.metamodels.functional_scenario import FunctionalScenario
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from logical_level.models.logical_scenario import LogicalScenario


class CSPSolver(ABC):
    @abstractmethod
    def init_problem(
        self,
        logical_scenario: LogicalScenario,
        functional_scenario: Optional[FunctionalScenario],
        initial_population: List[List[float]],
        eval_data: EvaluationData,
    ):
        pass

    @abstractmethod
    def evaluate(self, some_input, eval_data: EvaluationData):
        pass

    @abstractmethod
    def convert_results(self, some_results, eval_data: EvaluationData) -> Tuple[List[float], int, float]:
        pass

    @classmethod
    @abstractmethod
    def algorithm_desc(cls) -> str:
        pass
