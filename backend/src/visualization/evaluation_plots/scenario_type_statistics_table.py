from collections import defaultdict
from itertools import combinations
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt

from concrete_level.concrete_scene_abstractor import ConcreteSceneAbstractor
from evaluation.chi_square_kl_div import ChiSquareKLDiv
from evaluation.vessel_type_sampler import VesselTypeSampler
from functional_level.models.functional_model_manager import FunctionalModelManager
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from utils.evaluation_config import DC_RS, DC_SB_II, MSR_CDRS_PS, MSR_SB_III
from visualization.plotting_utils import DummyEvalPlot


class ScenarioTypeStatisticsTable(DummyEvalPlot):
    def __init__(self, eval_datas: List[EvaluationData]):
        super().__init__(eval_datas)

    @property
    def config_groups(self) -> List[str]:
        return [
            DC_SB_II,
            MSR_SB_III,
            DC_RS,
            MSR_CDRS_PS,
        ]

    @property
    def actor_numbers_by_type(self) -> List[Tuple[int, int]]:
        return [(2, 0)]

    def create_fig(self) -> plt.Figure:
        samples: Dict[Tuple[int, int], Dict[str, List[int]]] = defaultdict(lambda: defaultdict())
        for i, actor_number_by_type in enumerate(self.actor_numbers_by_type):
            for j, comparison_group in enumerate(self.comparison_groups):
                scenarios = [ConcreteSceneAbstractor.get_abstractions_from_eval(eval_data).functional_scenario for eval_data in self.measurements[actor_number_by_type][comparison_group]]
                values = [round(value) for value in VesselTypeSampler.sample(scenarios, 0, {})]
                samples[actor_number_by_type][comparison_group] = values

            values = [round(value) for value in [56952 * 0.131, 56952 * 0.002, 56952 * 0.867]]
            samples[actor_number_by_type]["zhu_et_al"] = values
            values = [
                round(value)
                for value in VesselTypeSampler.sample(
                    FunctionalModelManager.get_x_vessel_y_obstacle_scenarios(actor_number_by_type[0], actor_number_by_type[1]),
                    0,
                    {},
                )
            ]

            samples[actor_number_by_type]["base_reference"] = values

        groups_to_compare = list(combinations(self.comparison_groups, 2))
        for i, actor_number_by_type in enumerate(self.actor_numbers_by_type):
            for j, (group1, group2) in enumerate(groups_to_compare):
                samples1 = samples[actor_number_by_type][group1]
                samples2 = samples[actor_number_by_type][group2]
                test = ChiSquareKLDiv(samples1, samples2)
                print(f"{actor_number_by_type[0]} vessels, {actor_number_by_type[1]} obstacles, {group1} - {group2}: {group1} p-value:{test.p_value}, KL Divergence::{test.kl_div}")

                # evenness_test = PermutationEvennessTest(samples1, samples2)
                # print(f'{vessel_number} vessels, {group1} - {group2}: {group1} evenness={evenness_test.evenness_1}, {group2} evenness={evenness_test.evenness_2}, p-value:{evenness_test.p_value}, effect-size:{evenness_test.observed_diff}')

        return DummyEvalPlot.create_fig(self)
