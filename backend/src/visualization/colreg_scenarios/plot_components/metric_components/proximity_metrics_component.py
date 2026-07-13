from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple

from matplotlib import pyplot as plt

from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from evaluation.risk_evaluation import ProximityVector, RiskVector
from utils.colors import light_colors, colors, mix_colors
from utils.global_constants import ONE_N_MILE_IN_M
from visualization.colreg_scenarios.plot_components.plot_component import PlotComponent


class ProximityMetricComponent(PlotComponent, ABC):
    time_treshold = 10 * 60
    dist_treshold = 1 * ONE_N_MILE_IN_M

    def __init__(self, ax : plt.Axes, monitored_scene: MonitoredScene,  risk_vectors : List[RiskVector], ref_risk_vectors : Optional[List[RiskVector]] = None) -> None:
        super().__init__(ax, monitored_scene)
        self.risk_vectors =  risk_vectors
        self.ref_risk_vectors = ref_risk_vectors
        self.line_graphs : Dict[Tuple[ConcreteVessel, ConcreteVessel], plt.Line2D] = {}
        self.reference_line_graphs : Dict[Tuple[ConcreteVessel, ConcreteVessel], plt.Line2D] = {}
        self.threshold_graphs : Dict[Tuple[ConcreteVessel, ConcreteVessel], plt.Line2D] = {}
        self.ax = ax
        self.length = len(self.risk_vectors)
        self.ref_length = len(self.ref_risk_vectors) if self.ref_risk_vectors else 0

        #self.ax.set_title(self.get_title())
        self.ax.set_xlabel('Time (s)')
        self.ax.set_ylabel(rf'{self.get_metric_str()}')
        self.ax.set_aspect('auto', adjustable='box')

    def _vessel_pairs(self):
        """Yield (vessel1, vessel2) for OS-TS then TS-TS pairs."""
        self.monitored_scene.scene.all_vessel_pair_combinations

    @abstractmethod
    def get_y_metric(self, proximity_vector: ProximityVector) -> float:
        pass

    @abstractmethod
    def get_metric_str(self) -> str:
        pass

    @abstractmethod
    def get_threshold_y(self, proximity_vector: ProximityVector) -> float:
        pass

    @abstractmethod
    def get_threshold2_y(self) -> float:
        pass

    @abstractmethod
    def get_threshold2_label(self) -> str:
        pass

    @abstractmethod
    def get_y_lim(self) -> Tuple[float, float]:
        pass

    @abstractmethod
    def get_title(self) -> str:
        pass

    def use_same_color_for_reference(self) -> bool:
        """If True, reference (original) line uses same color as generated line for that pair. Default False."""
        return False

    def draw_threshold2_line(self) -> bool:
        """If True, draw the second threshold line (e.g. 1 NM) and its label. Default True."""
        return True

    def do_draw(self):
        max_len = max(self.length, self.ref_length) if self.ref_length else self.length
        x_full = range(0, max_len)
        for vessel1, vessel2 in self._vessel_pairs():
            if self.length == 0:
                break
            pair_key = (vessel1, vessel2)
            id1, id2 = vessel1.id, vessel2.id
            pair_color = mix_colors(colors[id1 % len(colors)], colors[id2 % len(colors)])
            pair_light_color = mix_colors(light_colors[id1 % len(light_colors)], light_colors[id2 % len(light_colors)])
            ref_color = pair_color if self.use_same_color_for_reference() else pair_light_color
            label = fr'${self.scenario.get_actor_name(vessel1)} \rightarrow {self.scenario.get_actor_name(vessel2)}$'
            if self.ref_risk_vectors is not None and self.ref_length > 0:
                x_ref = range(0, self.ref_length)
                y_ref = [self.get_y_metric(rv.proximity_vectors[pair_key]) for rv in self.ref_risk_vectors if pair_key in rv.proximity_vectors]
                if len(y_ref) == self.ref_length:
                    line, = self.ax.plot(x_ref, y_ref, color=ref_color, linewidth=2, linestyle='-')
                    self.reference_line_graphs[pair_key] = line
                    self.graphs += [line]
            if pair_key in self.risk_vectors[0].proximity_vectors:
                threshold_y = [self.get_threshold_y(self.risk_vectors[0].proximity_vectors[pair_key])] * self.length
                x_gen = range(0, self.length)
                y = [self.get_y_metric(rv.proximity_vectors[pair_key]) for rv in self.risk_vectors if pair_key in rv.proximity_vectors]
                if len(y) == self.length:
                    line, = self.ax.plot(x_gen, y, color=pair_color, linewidth=1.7, label=label, linestyle='--')
                    self.line_graphs[pair_key] = line
                    self.graphs += [line]

        if self.draw_threshold2_line():
            threshold2, = self.ax.plot(x_full, [self.get_threshold2_y()] * max_len, color='black', linewidth=1.5, linestyle='--')
            self.threshold_graphs['threshold2'] = threshold2
            self.graphs += [threshold2]
        threshold0, = self.ax.plot(x_full, [0] * max_len, color='black', linewidth=1.5, linestyle='--')
        self.threshold_graphs['basic'] = threshold0
        self.graphs += [threshold0]

        self.ax.margins(x=0.2, y=0.2)
        self.ax.set_xlim(0, max_len)
        self.ax.set_ylim(*self.get_y_lim())
        self.ax.legend()

        if self.draw_threshold2_line():
            ymin, ymax = self.ax.get_ylim()
            offset = (ymax - ymin) * 0.03
            self.ax.text(max_len / 2, self.get_threshold2_y() + offset, self.get_threshold2_label(), ha='center', va='center', fontsize=11, horizontalalignment='center')

        draw_extra = getattr(self, '_draw_extra', None)
        if callable(draw_extra):
            draw_extra()

    def do_update(self, monitored_scene: MonitoredScene) -> List[plt.Artist]:
        return self.graphs

class DistanceAxesComponent(ProximityMetricComponent):
    def __init__(self, ax : plt.Axes, monitored_scene: MonitoredScene, risk_vectors : List[RiskVector], ref_risk_vectors : Optional[List[RiskVector]] = None) -> None:
        super().__init__(ax, monitored_scene, risk_vectors, ref_risk_vectors)

    def use_same_color_for_reference(self) -> bool:
        return True

    def draw_threshold2_line(self) -> bool:
        return False

    def get_y_metric(self, proximity_vector : ProximityVector) -> float:
        return proximity_vector.dist

    def get_metric_str(self) -> str:
        return 'Distance (m)'

    def get_title(self) -> str:
        return "Distance"

    def get_y_lim(self) -> Tuple[float, float]:
        dist = max(self.risk_vectors[0].proximity_vectors.values(), key=lambda pv: pv.dist).dist
        return -0.1, max(dist * 2, self.get_threshold2_y() * 1.1)

    def get_threshold_y(self, proximity_vector : ProximityVector) -> float:
        return proximity_vector.props.safety_dist

    def get_threshold2_y(self) -> float:
        return self.dist_treshold

    def get_threshold2_label(self) -> str:
        return f'{(self.dist_treshold / ONE_N_MILE_IN_M):.0f} NM'

    def _draw_extra(self) -> None:
        """Draw small black markers at first collision time for each vessel pair (when scene.do_collide holds)."""
        if self.trajectory_manager is None:
            return
        for vessel1, vessel2 in self._vessel_pairs():
            for t in range(self.trajectory_manager.timespan):
                scenario = self.trajectory_manager.get_scenario(t)
                if scenario.do_collide(vessel1, vessel2):
                    line, = self.ax.plot(t, self.get_y_metric(self.risk_vectors[0].proximity_vectors[(vessel1, vessel2)]), 'ko', markersize=4, zorder=10)
                    self.graphs += [line]
                    break

class DCPAAxesComponent(ProximityMetricComponent):
    def __init__(self, ax : plt.Axes, monitored_scene: MonitoredScene,  risk_vectors : List[RiskVector],   ref_risk_vectors : Optional[List[RiskVector]] = None) -> None:
        super().__init__(ax, monitored_scene,  risk_vectors,   ref_risk_vectors)

    def get_y_metric(self, proximity_vector : ProximityVector) -> float:
        return proximity_vector.dcpa

    def get_metric_str(self) -> str:
        return 'DCPA (m)'

    def get_title(self) -> str:
        return 'Distance at closest point of approach'

    def get_y_lim(self) -> Tuple[float, float]:
        dcpa = max(self.risk_vectors[0].proximity_vectors.values(), key=lambda pv: pv.dcpa).dcpa
        #threshold = max(self.metrics, key=lambda metric: metric.relation.safety_dist).relation.safety_dist
        return -0.1, max(dcpa * 2, self.get_threshold2_y()*1.1)

    def get_threshold_y(self, proximity_vector : ProximityVector) -> float:
        return proximity_vector.props.safety_dist

    def get_threshold2_y(self) -> float:
        return self.dist_treshold

    def get_threshold2_label(self) -> str:
        return f'{(self.dist_treshold / ONE_N_MILE_IN_M):.0f} NM'

class TCPAAxesComponent(ProximityMetricComponent):
    def __init__(self, ax : plt.Axes, monitored_scene: MonitoredScene,  risk_vectors : List[RiskVector],   ref_risk_vectors : Optional[List[RiskVector]] = None) -> None:
        super().__init__(ax, monitored_scene,  risk_vectors,   ref_risk_vectors)

    def get_y_metric(self, proximity_vector : ProximityVector) -> float:
        return proximity_vector.tcpa

    def get_metric_str(self) -> str:
        return 'TCPA (s)'

    def get_title(self) -> str:
        return 'Time to closest point of approach'

    def get_y_lim(self) -> Tuple[float, float]:
        tcpa0 = max(self.risk_vectors[0].proximity_vectors.values(), key=lambda pv: pv.tcpa).tcpa
        return -100, max(tcpa0, self.get_threshold2_y()) * 1.1

    def get_threshold_y(self, proximity_vector : ProximityVector) -> float:
        return 0.0

    def get_threshold2_y(self) -> float:
        return self.time_treshold

    def get_threshold2_label(self) -> str:
        return f'{(self.time_treshold / 60):.0f} min'
