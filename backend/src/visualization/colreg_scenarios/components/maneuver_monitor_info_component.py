import tkinter as tk
from typing import Dict, List

from concrete_level.models.relation import Relation

from utils.colors import light_colors
from visualization.colreg_scenarios.components.modern_table import ModernTable
from visualization.colreg_scenarios.components.tooltip import ToolTip
from visualization.colreg_scenarios.scenario_plot import ScenarioPlot

SUBSCRIPT_TRANSLATION = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


class ManeuverMonitorInfoComponent:
    """Component responsible for displaying maneuver monitor information for individual actors."""

    def __init__(self, parent_frame: tk.Frame, trajectory_manager: TrajectoryManager, colreg_plot: ScenarioPlot):
        self.parent_frame = parent_frame
        self.trajectory_manager = trajectory_manager
        self.colreg_plot = colreg_plot
        self.update_interval_ms = 200

        self.maneuver_monitor_info_outer_frame = tk.Frame(self.parent_frame, background="white", relief=tk.RAISED, bd=1)
        self.maneuver_monitor_info_outer_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        title_label = tk.Label(
            self.maneuver_monitor_info_outer_frame,
            text="Individual Actor Maneuver Status",
            font=("Arial", 10, "bold"),
            background="white",
        )
        title_label.pack(side=tk.TOP, pady=(5, 5))

        self.all_vessels = self.trajectory_manager.scenario.concrete_scene.vessels
        self.all_relations = [Relation(vessel, vessel) for vessel in self.all_vessels]

        self.table = ModernTable(
            self.maneuver_monitor_info_outer_frame,
            corner_title="Maneuver Info",
            row_header_width=230,
            cell_min_width=180,
        )

        self.row_headers = [
            "Maneuver Type",
            "Previous Maneuver Type",
            "Suggested Maneuvers",
            "Maneuver Count",
            "Distance Made",
            "Total Distance Made",
            "Timespan",
            "Heading Change Direction",
            "Heading Diff Since Previous",
            "Heading Diff Since Start",
            "Heading Diff Since Readily Apparent",
            "Start Timestamp",
            "Current Timestamp",
            "Just Started",
            "Readily Apparent Time Passed",
            "Time Spent in Current Maneuver",
            "Failed Rules",
            "Overall Status",
        ]

        self.tooltips: List[List[ToolTip]] = []
        self.maneuver_monitor_info_labels = self._build_table_cells()

        self.update_maneuver_monitor_info_labels()

    def _build_table_cells(self) -> List[List[tk.Label]]:
        column_headers = [self._format_actor_header(vessel.name, idx) for idx, vessel in enumerate(self.all_vessels)]
        column_colors = [light_colors[vessel.id] for vessel in self.all_vessels]
        self.tooltips = [[] for _ in column_headers]

        def cell_factory(row_idx: int, column_idx: int, parent: tk.Frame, bg: str) -> tk.Label:
            label = tk.Label(
                parent,
                text="-",
                font=("Segoe UI", 10),
                background=bg,
                foreground="#111827",
                wraplength=self.table.cell_width_px - 20,
                justify="center",
            )
            label.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
            tooltip = ToolTip(label, text="-")
            self.tooltips[column_idx].append(tooltip)
            return label

        return self.table.build(
            row_headers=self.row_headers,
            column_headers=column_headers,
            column_colors=column_colors,
            cell_factory=cell_factory,
        )

    def _get_maneuver_infos(self) -> Dict[Relation, List[str]]:
        maneuver_infos: Dict[Relation, List[str]] = {}

        try:
            current_time = int(self.colreg_plot.animation.current_sim_time)
            monitored_scene = self.trajectory_manager.monitored_trajectory.get_monitored_scene_by_time(current_time)

            for relation in self.all_relations:
                maneuver_state = monitored_scene.maneuver_state_set.get(relation, None)
                monitor_result = monitored_scene.monitor_result_map_set.get_result(relation)

                if maneuver_state:
                    suggested_maneuvers = "\n".join([maneuver.custom_name for maneuver in monitored_scene.maneuver_suggestions.get_all_maneuvers(relation.actor1)])
                    heading_change = maneuver_state.heading_change

                    failed_rules = monitor_result.get_failed_rules()
                    failed_rules_str = ",\n".join([str(rule) for rule in failed_rules]) if failed_rules else "None"
                    overall_status = "FAILED" if monitor_result.is_failed() else "NOT FAILED"

                    maneuver_infos[relation] = [
                        maneuver_state.type.custom_name,
                        maneuver_state.previous_maneuver_type.custom_name,
                        suggested_maneuvers,
                        str(maneuver_state.maneuver_count),
                        f"{maneuver_state.distance_made:.2f} m",
                        f"{maneuver_state.total_distance_made:.2f} m",
                        str(maneuver_state.timespan),
                        heading_change.detected_heading_direction,
                        f"{heading_change.heading_diff_since_previous_deg:.2f} deg",
                        f"{heading_change.heading_diff_since_start_deg:.2f} deg",
                        f"{heading_change.heading_diff_since_readily_apparent_time_deg:.2f} deg",
                        str(maneuver_state.start_timestamp),
                        str(maneuver_state.current_timestamp),
                        str(maneuver_state.just_started),
                        str(maneuver_state.readily_apparent_time_passed),
                        str(maneuver_state.current_timestamp - maneuver_state.start_timestamp),
                        failed_rules_str,
                        overall_status,
                    ]
                else:
                    maneuver_infos[relation] = ["N/A"] * self.num_rows

        except Exception:
            for relation in self.all_relations:
                maneuver_infos[relation] = ["N/A"] * self.num_rows

        return maneuver_infos

    def update_maneuver_monitor_info_labels(self):
        if not self.maneuver_monitor_info_outer_frame.winfo_exists():
            return

        maneuver_infos = self._get_maneuver_infos()
        default_row = ["N/A"] * self.num_rows

        for i, relation in enumerate(self.all_relations):
            column_cells = self.maneuver_monitor_info_labels[i]
            column_tooltips = self.tooltips[i] if i < len(self.tooltips) else []
            for j, info in enumerate(maneuver_infos.get(relation, default_row)):
                if j < len(column_cells):
                    label = column_cells[j]
                    if label.cget("text") != info:
                        label.config(text=info)
                        if j < len(column_tooltips):
                            column_tooltips[j].update_text(info)

        self.maneuver_monitor_info_outer_frame.after(self.update_interval_ms, self.update_maneuver_monitor_info_labels)

    @staticmethod
    def _to_subscript(value: str) -> str:
        return value.translate(SUBSCRIPT_TRANSLATION)

    def _format_actor_header(self, actor_name: str, index: int) -> str:
        if "_" in actor_name:
            base, _, suffix = actor_name.partition("_")
            if suffix.isdigit():
                return f"{base}{self._to_subscript(suffix)}"
        return f"{actor_name}{self._to_subscript(str(index + 1))}"

    @property
    def num_rows(self) -> int:
        return len(self.row_headers)
