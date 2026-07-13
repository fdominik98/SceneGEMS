from typing import Dict, List

from matplotlib import pyplot as plt

from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.relation import Relation
from visualization.colreg_scenarios.plot_components.plot_component import PlotComponent


class PrimeComponent(PlotComponent):
    def __init__(self, ax: plt.Axes, monitored_scene: MonitoredScene) -> None:
        super().__init__(ax, monitored_scene)
        self.p12_vec_graphs: Dict[Relation, plt.Quiver] = {}
        self.p21_vec_graphs: Dict[Relation, plt.Quiver] = {}
        self.zorder = -15

    def do_draw(self):
        for relation, colregs_state in self.monitored_scene.colregs_state_set.items():
            props = self.monitored_scene.scene.get_geo_props(relation.actor1, relation.actor2)

            p12_scaled = props.p12 * 0.95
            p12_vec = self.ax.quiver(
                props.val1.x,
                props.val1.y,
                p12_scaled[0],
                p12_scaled[1],
                angles="xy",
                scale_units="xy",
                scale=1,
                color="black",
                zorder=self.zorder,
                width=0.006,
            )
            self.p12_vec_graphs[relation] = p12_vec

            p21_scaled = props.p21 * 0.95
            p21_vec = self.ax.quiver(
                props.val2.x,
                props.val2.y,
                p21_scaled[0],
                p21_scaled[1],
                angles="xy",
                scale_units="xy",
                scale=1,
                color="black",
                zorder=self.zorder,
                width=0.006,
            )
            self.p21_vec_graphs[relation] = p21_vec

            self.graphs += [p12_vec, p21_vec]

    def do_update(self, monitored_scene: MonitoredScene) -> List[plt.Artist]:
        for relation, colregs_state in monitored_scene.colregs_state_set.items():
            props = monitored_scene.scene.get_geo_props(relation.actor1, relation.actor2)
            if self.p12_vec_graphs[relation].get_visible():
                p12_scaled = props.p12 * 0.95
                self.p12_vec_graphs[relation].set_offsets(props.val1.p)
                self.p12_vec_graphs[relation].set_UVC(p12_scaled[0], p12_scaled[1])
            if self.p21_vec_graphs[relation].get_visible():
                p21_scaled = props.p21 * 0.95
                self.p21_vec_graphs[relation].set_offsets(props.val2.p)
                self.p21_vec_graphs[relation].set_UVC(p21_scaled[0], p21_scaled[1])
        return self.graphs
