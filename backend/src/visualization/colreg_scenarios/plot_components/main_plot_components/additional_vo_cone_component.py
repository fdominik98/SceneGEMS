from typing import Dict, List

import numpy as np
from matplotlib import pyplot as plt

from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.relation import Relation
from utils.math_utils import calculate_heading
from visualization.colreg_scenarios.plot_components.plot_component import PlotComponent


class AdditionalVOConeComponent(PlotComponent):
    def __init__(self, ax: plt.Axes, monitored_scene: MonitoredScene) -> None:
        super().__init__(ax, monitored_scene)
        self.circle_graphs: Dict[Relation, plt.Circle] = {}
        self.line1_graphs: Dict[Relation, plt.Line2D] = {}
        self.line2_graphs: Dict[Relation, plt.Line2D] = {}
        self.graphs_by_rels = [self.circle_graphs, self.line1_graphs, self.line2_graphs]
        self.zorder = -2

    def do_draw(self):
        for relation, colregs_state in self.monitored_scene.colregs_state_set.items():
            props = self.monitored_scene.scene.get_geo_props(relation.actor1, relation.actor2)
            vo_circle = plt.Circle(
                props.val2.p,
                props.safety_dist,
                color="black",
                fill=False,
                linestyle="--",
                linewidth=0.7,
                zorder=self.zorder,
            )
            self.ax.add_artist(vo_circle)
            self.circle_graphs[relation] = vo_circle
            # Calculate the angles of the cone
            angle_rel = calculate_heading(props.p12)
            sin_half_cone_theta = np.clip(props.safety_dist / props.o_distance, -1, 1)
            angle_half_cone = abs(np.arcsin(sin_half_cone_theta))  # [0, pi/2]
            angle1 = angle_rel + angle_half_cone
            angle2 = angle_rel - angle_half_cone

            # Plot the velocity obstacle cone
            cone1 = props.val1.p + np.array([np.cos(angle1), np.sin(angle1)]) * props.o_distance
            cone2 = props.val1.p + np.array([np.cos(angle2), np.sin(angle2)]) * props.o_distance

            (line1,) = self.ax.plot(
                [props.val1.x, cone1[0]],
                [props.val1.y, cone1[1]],
                "k--",
                linewidth=0.7,
                zorder=self.zorder,
            )
            self.line1_graphs[relation] = line1

            (line2,) = self.ax.plot(
                [props.val1.x, cone2[0]],
                [props.val1.y, cone2[1]],
                "k--",
                linewidth=0.7,
                zorder=self.zorder,
            )
            self.line2_graphs[relation] = line2
            self.graphs += [vo_circle, line1, line2]

    def do_update(self, monitored_scene: MonitoredScene) -> List[plt.Artist]:
        for relation, colregs_state in monitored_scene.colregs_state_set.items():
            if not (self.circle_graphs[relation].get_visible() or self.line1_graphs[relation].get_visible() or self.line2_graphs[relation].get_visible()):
                continue
            props = monitored_scene.scene.get_geo_props(relation.actor1, relation.actor2)
            self.circle_graphs[relation].set_center((props.val2.p[0], props.val2.p[1]))
            self.circle_graphs[relation].set_radius(props.safety_dist)
            # Calculate the angles of the cone
            # Calculate the angles of the cone
            angle_rel = calculate_heading(props.p12)

            # Calculate the angles of the cone
            angle_rel = calculate_heading(props.p12)
            sin_half_cone_theta = np.clip(props.safety_dist / props.o_distance, -1, 1)
            angle_half_cone = abs(np.arcsin(sin_half_cone_theta))  # [0, pi/2]
            angle1 = angle_rel + angle_half_cone
            angle2 = angle_rel - angle_half_cone

            # Plot the velocity obstacle cone
            cone1 = props.val1.p + np.array([np.cos(angle1), np.sin(angle1)]) * props.o_distance
            cone2 = props.val1.p + np.array([np.cos(angle2), np.sin(angle2)]) * props.o_distance

            self.line1_graphs[relation].set_data([props.val1.x, cone1[0]], [props.val1.y, cone1[1]])
            self.line2_graphs[relation].set_data([props.val1.x, cone2[0]], [props.val1.y, cone2[1]])
        return self.graphs
