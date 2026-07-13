from typing import List, Tuple

import matplotlib.pyplot as plt
import numpy as np

from concrete_level.models.concrete_scene import ConcreteScene
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from utils.evaluation_config import DC_RS, DC_SB_II, MSR_CDRS_PS, MSR_SB_III
from utils.global_constants import ONE_N_MILE_IN_M
from visualization.plotting_utils import EvalPlot


class RiskVectorPlot(EvalPlot):
    @staticmethod
    def metric_map_type(scene: ConcreteScene, metric_type: str):
        metric_mapping = {
            "dcpa": scene.dcpa,
            "tcpa": scene.tcpa,
            "ds": scene.danger_sector,
            "proximity": scene.proximity_index,
        }
        if metric_type not in metric_mapping:
            raise ValueError("Unrecognized type.")
        if metric_mapping[metric_type] is None:
            raise ValueError("None vector found among optimal solutions")
        return metric_mapping[metric_type]

    metric_map_title = {
        "dcpa": r"DCPA of OS to closest TS (s)",
        "tcpa": r"TCPA of OS to closest TS (s)",
        "ds": r"DS index of OS at $t_0$",
        "proximity": r"Max proximity index of OS at $t_0$",
    }

    metric_map_max = {
        "dcpa": 1 * ONE_N_MILE_IN_M,
        "tcpa": 1500,
        "ds": 1.0,
        "proximity": 1.0,
    }

    @property
    def config_groups(self) -> List[str]:
        return [DC_SB_II, MSR_SB_III, DC_RS, MSR_CDRS_PS]

    @property
    def actor_numbers_by_type(self) -> List[Tuple[int, int]]:
        return [(2, 0), (3, 0), (4, 0), (5, 0), (6, 0)]

    def __init__(self, eval_datas: List[EvaluationData], metric="dcpa"):
        self.metric = metric
        EvalPlot.__init__(self, eval_datas, is_all=False)

    def create_fig(self) -> plt.Figure:
        fig, axes = plt.subplots(
            1,
            self.vessel_num_count,
            figsize=(self.vessel_num_count, 4),
            gridspec_kw={"width_ratios": [1] * self.vessel_num_count},
            constrained_layout=True,
        )
        axes = np.atleast_1d(axes)

        for i, actor_number_by_type in enumerate(self.actor_numbers_by_type):
            axi: plt.Axes = axes[i]
            axi.set_title(self.vessel_num_labels[i])
            self.init_axi(i, axi, self.metric_map_title[self.metric])

            data = []
            new_group_labels = []
            for measurement, label in zip(self.measurements[actor_number_by_type].values(), self.group_labels):
                values = [self.metric_map_type(eval_data.best_scene, self.metric) for eval_data in measurement]
                if len(values) != 0:
                    data.append(values)
                    new_group_labels.append(label)

            if len(data) == 0:
                continue

            violin_plot = axi.violinplot(data, widths=0.7, showmeans=True, showmedians=True)

            # axi.set_yticks(range(max([max(d) for d in data])))
            axi.set_xticks(range(1, len(new_group_labels) + 1), new_group_labels)
            axi.set_xticklabels(new_group_labels, rotation=0, ha="right", fontweight="bold")
            self.set_yticks(axi, range(int(np.ceil(self.metric_map_max[self.metric]) + 1)))

            for patch, color in zip(violin_plot["bodies"], self.colors):
                patch.set_facecolor(color)  # Set fill color
                patch.set_linewidth(1.5)

            violin_plot["cmeans"].set_color("black")
            violin_plot["cmeans"].set_linewidth(2)
            violin_plot["cmedians"].set_color("grey")
            violin_plot["cmedians"].set_linewidth(2)
            violin_plot["cmedians"].set_linestyle(":")

            axi.set_ylim(0, self.metric_map_max[self.metric] * 1.15)

            # Annotate each box with the number of samples
            for j, group in enumerate(data, 1):  # '1' because boxplot groups start at 1
                sample_size = len(group)
                axi.text(
                    j,
                    self.metric_map_max[self.metric] * 1.05,
                    f"{sample_size}",
                    ha="left",
                    va="center",
                    fontsize=10,
                    horizontalalignment="left",
                )

        return fig
