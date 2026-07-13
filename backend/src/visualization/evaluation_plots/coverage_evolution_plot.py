from typing import List, Set, Tuple

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import gridspec
from pyparsing import ABC, abstractmethod

from functional_level.models.model_parser import ModelParser
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from utils.evaluation_config import DC_RS, DC_SB_II, DC_SB_III, MSR_CDRS_PS, MSR_SB_III
from utils.global_constants import FOUR_MINUTES_IN_SEC
from visualization.plotting_utils import EvalPlot

class CoverageEvolutionPlot(EvalPlot, ABC):
    def __init__(self, eval_datas : List[EvaluationData]):
        super().__init__(eval_datas, is_all=True)

    @property
    def config_groups(self) -> List[str]:
        return [DC_SB_II, DC_SB_III, MSR_SB_III, DC_RS, MSR_CDRS_PS]
        # return [DC_SB_II, DC_SB_III, DC_RS, MSR_SB_III, MSR_CDRS, MSR_CDRS_PS, DC_RS_PS]
        # return [DC_RS, DC_RS_PS, MSR_CDRS, MSR_CDRS_PS]

    @property
    def actor_numbers_by_type(self) -> List[Tuple[int, int]]:
        # return [(2, 0), (2, 1), (3, 0), (3, 1), (4, 0), (5, 0), (6, 0)]
        return [(2, 0), (3, 0), (4, 0), (5, 0), (6, 0)]

    @property
    @abstractmethod
    def total_fecs(self) -> int:
        pass

    @abstractmethod
    def pred(self, data : EvaluationData) -> bool:
        pass

    @property
    @abstractmethod
    def row_label(self) -> str:
        pass

    def calculate_coverages_by_timestamps(
        self,
        actor_numbers_by_type: Tuple[int, int],
        comparison_group: str,
        seed: int,
        timestamps: np.ndarray,
    ) -> List[float]:
        data = self.measurements[actor_numbers_by_type][comparison_group][seed]
        coverage = [(0, 0.0)]
        covered_classes: Set[int] = set()
        coverages_by_timestamp = []

        for d in data:
            next_timestamp = coverage[-1][1] + d.evaluation_time
            if next_timestamp > (self.total_fecs[actor_numbers_by_type] + 1) * FOUR_MINUTES_IN_SEC:
                break
            if d.is_valid and self.pred(d):
                covered_classes.add(d.best_scene.second_level_hash)
            coverage.append((len(covered_classes), next_timestamp))

        # find the last timestamp in the coverage that is less than or equal to each timestamp in timestamps
        for timestamp in timestamps:
            last_coverage = next((c for c in reversed(coverage) if c[1] <= timestamp), None)
            if last_coverage is not None:
                if self.total_fecs[actor_numbers_by_type] == 0:
                    coverages_by_timestamp.append(0.0)
                else:
                    coverages_by_timestamp.append(last_coverage[0] / self.total_fecs[actor_numbers_by_type] * 100)
            else:
                coverages_by_timestamp.append(coverages_by_timestamp[-1] if coverages_by_timestamp else 0)
        return coverages_by_timestamp

    def aggregate_data(self, actor_numbers_by_type : Tuple[int, int], comparison_group : str,
                            timestamps : np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
        seeds = self.measurements[actor_numbers_by_type][comparison_group].keys()
        if len(seeds) == 0:
            return np.array([0]*timestamps), np.array([0]*timestamps), np.array([0]*timestamps), np.array([0]*timestamps), np.array([0]*timestamps), np.array([0]*timestamps), 0.0
        # Create a 2D array: rows = seeds, columns = timestamps
        coverages_by_seed : List[List[float]] = []
        for seed in seeds:
            coverages = self.calculate_coverages_by_timestamps(actor_numbers_by_type, comparison_group, seed, timestamps)
            coverages_by_seed.append(coverages)
        # Now coverages_by_seed is a list of lists: [ [cov_t1, cov_t2, ...], ... for each seed ]
        coverages_by_seed = np.array(coverages_by_seed)  # shape: (num_seeds, num_timestamps)

        # Calculate median timestamp of 100% coverage
        timestamps_at_100_by_seed = []
        for i, coverages in enumerate(coverages_by_seed):
            # Find first index where coverage is 100
            first_index_at_100 = next((i for i, coverage in enumerate(coverages) if coverage == 100.0), None)
            if first_index_at_100 is None:
                timestamps_at_100_by_seed.append(np.inf)
            else:
                timestamps_at_100_by_seed.append(float(timestamps[first_index_at_100]))
        median_timestamps_at_100 = float(np.median(timestamps_at_100_by_seed))

        # Calculate median, q1, q3 across seeds for each timestamp
        median = np.median(coverages_by_seed, axis=0)
        mean = np.mean(coverages_by_seed, axis=0)
        min = np.min(coverages_by_seed, axis=0)
        max = np.max(coverages_by_seed, axis=0)
        q1 = np.percentile(coverages_by_seed, 0, axis=0)
        q3 = np.percentile(coverages_by_seed, 100, axis=0)
        print(median[-1])
        return median, mean, min, max, q1, q3, median_timestamps_at_100

    @staticmethod
    def calculate_runtime(data: List[EvaluationData]) -> float:
        """Calculate the total runtime for a list of EvaluationData."""
        return sum(d.evaluation_time for d in data)

    def create_timestamps(self, actor_numbers_by_type) -> np.ndarray:
        max_runtime = 0.0
        for comparison_group in self.comparison_groups:
            for seed in self.measurements[actor_numbers_by_type][comparison_group].keys():
                runtime = self.calculate_runtime(self.measurements[actor_numbers_by_type][comparison_group][seed])
                if runtime > max_runtime:
                    max_runtime = runtime
        return np.linspace(0, max_runtime, 400)


    def crop_data(self, timestamps : np.ndarray, data : List[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]]) -> Tuple[np.ndarray, List[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]]]:
        # Find the last index where any y-series changes
        last_change_indices = []

        for median, mean, min, max, q1, q3, median_timestamps_at_100 in data:
            change_indices = np.where((np.diff(median) != 0) | (np.diff(q1) != 0) | (np.diff(q3) != 0))[0]
            if len(change_indices) > 0:
                last_change = change_indices[-1] + 1  # +1 to include the last change point
                last_change_indices.append(last_change)

        for index in last_change_indices:
            print(f"Last change index for series: {index}, timestamp: {timestamps[index] if index < len(timestamps) else 'N/A'}")
        # Determine the global last change index
        if last_change_indices:
            global_last_change_index = np.max(last_change_indices)
        else:
            global_last_change_index = len(timestamps) - 1  # No change in any series

        timestamps_trimmed = timestamps[:global_last_change_index + 1]
        data_trimmed = [(median[:global_last_change_index + 1], mean[:global_last_change_index + 1], min[:global_last_change_index + 1], max[:global_last_change_index + 1], q1[:global_last_change_index + 1], q3[:global_last_change_index + 1], median_timestamps_at_100) for median, mean, min, max, q1, q3, median_timestamps_at_100 in data]
        return timestamps_trimmed, data_trimmed


    def create_fig(self) -> plt.Figure:
        fig = plt.figure(figsize=(1.7 * self.vessel_num_count, 3), constrained_layout=True)
        gs = gridspec.GridSpec(2, self.vessel_num_count, height_ratios=[7, 1], hspace=0.7)
        # Top axes spans all 6 columns
        ax_top = [fig.add_subplot(gs[0, i]) for i in range(self.vessel_num_count)]
        # Create an invisible axes spanning the bottom row for the legend
        ax_bottom = fig.add_subplot(gs[1, :])
        ax_bottom.axis("off")
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

            timestamps = self.create_timestamps(actor_number_by_type)
            data = []
            for j, cg in enumerate(self.comparison_groups):
                median, mean, min, max, q1, q3, median_timestamps_at_100 = self.aggregate_data(actor_number_by_type, cg, timestamps)
                data.append((median, mean, min, max, q1, q3, median_timestamps_at_100))

            for j, cg in enumerate(self.comparison_groups):
                first_timestamp = -1
                median, mean, min, max, q1, q3, median_timestamps_at_100 = data[j]
                for idx, t in enumerate(timestamps):
                    if min[idx] == 100:
                        first_timestamp = t
                        break
                # print(f"First timestamp for for {self.config_group_map[cg]} ({actor_number_by_type[0]} vessels): {first_timestamp}")
                # print(f"Median timestamp at 100% coverage for {self.config_group_map[cg]} ({actor_number_by_type[0]} vessels): {median_timestamps_at_100}")

            timestamps, data = self.crop_data(timestamps, data)

            for j, cg in enumerate(self.comparison_groups):
                median, mean, min, max, q1, q3, median_timestamps_at_100 = data[j]
                axi.plot(timestamps, median, color=self.colors[cg], linestyle='-', linewidth=2, label=r"$\bf{" + self.config_group_map[cg] + r"}$")

                axi.fill_between(timestamps, q1, q3, color=self.colors[cg], alpha=0.25)

                self.set_xticks(axi, timestamps, unit='s', tick_number=3)

        # Get handles and labels from the last axis (or any axis — all are the same here)
        handles, labels = axes[0][0].get_legend_handles_labels()
        # Add one legend to the figure (outside bottom)
        ax_bottom.legend(handles, labels, ncol=len(self.comparison_groups), fontsize=10, loc='lower center')
        return fig


class RelevantCoverageEvolutionPlot(CoverageEvolutionPlot):
    def __init__(self, eval_datas : List[EvaluationData]):
        super().__init__(eval_datas)

    @property
    def total_fecs(self) -> int:
        return ModelParser.TOTAL_REL_FECS

    def pred(self, data : EvaluationData) -> bool:
        return data.best_scene.is_relevant_by_fec

    @property
    def row_label(self) -> str:
        return "Relevant FEC coverage"


class AmbiguousCoverageEvolutionPlot(CoverageEvolutionPlot):
    def __init__(self, eval_datas : List[EvaluationData]):
        super().__init__(eval_datas)

    @property
    def total_fecs(self) -> int:
        return ModelParser.TOTAL_AMB_FECS

    def pred(self, data : EvaluationData) -> bool:
        return data.best_scene.is_ambiguous_by_fec

    @property
    def row_label(self) -> str:
        return "Ambiguous FEC coverage"
