from typing import Dict, List

import numpy as np
from matplotlib import pyplot as plt

from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor
from utils.colors import light_colors
from utils.global_constants import BOW_ANGLE, MAX_COORD, STERN_ANGLE
from visualization.colreg_scenarios.plot_components.plot_component import PlotComponent


class AngleCircleComponent(PlotComponent):
    # Define the angle and radius
    angle_circle_slice_1 = BOW_ANGLE  # 20 degree slice
    angle_circle_slice_2 = STERN_ANGLE  # 140 degree slice

    def __init__(self, ax: plt.Axes, monitored_scene: MonitoredScene, linewidth=0.8, radius_ratio=10) -> None:
        super().__init__(ax, monitored_scene)
        self.circle_graphs: Dict[ConcreteActor, plt.Circle] = {}
        self.line1_graphs: Dict[ConcreteActor, plt.Line2D] = {}
        self.line2_graphs: Dict[ConcreteActor, plt.Line2D] = {}
        self.line3_graphs: Dict[ConcreteActor, plt.Line2D] = {}
        self.line4_graphs: Dict[ConcreteActor, plt.Line2D] = {}
        self.graphs_by_vessel = [
            self.circle_graphs,
            self.line1_graphs,
            self.line2_graphs,
            self.line3_graphs,
            self.line4_graphs,
        ]
        self.zorder = -20

        self.linewidth = linewidth
        self.angle_circle_radius = MAX_COORD / radius_ratio

    def do_draw(self):
        for actor, state in self.monitored_scene.scene.items():
            self.one_draw(actor, state, self.zorder, light_colors[actor.id])

    def one_draw(self, actor: ConcreteActor, state: ActorState, zorder: int, circle_color):
        # Draw two lines centered on the vector
        circle_line1 = self.draw_line(
            state.p,
            state.v_norm_forward,
            -self.angle_circle_slice_1 / 2,
            circle_color,
            self.angle_circle_radius,
            zorder,
        )  # Left line
        self.line1_graphs[actor] = circle_line1
        circle_line2 = self.draw_line(
            state.p,
            state.v_norm_forward,
            self.angle_circle_slice_1 / 2,
            circle_color,
            self.angle_circle_radius,
            zorder,
        )  # Right line
        self.line2_graphs[actor] = circle_line2

        # Draw two lines centered on the negated vector
        circle_line3 = self.draw_line(
            state.p,
            state.v_norm_backward,
            -self.angle_circle_slice_2 / 2,
            circle_color,
            self.angle_circle_radius,
            zorder,
        )  # Left line
        self.line3_graphs[actor] = circle_line3
        circle_line4 = self.draw_line(
            state.p,
            state.v_norm_backward,
            self.angle_circle_slice_2 / 2,
            circle_color,
            self.angle_circle_radius,
            zorder,
        )  # Right line
        self.line4_graphs[actor] = circle_line4

        # # Plot vectors for better visibility
        # v1_scaled = state.v_norm * MAX_COORD / 11
        # big_quiver = self.ax.quiver(state.x, state.y, v1_scaled[0], v1_scaled[1], angles='xy', scale_units='xy', scale=1,
        #                             color=light_colors[vessel.id], zorder=zorder)

        # self.graphs += [circle, circle_line1, circle_line2, circle_line3, circle_line4, big_quiver]

        circle = plt.Circle(
            (state.p[0], state.p[1]),
            self.angle_circle_radius,
            fill=False,
            color=circle_color,
            linewidth=self.linewidth,
            zorder=zorder,
        )
        self.ax.add_artist(circle)
        self.circle_graphs[actor] = circle

        self.graphs += [circle, circle_line1, circle_line2, circle_line3, circle_line4]

    # Function to draw lines for slices
    def draw_line(self, origin, center_vector, angle, color, length, zorder):
        x, y = self.get_line_x_y(origin, center_vector, angle, length)
        (line,) = self.ax.plot(x, y, color=color, linewidth=self.linewidth, zorder=zorder)
        return line

    def get_line_x_y(self, origin, center_vector, angle, length):
        direction = np.array([np.cos(angle), np.sin(angle)])
        rotation_matrix = np.array(
            [
                [center_vector[0], -center_vector[1]],
                [center_vector[1], center_vector[0]],
            ]
        )
        rotated_direction = rotation_matrix.dot(direction)
        end_point = origin + length * rotated_direction
        return [origin[0], end_point[0]], [origin[1], end_point[1]]

    def do_update(self, monitored_scene: MonitoredScene) -> List[plt.Artist]:
        for vessel, state in monitored_scene.scene.items():
            self.update_one(vessel, state)
        return self.graphs

    def update_one(self, actor: ConcreteActor, state: ActorState):
        if not self.circle_graphs[actor].get_visible():
            return
        self.circle_graphs[actor].set_center((state.p[0], state.p[1]))
        self.circle_graphs[actor].set_radius(self.angle_circle_radius)

        x1, y1 = self.get_line_x_y(
            state.p,
            state.v_norm_forward,
            -self.angle_circle_slice_1 / 2,
            self.angle_circle_radius,
        )
        self.line1_graphs[actor].set_data(x1, y1)

        x2, y2 = self.get_line_x_y(
            state.p,
            state.v_norm_forward,
            self.angle_circle_slice_1 / 2,
            self.angle_circle_radius,
        )
        self.line2_graphs[actor].set_data(x2, y2)

        x3, y3 = self.get_line_x_y(
            state.p,
            state.v_norm_backward,
            -self.angle_circle_slice_2 / 2,
            self.angle_circle_radius,
        )
        self.line3_graphs[actor].set_data(x3, y3)

        x4, y4 = self.get_line_x_y(
            state.p,
            state.v_norm_backward,
            self.angle_circle_slice_2 / 2,
            self.angle_circle_radius,
        )
        self.line4_graphs[actor].set_data(x4, y4)
