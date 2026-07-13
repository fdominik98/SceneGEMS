from typing import Dict, List

import numpy as np
from matplotlib import pyplot as plt

from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.relation import Relation
from utils.colors import colors
from utils.math_utils import calculate_heading
from visualization.colreg_scenarios.plot_components.plot_component import PlotComponent


class VOConeComponent(PlotComponent):
    def __init__(self, ax: plt.Axes, monitored_scene: MonitoredScene) -> None:
        super().__init__(ax, monitored_scene)
        self.other_velocity_graphs: Dict[Relation, plt.Quiver] = {}
        self.line1_graphs: Dict[Relation, plt.Line2D] = {}
        self.line2_graphs: Dict[Relation, plt.Line2D] = {}
        self.filling_graphs: Dict[Relation, plt.Polygon] = {}
        self.graphs_by_rels = [
            self.other_velocity_graphs,
            self.line1_graphs,
            self.line2_graphs,
            self.filling_graphs,
        ]
        self.zorder = -1

    def do_draw(self):
        for relation, colregs_state in self.monitored_scene.colregs_state_set.items():
            props = self.monitored_scene.scene.get_geo_props(relation.actor1, relation.actor2)
            # Calculate the angles of the cone
            angle_rel = calculate_heading(props.p12)
            sin_half_cone_theta = np.clip(props.safety_dist / props.o_distance, -1, 1)
            angle_half_cone = abs(np.arcsin(sin_half_cone_theta))  # [0, pi/2]
            angle1 = angle_rel + angle_half_cone
            angle2 = angle_rel - angle_half_cone

            cone_size = props.o_distance

            cone1 = props.val2.v + props.val1.p + np.array([np.cos(angle1), np.sin(angle1)]) * cone_size
            cone2 = props.val2.v + props.val1.p + np.array([np.cos(angle2), np.sin(angle2)]) * cone_size

            (line1,) = self.ax.plot(
                [props.val2.v[0] + props.val1.x, cone1[0]],
                [props.val2.v[1] + props.val1.y, cone1[1]],
                "--",
                color=colors[relation.actor2.id],
                linewidth=0.7,
                zorder=self.zorder,
            )
            (line2,) = self.ax.plot(
                [props.val2.v[0] + props.val1.x, cone2[0]],
                [props.val2.v[1] + props.val1.y, cone2[1]],
                "--",
                color=colors[relation.actor2.id],
                linewidth=0.7,
                zorder=self.zorder,
            )
            self.line1_graphs[relation] = line1
            self.line2_graphs[relation] = line2

            # Move the other vessels velocity vector in the o1 position to see if the vector is in the VO cone
            other_velocity = self.ax.quiver(
                props.val1.x,
                props.val1.y,
                props.val2.v[0],
                props.val2.v[1],
                angles="xy",
                scale_units="xy",
                scale=1,
                color=colors[relation.actor2.id],
                zorder=self.zorder - 10,
            )
            self.other_velocity_graphs[relation] = other_velocity

            # Fill the cone with a semi-transparent color
            filling = self.ax.fill(
                [props.val2.v[0] + props.val1.x, cone1[0], cone2[0]],
                [props.val2.v[1] + props.val1.y, cone1[1], cone2[1]],
                color=colors[relation.actor2.id],
                alpha=0.15,
                zorder=self.zorder,
            )
            self.filling_graphs[relation] = filling[0]

            self.graphs += [line1, line2, other_velocity, filling[0]]

    def do_update(self, monitored_scene: MonitoredScene) -> List[plt.Artist]:
        for relation, colregs_state in monitored_scene.colregs_state_set.items():
            if not (
                self.line1_graphs[relation].get_visible()
                or self.line2_graphs[relation].get_visible()
                or self.other_velocity_graphs[relation].get_visible()
                or self.filling_graphs[relation].get_visible()
            ):
                continue
            props = monitored_scene.scene.get_geo_props(relation.actor1, relation.actor2)
            # Calculate the angles of the cone
            angle_rel = calculate_heading(props.p12)
            sin_half_cone_theta = np.clip(props.safety_dist / props.o_distance, -1, 1)
            angle_half_cone = abs(np.arcsin(sin_half_cone_theta))  # [0, pi/2]
            angle1 = angle_rel + angle_half_cone
            angle2 = angle_rel - angle_half_cone

            cone_size = props.o_distance

            cone1 = props.val2.v + props.val1.p + np.array([np.cos(angle1), np.sin(angle1)]) * cone_size
            cone2 = props.val2.v + props.val1.p + np.array([np.cos(angle2), np.sin(angle2)]) * cone_size
            self.line1_graphs[relation].set_data(
                [props.val2.v[0] + props.val1.x, cone1[0]],
                [props.val2.v[1] + props.val1.y, cone1[1]],
            )
            self.line2_graphs[relation].set_data(
                [props.val2.v[0] + props.val1.x, cone2[0]],
                [props.val2.v[1] + props.val1.y, cone2[1]],
            )
            self.other_velocity_graphs[relation].set_offsets(props.val1.p)
            self.other_velocity_graphs[relation].set_UVC(props.val2.v[0], props.val2.v[1])

            polx = [props.val2.v[0] + props.val1.x, cone1[0], cone2[0]]
            poly = [props.val2.v[1] + props.val1.y, cone1[1], cone2[1]]
            self.filling_graphs[relation].set_xy(np.array([polx, poly]).T)
        return self.graphs
