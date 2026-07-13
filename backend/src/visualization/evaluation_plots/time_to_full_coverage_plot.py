from abc import abstractmethod
from itertools import combinations
from typing import Dict, List, Optional, Set, Tuple
from matplotlib import gridspec
import matplotlib.pyplot as plt
import numpy as np
from pyparsing import ABC
from evaluation.mann_whitney_u_cliff_delta import MannWhitneyUCliffDelta
from functional_level.models.model_parser import ModelParser
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from utils.evaluation_config import DC_RS, DC_SB_III, MSR_CDRS, DC_SB_II, MSR_SB_II, MSR_SB_III, MSR_CDRS_PS, DC_RS_PS
from visualization.plotting_utils import EvalPlot


class TimeToFullCoveragePlot(EvalPlot, ABC):
    def __init__(self, eval_datas: List[EvaluationData], is_all, is_algo):
        EvalPlot.__init__(self, eval_datas, is_algo=is_algo, is_all=is_all)

    @property
    def config_groups(self) -> List[str]:
        
        # return [DC_SB_II, DC_SB_III, DC_RS, MSR_SB_II, MSR_SB_III, MSR_CDRS, MSR_CDRS_PS, DC_RS_PS]
        return [DC_SB_II, DC_SB_III, MSR_SB_III, DC_RS, MSR_CDRS_PS]

    @property
    def actor_numbers_by_type(self) -> List[Tuple[int, int]]:
        # return [(2, 0), (3, 0), (4, 0), (5, 0), (6, 0)]
        return [(2, 0), (3, 0), (4, 0), (5, 0), (6, 0)]

    @property
    @abstractmethod
    def row_label(self) -> str:
        pass

    @property
    @abstractmethod
    def total_fecs(self) -> Dict[Tuple[int, int], int]:
        pass

    @abstractmethod
    def pred(self, data: EvaluationData) -> bool:
        pass

    def calculate_time_to_full_coverage(self, actor_numbers_by_type: Tuple[int, int], 
                                         comparison_group: str, seed: int) -> Optional[float]:
        """
        Calculate the time it takes to reach 100% coverage for a given seed.
        Returns None if 100% coverage is never reached.
        """
        data = self.measurements[actor_numbers_by_type][comparison_group][seed]
        total_fec_count = self.total_fecs[actor_numbers_by_type]
        
        if total_fec_count == 0:
            return 0.0
        
        covered_classes: Set[int] = set()
        cumulative_time = 0.0

        for d in data:
            if d.evaluation_time is not None:
                cumulative_time += d.evaluation_time
            if d.is_valid and self.pred(d):
                hash_val = d.best_scene.second_level_hash
                if hash_val is not None:
                    covered_classes.add(hash_val)
                if len(covered_classes) >= total_fec_count:
                    return cumulative_time

        return None

    def count_seeds_reaching_full_coverage(self, actor_numbers_by_type: Tuple[int, int],
                                           comparison_group: str) -> Tuple[int, int]:
        """
        Count how many seeds reach 100% coverage for the given configuration group.
        Returns (total_seeds, seeds_with_full_coverage).
        """
        seed_dict = self.measurements[actor_numbers_by_type].get(comparison_group, {})
        total_seeds = len(seed_dict.keys())
        full_coverage_seeds = 0

        for seed in seed_dict.keys():
            time_to_full = self.calculate_time_to_full_coverage(actor_numbers_by_type, comparison_group, seed)
            if time_to_full is not None:
                full_coverage_seeds += 1

        return total_seeds, full_coverage_seeds

    def aggregate_data(self, actor_numbers_by_type: Tuple[int, int], 
                       comparison_group: str) -> Optional[np.ndarray]:
        """
        Aggregate time-to-100%-coverage data across all seeds.
        Returns None if any seed does not reach 100% coverage.
        """
        seeds = self.measurements[actor_numbers_by_type][comparison_group].keys()
        times = []
        
        for seed in seeds:
            time_to_full = self.calculate_time_to_full_coverage(actor_numbers_by_type, comparison_group, seed)
            if time_to_full is None:
                return None
            times.append(time_to_full)
        
        if len(times) == 0:
            return None
            
        return np.array(times)

    def create_fig(self) -> plt.Figure:
        fig = plt.figure(figsize=(1.7 * self.vessel_num_count, 2.5), constrained_layout=True)
        gs = gridspec.GridSpec(1, self.vessel_num_count, height_ratios=[1])
        ax_top = [fig.add_subplot(gs[0, i]) for i in range(self.vessel_num_count)]
        axes = [ax_top]

        total_base_seeds = 0
        total_base_full_coverage_seeds = 0

        for i, actor_number_by_type in enumerate(self.actor_numbers_by_type):
            axi: plt.Axes = axes[0][i]
            axi.set_title(self.vessel_num_labels[i], fontweight='bold')
            self.init_axi(i, axi, self.row_label)

            datas = []
            new_comparison_groups = []
            new_comparison_group_labels = []
            
            for j, cg in enumerate(self.comparison_groups):
                data = self.aggregate_data(actor_number_by_type, cg)
                if data is not None and len(data) > 0:
                    datas.append(data)
                    new_comparison_groups.append(cg)
                    new_comparison_group_labels.append(self.group_labels[j])
            
            # Print how many seeds reach 100% coverage for the base approach (MSR_CDRS_PS)
            base_approach = MSR_CDRS_PS
            if base_approach in self.measurements[actor_number_by_type]:
                total_seeds, full_coverage_seeds = self.count_seeds_reaching_full_coverage(actor_number_by_type, base_approach)
                if total_seeds > 0:
                    total_base_seeds += total_seeds
                    total_base_full_coverage_seeds += full_coverage_seeds
                    base_label = self.config_group_map.get(base_approach, base_approach)
                    print(
                        f"Seeds reaching 100% coverage for base approach {base_label} "
                        f"({actor_number_by_type[0]} vessels): {full_coverage_seeds}/{total_seeds}"
                    )
            if len(datas) == 0:
                axi.text(0.5, 0.5, 'No group\nreached 100%', 
                        transform=axi.transAxes, ha='center', va='center',
                        fontsize=10, color='gray')
                continue

            all_times = np.concatenate(datas)
            max_time = np.max(all_times)
            
            axi.set_ylim(0, max_time * 1.1)
            self.set_yticks(axi, [0, max_time], unit='s', tick_number=6)
            if i == 0:
                axi.set_ylabel(self.row_label, fontsize=14)

            violin_plot = axi.violinplot(datas, widths=0.7, showmeans=True, showmedians=True)

            axi.set_xticks(range(1, len(new_comparison_groups) + 1), new_comparison_group_labels)
            axi.set_xticklabels(new_comparison_group_labels, rotation=45, ha='right', fontweight='bold')

            for patch, cg in zip(violin_plot['bodies'], new_comparison_groups):  # type: ignore
                patch.set_facecolor(self.colors[cg])
                patch.set_alpha(0.8)
                patch.set_linewidth(1.0)

            violin_plot['cmeans'].set_color('black')
            violin_plot['cmeans'].set_linewidth(1)
            violin_plot['cmedians'].set_color('grey')
            violin_plot['cmedians'].set_linewidth(1)
            violin_plot['cmedians'].set_linestyle(':')

            for label, data in zip(new_comparison_group_labels, datas):
                median = np.median(data)
                mean = np.mean(data)
                min_val = np.min(data)
                max_val = np.max(data)
                print(f"Time to 100% - Median for {label} ({actor_number_by_type[0]} vessels): {median:.2f}s")
                print(f"Time to 100% - Mean for {label} ({actor_number_by_type[0]} vessels): {mean:.2f}s")
                print(f"Time to 100% - Min for {label} ({actor_number_by_type[0]} vessels): {min_val:.2f}s")
                print(f"Time to 100% - Max for {label} ({actor_number_by_type[0]} vessels): {max_val:.2f}s")


        if total_base_seeds > 0:
            print(
                f"Overall seeds reaching 100% coverage for base approach "
                f"{self.config_group_map.get(MSR_CDRS_PS, MSR_CDRS_PS)}: "
                f"{total_base_full_coverage_seeds}/{total_base_seeds}"
            )

        self.create_stat_test()
        return fig

    def create_stat_test(self):
        groups_to_compare = list(combinations(self.comparison_groups, 2))
        for i, actor_number_by_type in enumerate(self.actor_numbers_by_type):
            for j, (group1, group2) in enumerate(groups_to_compare):
                values1 = self.aggregate_data(actor_number_by_type, group1)
                values2 = self.aggregate_data(actor_number_by_type, group2)
                if values1 is None or values2 is None:
                    continue
                if len(values1) == 0 or len(values2) == 0:
                    continue

                statistical_test = MannWhitneyUCliffDelta(values1, values2)
                print(f'Time to 100% - {actor_number_by_type[0]} vessels, {self.config_group_map[group1]} - {self.config_group_map[group2]}: p-value:{statistical_test.p_value_mann_w}, effect-size:{statistical_test.effect_size_A12}')


class RelevantTimeToFullCoveragePlot(TimeToFullCoveragePlot):
    def __init__(self, eval_datas: List[EvaluationData], is_all=True, is_algo=False):
        super().__init__(eval_datas, is_all=is_all, is_algo=is_algo)

    @property
    def row_label(self) -> str:
        return "Time to 100% coverage"

    def pred(self, data: EvaluationData) -> bool:
        return bool(data.best_scene.is_relevant_by_fec)

    @property
    def total_fecs(self) -> Dict[Tuple[int, int], int]:
        return ModelParser.TOTAL_REL_FECS
