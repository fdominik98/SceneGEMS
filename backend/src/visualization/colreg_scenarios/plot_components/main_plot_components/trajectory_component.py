from typing import Dict, List

from matplotlib import pyplot as plt

from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor
from utils.colors import light_colors
from visualization.colreg_scenarios.plot_components.plot_component import PlotComponent


class TrajectoryComponent(PlotComponent):
    def __init__(self, ax: plt.Axes, monitored_scene: MonitoredScene) -> None:
        super().__init__(ax, monitored_scene)
        self.trajectory_line_graphs: Dict[ConcreteActor, plt.Line2D] = {}
        self.xs: Dict[ConcreteActor, List[float]] = {actor: [] for actor in monitored_scene.scene.actors}
        self.ys: Dict[ConcreteActor, List[float]] = {actor: [] for actor in monitored_scene.scene.actors}
        self.zorder = -14

    def do_draw(self):
        for actor, state in self.monitored_scene.scene.items():
            (line,) = self.ax.plot(
                self.xs[actor],
                self.ys[actor],
                ":",
                lw=3,
                color=light_colors[actor.id],
                zorder=self.zorder,
            )
            self.trajectory_line_graphs[actor] = line
            self.graphs.append(line)

    def do_update(self, monitored_scene: MonitoredScene):
        for actor, state in monitored_scene.scene.items():
            self._update_actor_trajectory(actor, state)
        return self.graphs

    def _update_actor_trajectory(self, actor: ConcreteActor, state: ActorState):
        xs = self.xs[actor]
        ys = self.ys[actor]
        current_pos = (state.x, state.y)

        if current_pos in zip(xs, ys):
            try:
                current_index = list(zip(xs, ys)).index(current_pos)
                xs[:] = xs[: current_index + 1]
                ys[:] = ys[: current_index + 1]
            except ValueError:
                xs.append(state.x)
                ys.append(state.y)
        else:
            xs.append(state.x)
            ys.append(state.y)

        self.trajectory_line_graphs[actor].set_data(xs, ys)

    def reset(self):
        for actor in self.monitored_scene.scene.actors:
            self.xs[actor].clear()
            self.ys[actor].clear()
        return super().reset()
