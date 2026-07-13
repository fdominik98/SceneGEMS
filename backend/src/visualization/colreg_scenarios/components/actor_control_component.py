import tkinter as tk
from typing import List


from utils.colors import light_colors
from visualization.colreg_scenarios.components.modern_table import ModernTable
from visualization.colreg_scenarios.scenario_plot import ScenarioPlot

from .checkbox_components import Checkbox, CheckboxArray

SUBSCRIPT_TRANSLATION = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


class ActorControlComponent:
    """Component responsible for actor visibility controls and checkboxes."""

    def __init__(self, parent_frame: tk.Frame, trajectory_manager: TrajectoryManager, colreg_plot: ScenarioPlot):
        self.parent_frame = parent_frame
        self.trajectory_manager = trajectory_manager
        self.colreg_plot = colreg_plot

        # Actor control outer frame
        self.actor_control_outer_frame = tk.Frame(self.parent_frame, background="white", relief=tk.RAISED, bd=1)
        self.actor_control_outer_frame.pack(side=tk.TOP, fill=tk.X, pady=(5, 5), padx=5)

        # Add title
        title_label = tk.Label(self.actor_control_outer_frame, text="Actor Controls", font=("Arial", 10, "bold"), background="white")
        title_label.pack(side=tk.TOP, pady=(5, 5))

        # Modern table for controls
        self.table = ModernTable(self.actor_control_outer_frame, corner_title="Component", row_header_width=210, cell_min_width=140)

        self.row_definitions = self._build_row_definitions()
        self.checkbox_arrays: List[CheckboxArray] = []
        self._build_table()

    def _build_row_definitions(self):
        """Describe each checkbox row for easier layout."""
        return [
            {"label": "Dot", "plot_components": [self.colreg_plot.ship_markings_component.ship_dot_graphs], "init_checked": False},
            {"label": "Velocity", "plot_components": [self.colreg_plot.ship_markings_component.velocity_graphs], "init_checked": False},
            {"label": "Radius", "plot_components": [self.colreg_plot.ship_markings_component.radius_graphs], "init_checked": False},
            {"label": "Icon", "plot_components": [self.colreg_plot.ship_image_component.image_graphs], "init_checked": True},
            {"label": "Trajectory", "plot_components": [self.colreg_plot.trajectory_component.trajectory_line_graphs], "init_checked": True},
            {"label": "Centered Sector Circle", "plot_components": self.colreg_plot.angle_circle_component.graphs_by_vessel, "init_checked": True},
            {
                "label": "Large Centered Sector Circle",
                "plot_components": self.colreg_plot.centered_angle_circle_component.graphs_by_vessel,
                "init_checked": False,
            },
        ]

    def _build_table(self):
        row_headers = [row["label"] for row in self.row_definitions]
        concrete_actors = list(self.trajectory_manager.concrete_scene.actors)

        column_headers = [self._format_actor_header(actor.name, idx) for idx, actor in enumerate(concrete_actors)]
        column_colors = [light_colors[actor.id] for actor in concrete_actors]

        def row_header_factory(row_idx: int, text: str, parent: tk.Frame):
            cb_array = CheckboxArray(parent, text, self.colreg_plot.fig)
            cb_array.checkbox.configure(
                font=("Segoe UI", 10, "bold"),
                background="#f3f4f6",
                foreground="#111827",
                anchor="center",
                justify="center",
                wraplength=self.table.row_header_width - 16,
            )
            cb_array.checkbox.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
            self.checkbox_arrays.append(cb_array)
            return cb_array.checkbox

        def cell_factory(row_idx: int, col_idx: int, parent: tk.Frame, bg: str):
            row_config = self.row_definitions[row_idx]
            actor = concrete_actors[col_idx]
            for pc in row_config["plot_components"]:
                if actor not in pc:
                    raise Exception("data and column dimensions do not match!")
            checkbox = Checkbox(
                parent,
                [pc[actor] for pc in row_config["plot_components"]],
                self.checkbox_arrays[row_idx],
                bg,
                row_config["init_checked"],
            )
            checkbox.checkbox.configure(wraplength=self.table.cell_width_px - 16)
            checkbox.checkbox.pack_configure(fill=tk.BOTH, expand=True, padx=6, pady=6)
            return checkbox.checkbox

        self.table.build(
            row_headers=row_headers,
            column_headers=column_headers,
            column_colors=column_colors,
            row_header_factory=row_header_factory,
            cell_factory=cell_factory,
        )

        for checkbox_array in self.checkbox_arrays:
            checkbox_array.flush()

    @staticmethod
    def _to_subscript(text: str) -> str:
        return text.translate(SUBSCRIPT_TRANSLATION)

    def _format_actor_header(self, actor_name: str, index: int) -> str:
        if "_" in actor_name:
            base, _, suffix = actor_name.partition("_")
            if suffix.isdigit():
                return f"{base}{self._to_subscript(suffix)}"
        return f"{actor_name}{self._to_subscript(str(index + 1))}"
