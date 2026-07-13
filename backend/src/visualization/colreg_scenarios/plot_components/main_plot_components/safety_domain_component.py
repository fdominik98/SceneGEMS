from typing import Dict, List

import numpy as np
from matplotlib import pyplot as plt
from matplotlib.collections import LineCollection

from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.relation import Relation
from utils.colors import colors
from visualization.colreg_scenarios.plot_components.plot_component import PlotComponent


class SafetyDomainComponent(PlotComponent):
    def __init__(self, ax: plt.Axes, monitored_scene: MonitoredScene) -> None:
        super().__init__(ax, monitored_scene)
        self.safety_domain_graphs_actor1: Dict[Relation, LineCollection] = {}
        self.safety_domain_graphs_actor2: Dict[Relation, LineCollection] = {}
        self.graphs_by_rels: Dict[Relation, List[plt.Artist]] = {}

    @staticmethod
    def _segments_from_points(points: np.ndarray) -> List[List[List[float]]]:
        if points.size == 0 or points.shape[0] < 2:
            return []
        segments = np.stack((points[:-1], points[1:]), axis=1)
        return segments.tolist()

    def _create_line_collection(self, points: np.ndarray, color: str) -> LineCollection:
        segments = self._segments_from_points(points)
        line_collection = LineCollection(
            segments,
            colors=[color],
            linewidths=1.5,
            zorder=self.zorder,
            capstyle="round",
            joinstyle="round",
        )
        self.ax.add_collection(line_collection)
        return line_collection

    def do_draw(self):
        for relation, situation_context in self.monitored_scene.situation_context_set.items():
            points_to_plot_actor1 = np.asarray(situation_context.get_safety_domains(self.monitored_scene.scene)[0].points_for_plotting)
            points_to_plot_actor2 = np.asarray(situation_context.get_safety_domains(self.monitored_scene.scene)[1].points_for_plotting)

            safety_domain_graph_actor1 = self._create_line_collection(points_to_plot_actor1, colors[relation.actor2.id])
            safety_domain_graph_actor2 = self._create_line_collection(points_to_plot_actor2, colors[relation.actor1.id])
            self.safety_domain_graphs_actor1[relation] = safety_domain_graph_actor1
            self.safety_domain_graphs_actor2[relation] = safety_domain_graph_actor2
            self.graphs_by_rels[relation] = [safety_domain_graph_actor1, safety_domain_graph_actor2]

            self.graphs += [safety_domain_graph_actor1, safety_domain_graph_actor2]

    def do_update(self, monitored_scene: MonitoredScene) -> List[plt.Artist]:
        for relation, situation_context in monitored_scene.situation_context_set.items():
            if self.safety_domain_graphs_actor1[relation].get_visible():
                points_to_plot_actor1 = np.asarray(situation_context.get_safety_domains(monitored_scene.scene)[0].points_for_plotting)
                segments_actor1 = self._segments_from_points(points_to_plot_actor1)
                self.safety_domain_graphs_actor1[relation].set_segments(segments_actor1)
            if self.safety_domain_graphs_actor2[relation].get_visible():
                points_to_plot_actor2 = np.asarray(situation_context.get_safety_domains(monitored_scene.scene)[1].points_for_plotting)
                segments_actor2 = self._segments_from_points(points_to_plot_actor2)
                self.safety_domain_graphs_actor2[relation].set_segments(segments_actor2)
        return self.graphs
