from itertools import combinations
from typing import List, Tuple

import matplotlib.pyplot as plt

from concrete_level.concrete_scene_abstractor import ConcreteSceneAbstractor
from evaluation.chi_square_kl_div import ChiSquareKLDiv
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from utils.evaluation_config import DC_RS, DC_SB_II, MSR_CDRS_PS, MSR_SB_III
from visualization.plotting_utils import DummyEvalPlot


class DiversityStatisticsTable(DummyEvalPlot):
    def __init__(
        self,
        eval_datas: List[EvaluationData],
        is_second_level_abstraction=False,
        get_equivalence_class_distribution=ConcreteSceneAbstractor.get_equivalence_class_distribution,
    ):
        self.get_equivalence_class_distribution = get_equivalence_class_distribution
        self.is_second_level_abstraction = is_second_level_abstraction
        super().__init__(eval_datas)

    @property
    def config_groups(self) -> List[str]:
        return [DC_SB_II, MSR_SB_III, DC_RS, MSR_CDRS_PS]

    @property
    def actor_numbers_by_type(self) -> List[Tuple[int, int]]:
        return [(2, 0), (3, 0), (4, 0), (5, 0), (6, 0)]

    def create_fig(self) -> plt.Figure:
        groups_to_compare = list(combinations(self.comparison_groups, 2))
        for i, actor_number_by_type in enumerate(self.actor_numbers_by_type):
            for j, (group1, group2) in enumerate(groups_to_compare):
                equivalence_classes1 = self.get_equivalence_class_distribution(
                    [eval_data.best_scene for eval_data in self.measurements[actor_number_by_type][group1]],
                    self.is_second_level_abstraction,
                )
                equivalence_classes2 = self.get_equivalence_class_distribution(
                    [eval_data.best_scene for eval_data in self.measurements[actor_number_by_type][group2]],
                    self.is_second_level_abstraction,
                )

                all_keys = set(equivalence_classes1.keys()) | set(equivalence_classes2.keys())

                # Step 2: Add missing keys with default value (None, 0)
                for key in all_keys:
                    equivalence_classes1.setdefault(key, (None, 0))
                    equivalence_classes2.setdefault(key, (None, 0))

                # Step 3: Sort dictionaries by key
                equivalence_classes1 = dict(sorted(equivalence_classes1.items()))
                equivalence_classes2 = dict(sorted(equivalence_classes2.items()))

                if len(equivalence_classes1) == 0 or len(equivalence_classes2) == 0:
                    continue
                values1 = [int(count) for _, count in equivalence_classes1.values()]
                values2 = [int(count) for _, count in equivalence_classes2.values()]
                if sum(values1) == 0 or sum(values2) == 0:
                    continue

                # evenness_test = PermutationEvennessTest(values1, values2)
                # print(f'{vessel_number} vessels, {group1} - {group2}: {group1} evenness={evenness_test.evenness_1}, {group2} evenness={evenness_test.evenness_2}, p-value:{evenness_test.p_value}, effect-size:{evenness_test.observed_diff}')

                test = ChiSquareKLDiv(values1, values2)
                print(f"{actor_number_by_type[0]} vessels, {actor_number_by_type[1]} obstacles, {group1} - {group2}: {group1} p-value:{test.p_value}, KL Divergence::{test.kl_div}")

        return DummyEvalPlot.create_fig(self)


class AmbiguousDiversityStatisticsTable(DiversityStatisticsTable):
    def __init__(self, eval_datas):
        super().__init__(
            eval_datas,
            ConcreteSceneAbstractor.get_ambiguous_equivalence_class_distribution,
        )


class UnspecifiedDiversityStatisticsTable(DiversityStatisticsTable):
    def __init__(self, eval_datas):
        super().__init__(
            eval_datas,
            ConcreteSceneAbstractor.get_unspecified_equivalence_class_distribution,
        )
