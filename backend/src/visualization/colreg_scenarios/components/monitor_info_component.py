import tkinter as tk
from typing import Dict, List, cast

from concrete_level.models.relation import Relation

from utils.colors import light_colors
from visualization.colreg_scenarios.components.modern_table import ModernTable
from visualization.colreg_scenarios.components.tooltip import ToolTip
from visualization.colreg_scenarios.scenario_plot import ScenarioPlot

SUBSCRIPT_TRANSLATION = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


class MonitorInfoComponent:
    """Component responsible for displaying COLREG monitor state and results for each vessel pair."""

    def __init__(self, parent_frame: tk.Frame, trajectory_manager: TrajectoryManager, colreg_plot: ScenarioPlot):
        self.parent_frame = parent_frame
        self.trajectory_manager = trajectory_manager
        self.colreg_plot = colreg_plot
        self.update_interval_ms = 200

        self.monitor_info_outer_frame = tk.Frame(self.parent_frame, background="white", relief=tk.RAISED, bd=1)
        self.monitor_info_outer_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        title_label = tk.Label(self.monitor_info_outer_frame, text="Monitor Status", font=("Arial", 10, "bold"), background="white")
        title_label.pack(side=tk.TOP, pady=(5, 5))

        self.all_relations = list(self.trajectory_manager.monitored_trajectory.first_colregs_state_set.keys())

        self.table = ModernTable(self.monitor_info_outer_frame, corner_title="Monitor Info", row_header_width=240, cell_min_width=170)

        self.row_headers = [
            "COLREGS Situation",
            "Time Spent in Current Context",
            "Avoidance Directions",
            "Global Avoidance Direction",
            "Give-way responsibility",
            "Global give-way responsibility",
            "See Each Other",
            "Passed Each Other",
            "Right of Start State",
            "Left of Start State",
            "Have Been in Right Maneuver",
            "Have Been in Left Maneuver",
            "Passed Potential Collision Domain",
            "In Front of Potential Collision Domain",
            "Violate Safety Domain",
            "On Collision Course",
            "Has Low TCPA",
            "Failed Rules",
            "Overall Status",
        ]

        self.tooltips: List[List[ToolTip]] = []
        self.monitor_info_labels = self._build_table_cells()

        self.update_monitor_info_labels()

    def _build_table_cells(self) -> List[List[tk.Label]]:
        column_headers = [self._format_relation_header(relation) for relation in self.all_relations]
        column_colors = [light_colors[relation.actor1.id] for relation in self.all_relations]
        self.tooltips = [[] for _ in column_headers]

        def cell_factory(row_idx: int, column_idx: int, parent: tk.Frame, bg: str) -> tk.Label:
            label = tk.Label(
                parent,
                text="—",
                font=("Segoe UI", 10),
                background=bg,
                foreground="#111827",
                wraplength=self.table.cell_width_px - 20,
                justify="center",
            )
            label.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
            tooltip = ToolTip(label, text="—")
            self.tooltips[column_idx].append(tooltip)
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

    def _get_monitor_infos(self) -> Dict[Relation, List[str]]:
        monitor_infos: Dict[Relation, List[str]] = {}

        try:
            current_time = int(self.colreg_plot.animation.current_sim_time)
            monitored_scene = self.trajectory_manager.monitored_trajectory.get_monitored_scene_by_time(current_time)

            for relation in self.all_relations:
                colregs_state = monitored_scene.colregs_state_set.get(relation, None)
                situation_context_set = monitored_scene.situation_context_set
                situation_context = situation_context_set.get(relation, None)
                monitor_result = monitored_scene.monitor_result_map_set.get_result(relation)

                if colregs_state and situation_context:
                    time_spent_in_current_context = current_time - situation_context.start_timestamp
                    right_of_start_state = (
                        f"{relation.actor1.name}: {colregs_state.actors_right_of_start_state[relation.actor1]}, "
                        f"{relation.actor2.name}: {colregs_state.actors_right_of_start_state[relation.actor2]}"
                    )
                    left_of_start_state = (
                        f"{relation.actor1.name}: {colregs_state.actors_left_of_start_state[relation.actor1]}, " f"{relation.actor2.name}: {colregs_state.actors_left_of_start_state[relation.actor2]}"
                    )
                    have_been_in_right_maneuver = (
                        f"{relation.actor1.name}: {colregs_state.actors_have_been_in_right_maneuver[relation.actor1]}, "
                        f"{relation.actor2.name}: {colregs_state.actors_have_been_in_right_maneuver[relation.actor2]}"
                    )
                    have_been_in_left_maneuver = (
                        f"{relation.actor1.name}: {colregs_state.actors_have_been_in_left_maneuver[relation.actor1]}, "
                        f"{relation.actor2.name}: {colregs_state.actors_have_been_in_left_maneuver[relation.actor2]}"
                    )
                    passed_potential_collision_domain = (
                        f"{relation.actor1.name}: {colregs_state.actors_passed_potential_collision_domain[relation.actor1]}, "
                        f"{relation.actor2.name}: {colregs_state.actors_passed_potential_collision_domain[relation.actor2]}"
                    )
                    in_front_of_potential_collision_domain = (
                        f"{relation.actor1.name}: {colregs_state.actors_in_front_of_potential_collision_domain[relation.actor1]}, "
                        f"{relation.actor2.name}: {colregs_state.actors_in_front_of_potential_collision_domain[relation.actor2]}"
                    )
                    avoidance_direction = (
                        f"{relation.actor1.name}: {situation_context.avoidance_direction(relation.actor1).custom_name}, "
                        f"{relation.actor2.name}: {situation_context.avoidance_direction(relation.actor2).custom_name}"
                    )
                    global_avoidance_direction = (
                        f"{relation.actor1.name}: {situation_context_set.actor_avoidance_direction(relation.actor1).custom_name}, "
                        f"{relation.actor2.name}: {situation_context_set.actor_avoidance_direction(relation.actor2).custom_name}"
                    )
                    give_way_responsibility = (
                        f"{relation.actor1.name}: {situation_context.is_give_way_actor(relation.actor1)}, " f"{relation.actor2.name}: {situation_context.is_give_way_actor(relation.actor2)}"
                    )
                    global_give_way_responsibility = (
                        f"{relation.actor1.name}: {situation_context_set.actor_has_to_give_way(relation.actor1)}, "
                        f"{relation.actor2.name}: {situation_context_set.actor_has_to_give_way(relation.actor2)}"
                    )

                    failed_rules = monitor_result.get_failed_rules()
                    failed_rules_str = ",\n".join([str(rule) for rule in failed_rules]) if failed_rules else "None"
                    overall_status = "FAILED" if monitor_result.is_failed() else "NOT FAILED"

                    monitor_infos[relation] = [
                        situation_context.situation_type.custom_name,
                        str(time_spent_in_current_context),
                        avoidance_direction,
                        global_avoidance_direction,
                        give_way_responsibility,
                        global_give_way_responsibility,
                        str(colregs_state.actors_see_each_other),
                        str(colregs_state.actors_passed_each_other),
                        right_of_start_state,
                        left_of_start_state,
                        have_been_in_right_maneuver,
                        have_been_in_left_maneuver,
                        passed_potential_collision_domain,
                        in_front_of_potential_collision_domain,
                        str(colregs_state.actors_violate_safety_domain),
                        str(colregs_state.actors_on_collision_course),
                        str(colregs_state.actors_have_low_tcpa),
                        failed_rules_str,
                        overall_status,
                    ]
                else:
                    monitor_infos[relation] = ["N/A"] * self.num_rows

        except Exception:
            for relation in self.all_relations:
                monitor_infos[relation] = ["N/A"] * self.num_rows

        return monitor_infos

    def update_monitor_info_labels(self):
        if not self.monitor_info_outer_frame.winfo_exists():
            return

        monitor_infos = self._get_monitor_infos()
        default_row = ["N/A"] * self.num_rows

        for i, relation in enumerate(self.all_relations):
            column_cells = self.monitor_info_labels[i]
            column_tooltips = self.tooltips[i] if i < len(self.tooltips) else []
            for j, info in enumerate(monitor_infos.get(relation, default_row)):
                if j < len(column_cells):
                    label = column_cells[j]
                    if label.cget("text") != info:
                        label.config(text=info)
                        if j < len(column_tooltips):
                            column_tooltips[j].update_text(info)

        self.monitor_info_outer_frame.after(self.update_interval_ms, self.update_monitor_info_labels)

    @staticmethod
    def _to_subscript(value: str) -> str:
        return value.translate(SUBSCRIPT_TRANSLATION)

    def _format_actor_name(self, actor_name: str) -> str:
        if "_" in actor_name:
            base, _, suffix = actor_name.partition("_")
            if suffix.isdigit():
                return f"{base}{self._to_subscript(suffix)}"
        return actor_name

    def _format_relation_header(self, relation: Relation) -> str:
        actor1 = self._format_actor_name(self.trajectory_manager.scenario.get_actor_name(relation.actor1))
        actor2 = self._format_actor_name(self.trajectory_manager.scenario.get_actor_name(relation.actor2))
        return f"{actor1} → {actor2}"

    @property
    def num_rows(self) -> int:
        return len(self.row_headers)
