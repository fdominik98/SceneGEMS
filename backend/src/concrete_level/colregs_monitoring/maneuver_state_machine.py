from concrete_level.colregs_monitoring.maneuver import HeadingChange, ManeuverStateSet, ManeuverType, SpeedChange, UndetectedManeuver
from concrete_level.colregs_monitoring.maneuver_context import ManeuverContextSet
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.concrete_scene import ConcreteScene


class ManeuverStateMachine:
    """Static class for monitoring vessel maneuvers"""

    @staticmethod
    def create_initial_state_set(maneuver_context_set: ManeuverContextSet) -> ManeuverStateSet:
        """Create initial maneuver state for a vessel"""
        initial_maneuver_state_set = ManeuverStateSet()

        for context in maneuver_context_set.values():
            start_timestamp = context.start_timestamp
            current_timestamp = start_timestamp

            hc = HeadingChange(
                heading_diff_since_previous=0,
                heading_diff_since_start=0,
                heading_diff_time_window=[0],
                colregs_constants=context.colregs_constants,
            )

            sc = SpeedChange(
                speed_diff_since_previous=0,
                speed_diff_since_start=0,
                speed_diff_time_window=[0],
                colregs_constants=context.colregs_constants,
            )

            initial_maneuver_state_set[context.relation] = UndetectedManeuver(
                maneuver_context=context,
                maneuver_count=1,
                distance_made=0,
                start_timestamp=start_timestamp,
                current_timestamp=current_timestamp,
                heading_change=hc,
                speed_change=sc,
                previous_maneuver_type=ManeuverType.UNDETECTED,
                total_distance_made=0,
                colregs_constants=context.colregs_constants,
            )

        return initial_maneuver_state_set

    @staticmethod
    def step(
        current_monitored_scene: MonitoredScene,
        next_maneuver_context_set: ManeuverContextSet,
        next_scene: ConcreteScene,
        time_step: int,
    ) -> ManeuverStateSet:
        """Calculate next maneuver state for all vessels"""
        next_maneuver_state_set = ManeuverStateSet()
        current_maneuver_state_set = current_monitored_scene.maneuver_state_set
        for context in next_maneuver_context_set.values():
            current_maneuver_state = current_maneuver_state_set[context.relation]
            next_maneuver_state = current_maneuver_state.step(context, current_monitored_scene.scene, next_scene, time_step)
            next_maneuver_state_set[context.relation] = next_maneuver_state
        return next_maneuver_state_set
