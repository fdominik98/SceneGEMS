from typing import List, Tuple

import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np

from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from utils.evaluation_config import DC_RS, DC_SB_II, MSR_CDRS_PS, MSR_SB_III
from visualization.plotting_utils import EvalPlot


class RelevantRatioPlot(EvalPlot):
    def __init__(self, eval_datas: List[EvaluationData], is_algo=False):
        EvalPlot.__init__(self, eval_datas, is_algo=is_algo, is_all=False)

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
        fig = plt.figure(figsize=(9, 3), constrained_layout=True)
        gs = gridspec.GridSpec(4, self.vessel_num_count, height_ratios=[4, 4, 4, 4], wspace=0, hspace=0.25)  # 2 rows, 6 columns
        # Top axes spans all 6 columns
        ax_relevant_fec = [fig.add_subplot(gs[0, i]) for i in range(self.vessel_num_count)]  # Row 0, all columns
        ax_ambiguous_fec = [fig.add_subplot(gs[1, i]) for i in range(self.vessel_num_count)]
        ax_relevant_fsm = [fig.add_subplot(gs[2, i]) for i in range(self.vessel_num_count)]
        axt_ambiguous_fsm = [fig.add_subplot(gs[3, i]) for i in range(self.vessel_num_count)]  # Row 1, column i

        def get_data(measurements: list[List[EvaluationData]], pred):
            data = []
            percentages = []
            new_group_labels = []
            for measurement, label in zip(list(measurements), self.group_labels):
                values = [1 if pred(eval_data) else 0 for eval_data in measurement]
                if len(values) != 0:
                    data.append(values)
                    percentages.append(np.mean(values) * 100)
                    new_group_labels.append(label)
            print([f"{label} : {perc}%" for label, perc in zip(new_group_labels, percentages)])
            return data, percentages, new_group_labels

        for i, vessel_number in enumerate(self.actor_numbers_by_type):
            axi: plt.Axes = ax_relevant_fec[i]
            axi.set_aspect("auto", adjustable="box")
            self.init_axi(i, axi, r"$\bf{Relevant}$" + "\nconsistent\n" + r"$\bf{FEC}$" + " rate")
            axi.set_title(self.vessel_num_labels[i], fontweight="bold")

            data, percentages, new_group_labels = get_data(
                self.measurements[vessel_number].values(),
                lambda eval_data: eval_data.best_scene.is_relevant_by_fec,
            )
            if len(data) == 0:
                continue

            bars: plt.BarContainer = axi.bar(
                new_group_labels,
                percentages,
                color=self.colors,
                edgecolor="black",
                linewidth=1.5,
                label=[r"$\bf{" + group_label + r"}$" for group_label in self.group_labels],
            )
            if i == 0:
                self.set_yticks(axi, range(101), unit="%", tick_number=3)
            axi.set_ylim(0, 110)

        for i, vessel_number in enumerate(self.actor_numbers_by_type):
            axi: plt.Axes = ax_ambiguous_fec[i]
            axi.set_aspect("auto", adjustable="box")
            self.init_axi(i, axi, r"$\bf{Ambiguous}$" + "\nconsistent\n" + r"$\bf{FEC}$" + " rate")

            data, percentages, new_group_labels = get_data(
                self.measurements[vessel_number].values(),
                lambda eval_data: eval_data.best_scene.is_ambiguous_by_fec,
            )
            if len(data) == 0:
                continue

            bars: plt.BarContainer = axi.bar(
                new_group_labels,
                percentages,
                color=self.colors,
                edgecolor="black",
                linewidth=1.5,
            )
            if i == 0:
                self.set_yticks(axi, range(101), unit="%", tick_number=3)
            axi.set_ylim(0, 110)

        for i, vessel_number in enumerate(self.actor_numbers_by_type):
            axi: plt.Axes = ax_relevant_fsm[i]
            axi.set_aspect("auto", adjustable="box")
            self.init_axi(i, axi, r"$\bf{Relevant}$" + "\nconsistent\n" + r"$\bf{FSM}$" + " rate")

            data, percentages, new_group_labels = get_data(
                self.measurements[vessel_number].values(),
                lambda eval_data: eval_data.best_scene.is_relevant_by_fsm,
            )
            if len(data) == 0:
                continue

            bars: plt.BarContainer = axi.bar(
                new_group_labels,
                percentages,
                color=self.colors,
                edgecolor="black",
                linewidth=1.5,
            )
            if i == 0:
                self.set_yticks(axi, range(101), unit="%", tick_number=3)
            axi.set_ylim(0, 110)

        for i, vessel_number in enumerate(self.actor_numbers_by_type):
            axi: plt.Axes = axt_ambiguous_fsm[i]
            axi.set_aspect("auto", adjustable="box")
            self.init_axi(i, axi, r"$\bf{Ambiguous}$" + "\nconsistent\n" + r"$\bf{FSM}$" + " rate")

            data, percentages, new_group_labels = get_data(
                self.measurements[vessel_number].values(),
                lambda eval_data: eval_data.best_scene.is_ambiguous_by_fsm,
            )
            if len(data) == 0:
                continue

            bars: plt.BarContainer = axi.bar(
                new_group_labels,
                percentages,
                color=self.colors,
                edgecolor="black",
                linewidth=1.5,
            )
            if i == 0:
                self.set_yticks(axi, range(101), unit="%", tick_number=3)
            axi.set_ylim(0, 110)

        # Create a fake handle for the title (invisible box)
        # title_patch = mpatches.Patch(color='none', label='Approaches')

        # Prepend title to the handles and labels
        handles, labels = ax_relevant_fec[0].get_legend_handles_labels()
        # handles = [title_patch] + handles
        # labels = ['Approaches'] + labels
        fig.legend(handles, labels, ncol=5, loc="lower center", fontsize=10)

        return fig
