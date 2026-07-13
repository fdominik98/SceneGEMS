from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any, Dict, List, Tuple

import numpy as np
from matplotlib import pyplot as plt

from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from utils.evaluation_config import DC_RS, DC_RS_PS, DC_SB_II, DC_SB_III, MSR_CDRS, MSR_CDRS_PS, MSR_SB_II, MSR_SB_III


class PlotBase(ABC):
    plt.rcParams["font.family"] = "serif"
    plt.rcParams["font.serif"] = ["Times New Roman"]
    plt.rcParams["font.size"] = 12
    plt.rcParams["pdf.fonttype"] = 42

    def __init__(self):
        super().__init__()
        self.fig = self.create_fig()

    @abstractmethod
    def create_fig(self) -> plt.Figure:
        pass


class EvalPlot(PlotBase, ABC):
    config_group_map = {
        DC_SB_II: "DC/SB2",
        DC_SB_III: "DC/SB3",
        MSR_SB_II: "MSR/SB2",
        MSR_SB_III: "MSR/SB3",
        DC_RS: "DC/RS",
        DC_RS_PS: "DC/RS+PS",
        MSR_CDRS: "MSR/RS",
        MSR_CDRS_PS: "MSR/RS+PS",
        "zhu_et_al": "Zhu",
        "base_reference": "BaseRef",
    }

    colors = {
        DC_SB_II: np.array([0.000, 0.500, 0.000, 1]),  # Green
        DC_SB_III: np.array([0.275, 0.600, 0.624, 1]),  # Teal (#469990)
        MSR_SB_II: np.array([1.000, 0.647, 0.000, 1]),  # Orange (#FFA500)
        MSR_SB_III: np.array([0.502, 0.000, 0.000, 1]),  # Maroon (#800000)
        DC_RS: np.array([0.000, 0.000, 0.459, 1]),  # Navy (#000075)
        DC_RS_PS: np.array([0.000, 0.749, 1.000, 1]),  # Sky Blue (#00bfff)
        MSR_CDRS: np.array([0.569, 0.118, 0.706, 1]),  # Purple (#911eb4)
        MSR_CDRS_PS: np.array([1.000, 0.000, 0.000, 1]),  # Red
    }

    actor_numbers_by_type_map = {
        (2, 0): "2 vessels",
        (2, 1): "2 vessels, 1 obstacle",
        (3, 0): "3 vessels",
        (3, 1): "3 vessels, 1 obstacle",
        (4, 0): "4 vessels",
        (5, 0): "5 vessels",
        (6, 0): "6 vessels",
    }

    algo_map = {
        "nsga2": "N2",
        "nsga3": "N3",
        "ga": "GA",
        "de": "DE",
        "pso": "PSO",
        "scenic": "Scenic",
    }
    aggregate_map = {
        "all": r"$\sum{}$",
        "actor": "A",
        "category": "C",
        "all_swarm": r"$\sum{s}$",
    }

    def __init__(self, eval_datas: List[EvaluationData], is_algo=False, is_all=False) -> None:
        self.comparison_groups: List[Any] = self.algos if is_algo else self.config_groups
        self.comparison_group_count = len(self.comparison_groups)
        self.vessel_num_count = len(self.actor_numbers_by_type)
        # self.colors = self.generate_colors(self.comparison_group_count)
        self.markers = ["o", "s", "^", "D", "v", "x", "*", "P", "h"]
        self.vessel_num_labels = [self.actor_numbers_by_type_map[vn] for vn in self.actor_numbers_by_type]
        self.group_labels = (
            [self.algo_map[algo] + "-" + self.aggregate_map[aggregate] for algo, aggregate in self.algos] if is_algo else [self.config_group_map[cg.lower()] for cg in self.config_groups]
        )

        self.measurements: Dict[Tuple[int, int], Dict[str, Dict[int, List[EvaluationData]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        # for actor_number_by_type in self.actor_numbers_by_type:
        #     for comparison_group in self.comparison_groups:
        #         self.measurements[actor_number_by_type][comparison_group] = []

        self.eval_datas: List[EvaluationData] = sorted(eval_datas, key=lambda eval_data: eval_data.timestamp)
        for eval_data in self.eval_datas:
            comparison_group = (eval_data.algorithm_desc.lower(), eval_data.aggregate_strat.lower()) if is_algo else eval_data.config_group.lower()
            if (not is_all and not eval_data.is_valid) or comparison_group not in self.comparison_groups or eval_data.actor_number_by_type not in self.actor_numbers_by_type:
                continue
            self.measurements[eval_data.actor_number_by_type][comparison_group][eval_data.random_seed].append(eval_data)
        super().__init__()

    @property
    @abstractmethod
    def config_groups(self) -> List[str]:
        pass

    @property
    @abstractmethod
    def actor_numbers_by_type(self) -> List[Tuple[int, int]]:
        pass

    @property
    def algos(self) -> List[Tuple[str, str]]:
        return []

    @staticmethod
    def generate_colors(size) -> List[np.ndarray]:
        # Convert the colors to RGB format
        color1_rgb = np.array((0, 0.5, 1))
        # if size == 1:
        #     return color1_rgb
        color2_rgb = np.array((1, 0.5, 0))
        # Generate a range of colors by linear interpolation
        # colors = [color1_rgb + (color2_rgb - color1_rgb) * i / (size - 1) for i in range(size)]
        # return [np.array([color[0], color[1], color[2], 0.7]) for color in colors]
        return [
            np.array([0.698, 0.875, 0.541, 1]),
            np.array([0.792, 0.698, 0.839, 1]),
            np.array([0.122, 0.471, 0.705, 1]),
            np.array([0.902, 0.333, 0.051, 1]),
            np.array([0.361, 0.596, 0.643, 1]),  # darker teal-blue
            np.array([0.494, 0.282, 0.415, 1]),
        ]  # muted plum/purple

    @staticmethod
    def convert_seconds_unit_list(seconds_list):
        """
        Converts a list of seconds into a common higher-order time unit if any value exceeds the threshold.
        Returns the converted list and the chosen unit.
        """
        max_val = max(seconds_list)

        if max_val >= 86400:
            factor, unit = 86400, "d"
        elif max_val >= 3600:
            factor, unit = 3600, "h"
        elif max_val >= 60:
            factor, unit = 60, "min"
        else:
            factor, unit = 1, "s"

        converted = [s / factor for s in seconds_list]
        return converted, factor, unit

    def set_yticks(
        self,
        axi: plt.Axes,
        values,
        unit: str = None,
        tick_number: int = 6,
        rotation: int = 0,
    ):
        if values is None or len(values) == 0:
            return

        # Handle time unit conversion if unit is in seconds
        ticks = np.linspace(0, max(values), tick_number)
        ticks = [round(t) for t in ticks]

        if unit is None:
            tick_labels = ticks
        elif unit == "s":
            new_ticks, factor, unit = self.convert_seconds_unit_list(ticks)
            new_ticks = [round(t) if float(t).is_integer() else round(t, 1) for t in new_ticks]
            ticks = [t * factor for t in new_ticks]
            tick_labels = [f"{v}{unit}" for v in new_ticks]
        else:
            tick_labels = [f"{round(t, 1)}{unit}" for t in ticks]

        # Add first and last tick explicitly (redundant if they already exist, but harmless)
        axi.set_yticks([ticks[0], ticks[-1]] + list(ticks), minor=False)
        axi.set_yticklabels([tick_labels[0], tick_labels[-1]] + list(tick_labels), rotation=rotation)

    def set_xticks(
        self,
        axi: plt.Axes,
        values,
        unit: str = None,
        tick_number: int = 6,
        rotation: int = 35,
    ):
        if values is None or len(values) == 0:
            return

        # Handle time unit conversion if unit is in seconds
        ticks = np.linspace(0, max(values), tick_number)
        ticks = [round(t) for t in ticks]

        if unit is None:
            tick_labels = ticks
        elif unit == "s":
            new_ticks, factor, unit = self.convert_seconds_unit_list(ticks)
            new_ticks = [round(t) if float(t).is_integer() else round(t, 1) for t in new_ticks]
            ticks = [t * factor for t in new_ticks]
            tick_labels = [f"{v}{unit}" for v in new_ticks]
        else:
            tick_labels = [f"{round(t, 1)}{unit}" for t in ticks]

        axi.set_xticks([ticks[0], ticks[-1]] + list(ticks), minor=False)
        axi.set_xticklabels([tick_labels[0], tick_labels[-1]] + list(tick_labels), rotation=rotation)

    def init_axi(self, pos: int, axi: plt.Axes, label: str):
        axi.set_aspect("auto", adjustable="box")
        if pos == 0:
            axi.set_ylabel(label, fontsize=14)
        axi.set_yticks([])
        axi.set_xticks([])


class DummyEvalPlot(EvalPlot):
    def __init__(self, eval_datas):
        super().__init__(eval_datas)

    def create_fig(self) -> plt.Figure:
        fig, axes = plt.subplots(1, 1, figsize=(7, 7))
        self.axi: plt.Axes = axes
        return fig

    @property
    def config_groups(self) -> List[str]:
        return [DC_SB_II, MSR_SB_III, DC_RS, MSR_CDRS_PS]

    @property
    def actor_numbers_by_type(self) -> List[Tuple[int, int]]:
        return []
