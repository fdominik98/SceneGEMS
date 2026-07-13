import tkinter as tk
from typing import List

from concrete_level.models.relation import Relation

from utils.colors import light_colors
from visualization.colreg_scenarios.components.modern_table import ModernTable
from visualization.colreg_scenarios.scenario_plot import ScenarioPlot

from .checkbox_components import Checkbox, CheckboxArray

SUBSCRIPT_TRANSLATION = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


class ColregControlComponent:
    """Component responsible for COLREG relationship controls and checkboxes."""

    def __init__(self, parent_frame: tk.Frame, trajectory_manager: TrajectoryManager, colreg_plot: ScenarioPlot):
        self.parent_frame = parent_frame
        self.trajectory_manager = trajectory_manager
        self.colreg_plot = colreg_plot

        # COLREG control outer frame
        self.rel_control_outer_frame = tk.Frame(self.parent_frame, background="white", relief=tk.RAISED, bd=1)
        self.rel_control_outer_frame.pack(side=tk.TOP, fill=tk.X, pady=(5, 5), padx=5)

        # Add title
        title_label = tk.Label(self.rel_control_outer_frame, text="COLREG Controls", font=("Arial", 10, "bold"), background="white")
        title_label.pack(side=tk.TOP, pady=(5, 5))

        # Modern table layout
        self.table = ModernTable(self.rel_control_outer_frame, corner_title="Component", row_header_width=240, cell_min_width=150)

        self.all_relations = list(self.trajectory_manager.monitored_trajectory.initial_monitored_scene_with_results.colregs_state_set.keys())
        self.row_definitions = self._build_row_definitions()
        self.checkbox_arrays: List[CheckboxArray] = []
        self._build_table()

    def _build_row_definitions(self):
        """Row configuration mirroring the legacy component order."""
        return [
            {"label": "Distance", "plot_components": [self.colreg_plot.distance_component.graphs_by_rels], "init_checked": False},
            {"label": "VO Vector", "plot_components": self.colreg_plot.vo_cone_component.graphs_by_rels[:1], "init_checked": False},
            {"label": "VO Cone", "plot_components": self.colreg_plot.vo_cone_component.graphs_by_rels[1:], "init_checked": False},
            {"label": "Additional VO Calculation", "plot_components": self.colreg_plot.add_vo_cone_component.graphs_by_rels, "init_checked": False},
            {"label": "P12 Vector", "plot_components": [self.colreg_plot.prime_component.p12_vec_graphs], "init_checked": False},
            {"label": "P21 Vector", "plot_components": [self.colreg_plot.prime_component.p21_vec_graphs], "init_checked": False},
            {
                "label": "Initial Potential Collision Domain",
                "plot_components": [self.colreg_plot.potential_collision_domain_component.start_potential_collision_domain_graphs],
                "init_checked": True,
            },
            {
                "label": "Current Potential Collision Domain",
                "plot_components": [self.colreg_plot.potential_collision_domain_component.current_potential_collision_domain_graphs],
                "init_checked": False,
            },
            {
                "label": "Safety Domains",
                "plot_components": [self.colreg_plot.safety_domain_component.graphs_by_rels],
                "init_checked": True,
            },
        ]

    def _build_table(self):
        row_headers = [row["label"] for row in self.row_definitions]

        column_headers = [self._format_relation_header(relation) for relation in self.all_relations]
        column_colors = [light_colors[relation.actor1.id] for relation in self.all_relations]

        def row_header_factory(row_idx: int, text: str, parent: tk.Frame):
            cb_array = CheckboxArray(parent, text, self.colreg_plot.fig)
            cb_array.checkbox.configure(
                font=("Segoe UI", 10, "bold"),
                background="#f3f4f6",
                foreground="#111827",
                anchor="center",
                justify="center",
            )
            cb_array.checkbox.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
            self.checkbox_arrays.append(cb_array)
            return cb_array.checkbox

        def column_header_factory(col_idx: int, text: str, parent: tk.Frame, bg: str):
            label = tk.Label(
                parent,
                text=text,
                font=("Segoe UI", 10, "bold"),
                background=bg,
                foreground="#111827",
                wraplength=self.table.cell_width_px - 16,
                justify="center",
            )
            label.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
            return label

        def cell_factory(row_idx: int, col_idx: int, parent: tk.Frame, bg: str):
            row_config = self.row_definitions[row_idx]
            relation = self.all_relations[col_idx]
            artists: List = []
            for pc in row_config["plot_components"]:
                artists.extend(self._collect_artists(pc, relation))

            if not artists:
                return self._create_unavailable_cell(parent, bg)

            checkbox = Checkbox(parent, artists, self.checkbox_arrays[row_idx], bg, row_config["init_checked"])
            checkbox.checkbox.configure(wraplength=self.table.cell_width_px - 16)
            checkbox.checkbox.pack_configure(fill=tk.BOTH, expand=True, padx=6, pady=6)
            return checkbox.checkbox

        self.table.build(
            row_headers=row_headers,
            column_headers=column_headers,
            column_colors=column_colors,
            row_header_factory=row_header_factory,
            column_header_factory=column_header_factory,
            cell_factory=cell_factory,
        )

        for checkbox_array in self.checkbox_arrays:
            checkbox_array.flush()

    def _create_unavailable_cell(self, parent: tk.Frame, background: str) -> tk.Label:
        label = tk.Label(
            parent,
            text="N/A",
            font=("Segoe UI", 10, "italic"),
            background=background,
            foreground="#6b7280",
            justify="center",
            wraplength=self.table.cell_width_px - 16,
        )
        label.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        return label

    def _collect_artists(self, component_store, relation: Relation) -> List:
        if isinstance(component_store, dict):
            entry = component_store.get(relation)
            return self._normalize_artists(entry)
        if hasattr(component_store, "get"):
            entry = component_store.get(relation)
            return self._normalize_artists(entry)
        if isinstance(component_store, (list, tuple)):
            result: List = []
            for item in component_store:
                result.extend(self._collect_artists(item, relation))
            return result
        return self._normalize_artists(component_store)

    def _normalize_artists(self, entry) -> List:
        if entry is None:
            return []
        if isinstance(entry, (list, tuple)):
            result: List = []
            for item in entry:
                result.extend(self._normalize_artists(item))
            return result
        return [entry]

    @staticmethod
    def _to_subscript(text: str) -> str:
        return text.translate(SUBSCRIPT_TRANSLATION)

    def _format_actor(self, actor) -> str:
        name = self.trajectory_manager.scenario.get_actor_name(actor)
        if "_" in name:
            base, _, suffix = name.partition("_")
            if suffix.isdigit():
                return f"{base}{self._to_subscript(suffix)}"
        return name

    def _format_relation_header(self, relation: Relation) -> str:
        actor1 = self._format_actor(relation.actor1)
        actor2 = self._format_actor(relation.actor2)
        return f"{actor1} → {actor2}"

    def _on_rel_control_frame_configure(self, event=None):
        """Keep the canvas scroll region in sync with the inner frame."""
        self.rel_control_canvas.configure(scrollregion=self.rel_control_canvas.bbox("all"))

    def _on_rel_control_mouse_wheel(self, event):
        """Handle horizontal scrolling with Shift + MouseWheel."""
        self.rel_control_canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_rel_control_mouse_wheel_vertical(self, event):
        """Handle vertical scrolling with MouseWheel."""
        self.rel_control_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
