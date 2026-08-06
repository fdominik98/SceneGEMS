import tkinter as tk
from typing import Dict, List, cast


from utils.colors import light_colors
from visualization.colreg_scenarios.components.modern_table import ModernTable
from visualization.colreg_scenarios.scenario_plot import ScenarioPlot

SUBSCRIPT_TRANSLATION = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


class ActorInfoComponent:
    """Component responsible for displaying actor information in a table format."""

    def __init__(self, parent_frame: tk.Frame, trajectory_manager: TrajectoryManager, colreg_plot: ScenarioPlot):
        self.parent_frame = parent_frame
        self.trajectory_manager = trajectory_manager
        self.colreg_plot = colreg_plot

        # Actor info outer frame
        self.actor_info_outer_frame = tk.Frame(self.parent_frame, background="white", relief=tk.RAISED, bd=1)
        self.actor_info_outer_frame.pack(side=tk.TOP, fill=tk.X, pady=(5, 5), padx=5)

        # Add title
        title_label = tk.Label(self.actor_info_outer_frame, text="Actor Information", font=("Arial", 10, "bold"), background="white")
        title_label.pack(side=tk.TOP, pady=(5, 5))

        # Create modern table layout
        self.table = ModernTable(self.actor_info_outer_frame, corner_title="Attribute", row_header_width=175, cell_min_width=150)

        # Build table structure
        self.row_headers = [
            "Type",
            "Length (m)",
            "Breadth (m)",
            "Radius (m)",
            "Position (m)",
            "Heading (rad)",
            "Speed (m/s)",
        ]
        self.actor_info_labels = self._build_table_cells()

        # Start updating actor info
        self.update_actor_info_labels()

    def _build_table_cells(self) -> List[List[tk.Label]]:
        """Create the table layout and return references to data labels."""
        logical_actors = list(self.trajectory_manager.logical_scenario.actor_variables)
        column_headers = [self._format_actor_header(actor.name, idx) for idx, actor in enumerate(logical_actors)]
        column_colors = [light_colors[actor.id] for actor in logical_actors]

        def cell_factory(row_index: int, column_index: int, parent: tk.Frame, bg: str) -> tk.Label:
            label = tk.Label(
                parent,
                text=":",
                font=("Segoe UI", 10),
                background=bg,
                foreground="#111827",
                wraplength=self.table.cell_width_px - 20,
                justify="center",
            )
            label.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
            return label

        return cast(
            List[List[tk.Label]],
            self.table.build(
                row_headers=self.row_headers,
                column_headers=column_headers,
                column_colors=column_colors,
                cell_factory=cell_factory,
            ),
        )

    def _get_actor_infos(self) -> Dict[int, List[str]]:
        """Get current actor information for display."""
        actor_infos: Dict[int, List[str]] = {}

        for (
            actor,
            state,
        ) in self.colreg_plot.animation.current_monitored_scene.scene.sorted_actor_states:
            actor_infos[actor.id] = [
                f"{actor.type}",
                f"{actor.length:.2f}",
                f"{actor.breadth:.2f}",
                f"{actor.safety_radius:.2f}",
                f"({state.x:.2f}, {state.y:.2f})",
                f"{state.heading:.2f}",
                f"{state.speed:.2f}",
            ]

        return actor_infos

    def update_actor_info_labels(self):
        """Update the actor information labels with current data."""
        if not self.actor_info_outer_frame.winfo_exists():
            return

        actor_infos = self._get_actor_infos()
        for i, actor in enumerate(self.trajectory_manager.logical_scenario.actor_variables):
            for j, info in enumerate(actor_infos[actor.id]):
                self.actor_info_labels[i][j].config(text=info)

        # Schedule the next update
        self.actor_info_outer_frame.after(50, self.update_actor_info_labels)

    @staticmethod
    def _to_subscript(text: str) -> str:
        return text.translate(SUBSCRIPT_TRANSLATION)

    def _format_actor_header(self, actor_name: str, index: int) -> str:
        """Render actor names with lower index representation."""
        if "_" in actor_name:
            base, _, suffix = actor_name.partition("_")
            if suffix.isdigit():
                return f"{base}{self._to_subscript(suffix)}"
        return f"{actor_name}{self._to_subscript(str(index + 1))}"
