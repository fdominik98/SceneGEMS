from abc import abstractmethod
from itertools import combinations
from typing import Dict, List, Tuple
from matplotlib import gridspec
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import gridspec
from pyparsing import ABC
from evaluation.mann_whitney_u_cliff_delta import MannWhitneyUCliffDelta
from functional_level.models.model_parser import ModelParser
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from utils.evaluation_config import DC_RS, DC_SB_III, MSR_CDRS, DC_SB_II, MSR_SB_II, MSR_SB_III, MSR_CDRS_PS, DC_RS_PS
from utils.global_constants import FOUR_MINUTES_IN_SEC
from visualization.plotting_utils import EvalPlot




class CoveragePlot(EvalPlot, ABC):
    def __init__(self, eval_datas : List[EvaluationData], is_all, is_algo):
        EvalPlot.__init__(self, eval_datas, is_algo=is_algo, is_all=is_all)

    @property
    def algos(self) -> List[Tuple[str, str]]:
        return [('nsga2', 'all'), ('nsga2', 'vessel'), ('nsga2', 'category'), ('nsga3', 'all'), ('nsga3', 'vessel'), ('nsga3', 'category'), ('ga', 'all'), ('de', 'all'), ('pso', 'all_swarm'), ('scenic', 'all')]

    @property
    def config_groups(self) -> List[str]:
        # return [DC_SB_II, DC_SB_III, DC_RS, MSR_SB_III, MSR_CDRS, MSR_CDRS_PS, DC_RS_PS]
        return [DC_SB_II, DC_SB_III, MSR_SB_III, DC_RS, MSR_CDRS_PS]

    @property
    def actor_numbers_by_type(self) -> List[Tuple[int, int]]:
        return [(2, 0), (3, 0), (4, 0), (5, 0), (6, 0)]

    @property
    @abstractmethod
    def row_label(self) -> str:
        """
        Override this method in subclasses to define the row label for the plot.
        """
        pass

    @property
    @abstractmethod
    def total_fecs(self) -> int:
        pass

    @abstractmethod
    def pred(self, data : EvaluationData) -> bool:
        pass

    def calculate_coverage(self, actor_numbers_by_type : Tuple[int, int], comparison_group : str, seed : int) -> float:
        data = self.measurements[actor_numbers_by_type][comparison_group][seed]
        coverage = [(0, 0.0)]
        covered_classes : Dict[int, EvaluationData] = {}

        for d in data:
            next_timestamp = coverage[-1][1] + d.evaluation_time
            if next_timestamp > (self.total_fecs[actor_numbers_by_type] + 1) * FOUR_MINUTES_IN_SEC:
                break
            if d.is_valid and self.pred(d):
                # if d.best_scene.second_level_hash is None or d.best_scene.second_level_hash in covered_classes.keys():
                #     print(f"Duplicate second_level_hash: {d.best_scene.second_level_hash}, {comparison_group}")
                    
                covered_classes[d.best_scene.second_level_hash] = d
            coverage.append((len(covered_classes.keys()), next_timestamp))

        last_coverage = coverage[-1][0]
        return last_coverage / self.total_fecs[actor_numbers_by_type] * 100

    def aggregate_data(self, actor_numbers_by_type : Tuple[int, int], comparison_group : str) -> np.ndarray:
        seeds = self.measurements[actor_numbers_by_type][comparison_group].keys()
        coverages = []
        for seed in seeds:
            coverage = self.calculate_coverage(actor_numbers_by_type, comparison_group, seed)
            coverages.append(coverage)
        return np.array(coverages)

    def create_fig(self) -> plt.Figure:
        fig = plt.figure(figsize=(1.7 * self.vessel_num_count, 2), constrained_layout=True)
        gs = gridspec.GridSpec(1, self.vessel_num_count, height_ratios=[1])
        # Top axes spans all 6 columns
        ax_top = [fig.add_subplot(gs[0, i]) for i in range(self.vessel_num_count)]
        # Bottom row: 6 equal-width axes
        # ax_bottom = [fig.add_subplot(gs[1, i]) for i in range(self.vessel_num_count)]
        # axes = [ax_top, ax_bottom]
        axes = [ax_top]


        for i, actor_number_by_type in enumerate(self.actor_numbers_by_type):
            axi : plt.Axes = axes[0][i]
            axi.set_title(self.vessel_num_labels[i], fontweight='bold')
            self.init_axi(i, axi, self.row_label)
            if i == 0:
                self.set_yticks(axi, range(101), unit="%", tick_number=6)
            axi.set_ylim(0, 105)

            datas = []
            new_comparison_groups = []
            new_comparison_group_labels = []
            for i, cg in enumerate(self.comparison_groups):
                data = self.aggregate_data(actor_number_by_type, cg)
                if len(data) > 0:
                    datas.append(data)
                    new_comparison_groups.append(cg)
                    new_comparison_group_labels.append(self.group_labels[i])
            if len(datas) == 0:
                continue

            violin_plot = axi.violinplot(datas, widths=0.7, showmeans=True, showmedians=True)

            axi.set_xticks(range(1, len(new_comparison_groups) + 1), new_comparison_group_labels)
            axi.set_xticklabels(new_comparison_group_labels, rotation=45, ha='right', fontweight='bold')

            for patch, cg in zip(violin_plot['bodies'], new_comparison_groups):
                patch.set_facecolor(self.colors[cg])           # Set fill color
                patch.set_alpha(0.8)                           # Set transparency (alpha)
                patch.set_linewidth(1.0)

            violin_plot['cmeans'].set_color('black')
            violin_plot['cmeans'].set_linewidth(1)
            violin_plot['cmedians'].set_color('grey')
            violin_plot['cmedians'].set_linewidth(1)
            violin_plot['cmedians'].set_linestyle(':')

            for label, data in zip(new_comparison_group_labels, datas):
                median = np.median(data)
                mean = np.mean(data)
                min = np.min(data)
                max = np.max(data)
                print(f"Median for {label} ({actor_number_by_type[0]} vessels): {median:.3f}%")
                print(f"Mean for {label} ({actor_number_by_type[0]} vessels): {mean:.3f}%")
                print(f"Min for {label} ({actor_number_by_type[0]} vessels): {min:.3f}%")
                print(f"Max for {label} ({actor_number_by_type[0]} vessels): {max:.3f}%")


        # # Create custom legend handles
        # mean_handle = Line2D([0], [0], color='black', linewidth=2, label='Mean')
        # median_handle = Line2D([0], [0], color='grey', linewidth=2, linestyle=':', label='Median')

        # # Add the legend to the plot
        # axes[0][0].legend(handles=[mean_handle, median_handle], loc='lower right')

        self.create_stat_test()
        return fig

    def create_stat_test(self):
        groups_to_compare = list(combinations(self.comparison_groups, 2))
        for i, actor_number_by_type in enumerate(self.actor_numbers_by_type):
            for j, (group1, group2) in enumerate(groups_to_compare):
                values1 = self.aggregate_data(actor_number_by_type, group1)
                values2 = self.aggregate_data(actor_number_by_type, group2)
                if len(values1) == 0 or len(values2) == 0:
                    continue

                statistical_test = MannWhitneyUCliffDelta(values1, values2)
                #print(f'{actor_number_by_type[0]} vessels, {actor_number_by_type[1]} obstacles, {group1} - {group2}: p-value:{statistical_test.p_value_mann_w}, effect-size:{statistical_test.effect_size_cohens_d}')
                print(f'{actor_number_by_type[0]} vessels, {self.config_group_map[group1]} - {self.config_group_map[group2]}: p-value:{statistical_test.p_value_mann_w}, effect-size:{statistical_test.effect_size_A12}')



class RelevantCoveragePlot(CoveragePlot):
    def __init__(self, eval_datas: List[EvaluationData], is_all=True, is_algo=False):
        super().__init__(eval_datas, is_all=is_all, is_algo=is_algo)

    @property
    def row_label(self) -> str:
        return "Relevant FEC coverage"

    def pred(self, data : EvaluationData) -> bool:
        return data.best_scene.is_relevant_by_fec

    @property
    def total_fecs(self) -> int:
        return ModelParser.TOTAL_REL_FECS
