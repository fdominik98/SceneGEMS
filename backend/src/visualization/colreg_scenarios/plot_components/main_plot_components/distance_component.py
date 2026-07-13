from typing import Dict, List

from matplotlib import pyplot as plt

from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.relation import Relation
from utils.global_constants import ONE_N_MILE_IN_M
from visualization.colreg_scenarios.plot_components.plot_component import PlotComponent


class DistanceComponent(PlotComponent):
    def __init__(self, ax: plt.Axes, monitored_scene: MonitoredScene) -> None:
        super().__init__(ax, monitored_scene)
        self.text_graphs: Dict[Relation, plt.Text] = {}
        self.line_graphs: Dict[Relation, plt.Line2D] = {}
        self.graphs_by_rels = [self.text_graphs, self.line_graphs]
        self.zorder = -3

    def do_draw(self):
        for relation, colregs_state in self.monitored_scene.colregs_state_set.items():
            props = self.monitored_scene.scene.get_geo_props(relation.actor1, relation.actor2)

            if props.o_distance < 1000:
                text_str = f"{props.o_distance:.0f} m"
            else:
                text_str = f"{props.o_distance / ONE_N_MILE_IN_M:.1f} NM"
            text = self.ax.text(
                props.val1.p[0] + props.p12[0] / 2,
                props.val1.p[1] + props.p12[1] / 2,
                text_str,
                fontsize=10,
                color="black",
                zorder=self.zorder + 10,
            )
            self.text_graphs[relation] = text

            (line,) = self.ax.plot(
                [props.val1.x, props.val2.x],
                [props.val1.y, props.val2.y],
                color="black",
                linewidth=0.8,
                zorder=self.zorder,
            )
            self.line_graphs[relation] = line

            self.graphs += [text, line]

    def do_update(self, monitored_scene: MonitoredScene) -> List[plt.Artist]:
        for relation, colregs_state in monitored_scene.colregs_state_set.items():
            if not (self.text_graphs[relation].get_visible() or self.line_graphs[relation].get_visible()):
                continue
            props = monitored_scene.scene.get_geo_props(relation.actor1, relation.actor2)

            self.text_graphs[relation].set_position((props.val1.p[0] + props.p12[0] / 2, props.val1.p[1] + props.p12[1] / 2))
            if props.o_distance < 1000:
                text_str = f"{props.o_distance:.0f} m"
            else:
                text_str = f"{props.o_distance / ONE_N_MILE_IN_M:.1f} NM"
            self.text_graphs[relation].set_text(text_str)

            self.line_graphs[relation].set_data([props.val1.x, props.val2.x], [props.val1.y, props.val2.y])
        return self.graphs
