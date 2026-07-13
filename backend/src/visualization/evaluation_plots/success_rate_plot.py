from typing import List, Tuple

import matplotlib.pyplot as plt
import numpy as np

from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from utils.evaluation_config import DC_RS, DC_SB_II, MSR_CDRS_PS, MSR_SB_III
from visualization.plotting_utils import EvalPlot


class SuccessRatePlot(EvalPlot):
    def __init__(self, eval_datas: List[EvaluationData], is_algo=False):
        EvalPlot.__init__(self, eval_datas, is_algo=is_algo, is_all=True)

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

    def create_fig(self) -> plt.Figure:
        fig, axes = plt.subplots(
            1,
            self.vessel_num_count,
            figsize=(self.comparison_group_count, 4),
            gridspec_kw={"width_ratios": [1] * self.vessel_num_count},
            constrained_layout=True,
        )
        axes = np.atleast_1d(axes)

        for i, vessel_number in enumerate(self.actor_numbers_by_type):
            axi: plt.Axes = axes[i]
            axi.set_title(self.vessel_num_labels[i])
            axi.set_aspect("auto", adjustable="box")
            self.init_axi(i, axi, "Success rate (%)")

            data = []
            percentages = []
            new_group_labels = []
            for measurement, label in zip(self.measurements[vessel_number].values(), self.group_labels):
                values = [0 if not eval_data.is_valid else 1 for eval_data in measurement]
                if len(values) != 0:
                    data.append(values)
                    percentages.append(np.mean(values) * 100)
                    print(f"{vessel_number} vessels, {label}: success rate: {percentages[-1]}")
                    new_group_labels.append(label)
            if len(data) == 0:
                continue

            bars: plt.BarContainer = axi.bar(
                new_group_labels,
                percentages,
                color=self.colors,
                edgecolor="black",
                linewidth=2,
            )
            axi.set_xticks(range(len(new_group_labels)), new_group_labels)
            axi.set_xticklabels(new_group_labels, rotation=0, ha="right", fontweight="bold")
            self.set_yticks(axi, range(101))
            axi.set_ylim(0, 110)

            for j, bar in enumerate(bars):
                axi.text(
                    bar.get_x() + bar.get_width() / 2,
                    102,
                    f"{len(data[j])}",
                    ha="center",
                    va="bottom",
                    fontsize=10,
                )

        return fig
