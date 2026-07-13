from copy import deepcopy
from typing import Dict, List

import numpy as np
from matplotlib import pyplot as plt

from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.relation import Relation
from utils.colors import colors
from visualization.colreg_scenarios.plot_components.plot_component import PlotComponent


class PotentialCollisionDomainComponent(PlotComponent):
    def __init__(self, ax: plt.Axes, monitored_scene: MonitoredScene) -> None:
        super().__init__(ax, monitored_scene)
        self.start_potential_collision_domain_graphs: Dict[Relation, List[plt.Circle]] = {}
        self.current_potential_collision_domain_graphs: Dict[Relation, List[plt.Circle]] = {}

    def do_draw(self):
        for relation, colregs_state in self.monitored_scene.colregs_state_set.items():
            domain_collection1, domain_collection2 = self.monitored_scene.scene.potential_safety_domains(relation.actor1, relation.actor2)
            start_circles = []
            current_circles = []
            for domain in domain_collection1.domains:
                center = domain.center
                radius = domain.center_end_distance
                start_circle = plt.Circle((center[0], center[1]), radius, color=colors[relation.actor1.id], fill=True, linestyle="-", alpha=0.3, zorder=self.zorder)
                current_circle = deepcopy(start_circle)
                self.ax.add_artist(start_circle)
                self.ax.add_artist(current_circle)
                start_circles.append(start_circle)
                current_circles.append(current_circle)
            for domain in domain_collection2.domains:
                center = domain.center
                radius = domain.center_end_distance
                start_circle = plt.Circle((center[0], center[1]), radius, color=colors[relation.actor2.id], fill=True, linestyle="-", alpha=0.3, zorder=self.zorder)
                current_circle = deepcopy(start_circle)
                self.ax.add_artist(start_circle)
                self.ax.add_artist(current_circle)
                start_circles.append(start_circle)
                current_circles.append(current_circle)
            self.start_potential_collision_domain_graphs[relation] = start_circles
            self.current_potential_collision_domain_graphs[relation] = current_circles
            self.graphs += start_circles + current_circles

    def do_update(self, monitored_scene: MonitoredScene) -> List[plt.Artist]:
        # for relation, colregs_state in monitored_scene.colregs_state_set.items():
        #     for current_graph in self.current_potential_collision_domain_graphs[relation]:
        #         if not current_graph.get_visible():
        #             continue
        #         domain_collection1, domain_collection2 = self.monitored_scene.scene.potential_safety_domains(relation.actor1, relation.actor2)
        #         if domains is None:
        #             center = np.array([0, 0])
        #             radius = 0.0
        #         else:
        #             domain1, _ = domains
        #             center = domain1.center
        #             radius = domain1.center_end_distance
        #         self.current_potential_collision_domain_graphs[relation].set_center((center[0], center[1]))
        #         self.current_potential_collision_domain_graphs[relation].set_radius(radius)

        return self.graphs
