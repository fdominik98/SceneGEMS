from typing import List, Tuple

import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import numpy as np

from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from utils.evaluation_config import DC_RS, DC_SB_II, MSR_CDRS_PS, MSR_SB_III
from visualization.plotting_utils import EvalPlot


class AverageTimePerScenePlot(EvalPlot):
    def __init__(self, eval_datas: List[EvaluationData], is_all=True, is_algo=False):
        EvalPlot.__init__(self, eval_datas, is_algo=is_algo, is_all=is_all)

    @property
    def algos(self) -> List[Tuple[str, str]]:
        return [
            ("nsga2", "all"),
            ("nsga2", "vessel"),
            ("nsga2", "category"),
            ("nsga3", "all"),
            ("nsga3", "vessel"),
            ("nsga3", "category"),
            ("ga", "all"),
            ("de", "all"),
            ("pso", "all_swarm"),
            ("scenic", "all"),
        ]

    @property
    def config_groups(self) -> List[str]:
        return [DC_SB_II, DC_RS, MSR_SB_III, MSR_CDRS_PS]

    @property
    def actor_numbers_by_type(self) -> List[Tuple[int, int]]:
        return [(2, 0), (3, 0), (4, 0), (5, 0), (6, 0)]

    def create_fig(self):
        fig = plt.figure(figsize=(7, 3.8), constrained_layout=True)
        gs = gridspec.GridSpec(3, self.vessel_num_count, height_ratios=[4.4, 4, 4], hspace=0.25)  # 2 rows, 6 columns
        # Top axes spans all 6 columns
        ax_top = fig.add_subplot(gs[0, :])  # Row 0, all columns
        # Bottom row: 6 equal-width axes
        ax_mid = fig.add_subplot(gs[1, :])

        ax_bottom = [fig.add_subplot(gs[2, i]) for i in range(self.vessel_num_count)]  # Row 1, column i

        self.init_axi(0, ax_top, "Average\ntime/scene")
        # axi.set_title(self.vessel_num_labels[i])
        max_time_per_scene_value = 0
        for j, config_group in enumerate(self.comparison_groups):
            average_runtimes = []
            success_rates = []

            for actor_number_by_type in self.actor_numbers_by_type:
                average_runtimes.append(np.mean([eval_data.evaluation_time for eval_data in self.measurements[actor_number_by_type][config_group]]))
                success_rates.append(np.mean([1 if eval_data.is_valid else 0 for eval_data in self.measurements[actor_number_by_type][config_group]]))

            average_times_per_scene = np.array(average_runtimes) / np.array(success_rates)

            print(f"approach, number of vessels, success rate, average runtime, average time per scene")
            for (
                vessel_num,
                success_rate,
                average_runtime,
                average_time_per_scene,
            ) in zip(
                self.vessel_num_labels,
                success_rates,
                average_runtimes,
                average_times_per_scene,
            ):
                print(f"{self.group_labels[j]}, {vessel_num[0]}, {success_rate}, {average_runtime}, {average_time_per_scene}")

            ax_top.plot(
                self.vessel_num_labels,
                average_times_per_scene,
                color=self.colors[j],
                linestyle="-",
                markersize=10,
                marker=".",
                linewidth=3.5,
                label=r"$\bf{" + self.group_labels[j] + r"}$",
            )

            if max_time_per_scene_value < max(average_times_per_scene):
                max_time_per_scene_value = max(average_times_per_scene)

        # ax_top.set_xticks(self.vessel_num_labels, minor=False)
        higher_max = round(max_time_per_scene_value + max(max_time_per_scene_value * 0.1, 1))
        self.set_yticks(ax_top, range(higher_max + 1), "s")
        ax_top.set_ylim(0, higher_max)

        handles, labels = ax_top.get_legend_handles_labels()
        ax_top.legend(handles, labels, ncol=2, fontsize=10, title="Approaches")

        self.init_axi(0, ax_mid, "Average\nruntime")
        # axi.set_title(self.vessel_num_labels[i])
        max_runtime_value = 0
        for j, config_group in enumerate(self.comparison_groups):
            average_runtimes = []
            for actor_number_by_type in self.actor_numbers_by_type:
                average_runtimes.append(np.mean([eval_data.evaluation_time for eval_data in self.measurements[actor_number_by_type][config_group]]))

            ax_mid.plot(
                self.vessel_num_labels,
                average_runtimes,
                color=self.colors[j],
                linestyle="-",
                marker=".",
                markersize=10,
                linewidth=3.5,
                label=r"$\bf{" + self.group_labels[j] + r"}$",
            )

            if max_runtime_value < max(average_runtimes):
                max_runtime_value = max(average_runtimes)

        ax_mid.set_xticks(self.vessel_num_labels, minor=False)
        ax_mid.set_xticklabels(self.vessel_num_labels, minor=False, fontweight="bold")
        higher_max = round(max_runtime_value + max(max_runtime_value * 0.1, 1))
        self.set_yticks(ax_mid, range(higher_max + 1), "s")
        ax_mid.set_ylim(0, higher_max)

        # handles, labels = ax_mid.get_legend_handles_labels()
        # ax_mid.legend(handles, labels, ncol=1, fontsize=10, title="Approaches")

        for i, vessel_number in enumerate(self.actor_numbers_by_type):
            axi: plt.Axes = ax_bottom[i]
            axi.set_aspect("auto", adjustable="box")
            self.init_axi(i, axi, "Success rate")

            data = []
            percentages = []
            new_group_labels = []
            for measurement, label in zip(self.measurements[vessel_number].values(), self.group_labels):
                values = [0 if not eval_data.is_valid else 1 for eval_data in measurement]
                if len(values) != 0:
                    data.append(values)
                    percentages.append(np.mean(values) * 100)
                    new_group_labels.append(label)
            if len(data) == 0:
                continue

            axi.bar(
                new_group_labels,
                percentages,
                color=self.colors,
                edgecolor="black",
                linewidth=1.5,
            )
            if i == 0:
                self.set_yticks(axi, range(101), unit="%")
            axi.set_ylim(0, 110)

            # for j, bar in enumerate(bars):
            #     axi.text(bar.get_x() + bar.get_width() / 2, 102,
            #     f'{len(data[j])}', ha='center', va='bottom', fontsize=10)

        return fig
