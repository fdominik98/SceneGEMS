from collections import defaultdict
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np

from concrete_level.concrete_scene_abstractor import ConcreteSceneAbstractor
from concrete_level.models.concrete_scene import ConcreteScene
from functional_level.models.model_parser import ModelParser
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from utils.evaluation_config import DC_RS, DC_SB_II, MSR_CDRS_PS, MSR_SB_III
from visualization.plotting_utils import EvalPlot


class DiversityPlot(EvalPlot):
    def __init__(self, eval_datas: List[EvaluationData]):
        super().__init__(eval_datas)

    @property
    def config_groups(self) -> List[str]:
        return [DC_SB_II, DC_RS, MSR_SB_III, MSR_CDRS_PS]

    @property
    def actor_numbers_by_type(self) -> List[Tuple[int, int]]:
        # return [(2, 0), (2, 1), (3, 0), (3, 1), (4, 0), (5, 0), (6, 0)]
        return [(2, 0), (3, 0), (4, 0), (5, 0), (6, 0)]

    def calculate_distribution(self, actor_numbers_by_type: Tuple[int, int], comparison_group: str, seed: int) -> Dict[int, int]:
        data = self.measurements[actor_numbers_by_type][comparison_group][seed]
        equivalence_classes: Dict[int, Tuple[ConcreteScene, int]] = ConcreteSceneAbstractor.get_equivalence_class_distribution([eval_data.best_scene for eval_data in data], True)

        processed_classes = {key: count for key, (scene, count) in equivalence_classes.items() if scene.is_relevant_by_fec}
        return processed_classes

    def aggregate_data(self, actor_numbers_by_type: Tuple[int, int], comparison_group: str) -> Dict[int, List[int]]:
        seeds = self.measurements[actor_numbers_by_type][comparison_group].keys()
        covered_classes = defaultdict(list)
        for seed in seeds:
            coverage_per_class = self.calculate_distribution(actor_numbers_by_type, comparison_group, seed)
            for key, count in coverage_per_class.items():
                covered_classes[key].append(count)

        # fill up all the count lists with zeros so that all values have the length of the number of seeds
        for key in covered_classes:
            while len(covered_classes[key]) < len(seeds):
                covered_classes[key].append(0)
        for i in range(ModelParser.TOTAL_REL_FECS[actor_numbers_by_type] - len(covered_classes)):
            if i not in covered_classes:
                covered_classes[i] = [0] * max(1, len(seeds))

        # sort the covered classes based on the mean of the values
        covered_classes = dict(sorted(covered_classes.items(), key=lambda item: np.mean(item[1]), reverse=True))
        return covered_classes

    def create_fig(self) -> plt.Figure:
        fig, axes = plt.subplots(
            self.comparison_group_count,
            self.vessel_num_count,
            figsize=(2.5 * 4, 3.8),
            constrained_layout=True,
            gridspec_kw={"wspace": 0, "hspace": 0},
        )
        axes = np.atleast_2d(axes)

        for i, actor_number_by_type in enumerate(self.actor_numbers_by_type):
            all_axes: List[plt.Axes] = []
            for j, config_group in enumerate(self.comparison_groups):
                axi: plt.Axes = axes[j][i]
                all_axes.append(axi)
                if j == 0:
                    axi.set_title(self.vessel_num_labels[i], fontweight="bold")
                self.init_axi(i, axi, r"$\bf{" + self.group_labels[j] + r"}$")

                values = self.aggregate_data(actor_number_by_type, config_group)
                if len(values) == 0:
                    continue

                # all_shapes = len(equivalence_classes)
                # relevant_shapes = sum(1 for scene, count in equivalence_classes.values() if scene.is_relevant_by_fec)
                # ambiguous_shapes = sum(1 for scene, count in equivalence_classes.values() if scene.is_ambiguous_by_fec)

                # plot_text = f'all shapes: {all_shapes}\nrelevant shapes: {relevant_shapes}\nambiguous shapes: {ambiguous_shapes}'
                # plot_text = f'covered: {all_shapes}'

                # axi.text(0.98, 0.98, plot_text,
                # transform=axi.transAxes,  # Use axis coordinates
                # verticalalignment='top', # Align text vertically to the top
                # horizontalalignment='right',
                # fontsize=11)

                labels = range(1, len(values.keys()) + 1)
                # create box plots instead of bars
                boxes: plt.BoxPlot = axi.boxplot(
                    list(values.values()),
                    positions=labels,
                    widths=0.5,
                    patch_artist=True,
                    boxprops=dict(facecolor=self.colors[config_group], color="black"),
                    medianprops=dict(color="black"),
                )
                # bars : plt.BarContainer = axi.bar(labels, values.values(), color=self.colors[j], edgecolor='black', linewidth=0)

                xticks = list(np.linspace(labels[0], labels[-1], 2))
                xticks = [int(t) for t in xticks]
                axi.set_xticks([xticks[0], xticks[-1]] + list(xticks), minor=False)
                # axi.set_xticks([1], minor=False)
                # axi.set_xticklabels([f'all shapes: {all_shapes}'], minor=False)
                maxes = [max(value) for value in values.values()]
                max_value = max(maxes)
                higher_max = round(max_value * 1.05) + 1
                self.set_yticks(axi, range(higher_max), tick_number=2)
                axi.set_ylim(0, higher_max)
            # for ax in all_axes:
            #     self.set_yticks(ax, range(max_value + 1), tick_number=2)
            #     ax.set_ylim(0, max_value)

        return fig


class AmbiguousDiversityPlot(DiversityPlot):
    def __init__(self, eval_datas, is_higher_abstraction=False):
        super().__init__(eval_datas, is_higher_abstraction)
