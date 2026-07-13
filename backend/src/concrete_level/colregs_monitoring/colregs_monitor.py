from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResultMapSet
from concrete_level.colregs_monitoring.colregs_state_machine import COLREGSStateMachine
from concrete_level.colregs_monitoring.maneuver_context import ManeuverContextSet
from concrete_level.colregs_monitoring.maneuver_state_machine import ManeuverStateMachine
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene, MonitoredSceneWithResults
from concrete_level.colregs_monitoring.rule_state_machine import RuleStateMachine
from concrete_level.colregs_monitoring.situation_context_set_state_machine import SituationContextSetStateMachine
from concrete_level.models.concrete_scene import ConcreteScene
from utils.colregs_approximations import COLREGSConstraints


class COLREGSMonitor:
    def __init__(self, initial_scene: ConcreteScene, colregs_constants: COLREGSConstraints) -> None:
        self.colregs_constants = colregs_constants

        # Store initial maneuver states for each vessel
        self.initial_maneuver_context_set = ManeuverContextSet.from_scene(initial_scene, 0, colregs_constants)
        self.initial_maneuver_state_set = ManeuverStateMachine.create_initial_state_set(self.initial_maneuver_context_set)

        # Create situation contexts and initial monitor states for each actor pair
        self.initial_situation_context_set = SituationContextSetStateMachine.create_initial_state_set(initial_scene, 0, colregs_constants)
        self.initial_monitor_state_set = COLREGSStateMachine.create_initial_state_set(self.initial_situation_context_set)

        self.initial_rules = RuleStateMachine.create_initial_rules(self.initial_situation_context_set, self.initial_maneuver_context_set)
        monitored_scene = MonitoredScene(
            scene=initial_scene,
            situation_context_set=self.initial_situation_context_set,
            colregs_state_set=self.initial_monitor_state_set,
            maneuver_state_set=self.initial_maneuver_state_set,
            timestamp=0,
        )
        self.initial_monitored_scene_with_results = MonitoredSceneWithResults(
            monitored_scene=monitored_scene,
            monitor_result_map_set=COLREGSRuleResultMapSet(),
            maneuver_suggestions=self.initial_rules.suggest_maneuvers(monitored_scene, 0),
        )

    def step(self, current_monitored_scene_with_results: MonitoredSceneWithResults, next_scene: ConcreteScene, time_step: int) -> MonitoredSceneWithResults:
        current_monitored_scene = current_monitored_scene_with_results.monitored_scene
        next_timestamp = current_monitored_scene_with_results.timestamp + time_step

        # Step 1: Update situation context set based on the next scene
        next_situation_context_set = SituationContextSetStateMachine.step(current_monitored_scene, next_scene, next_timestamp, self.colregs_constants)
        next_maneuver_context_set = self.initial_maneuver_context_set

        # Step 2: Update maneuver states for all vessels
        next_maneuver_state_set = ManeuverStateMachine.step(current_monitored_scene, next_maneuver_context_set, next_scene, time_step)

        # Step 3: Update COLREGS monitor states for all relations
        next_colregs_state_set = COLREGSStateMachine.step(current_monitored_scene, next_situation_context_set, next_scene, next_maneuver_state_set, next_timestamp)

        # Step 4: Create MonitorScene
        next_monitored_scene = MonitoredScene(
            scene=next_scene,
            situation_context_set=next_situation_context_set,
            colregs_state_set=next_colregs_state_set,
            maneuver_state_set=next_maneuver_state_set,
            timestamp=next_timestamp,
        )

        # Step 5: Update active rules and rule results when situation contexts change
        next_rules, transitioned_monitor_result_map_set = RuleStateMachine.step(
            current_monitored_scene.situation_context_set,
            next_situation_context_set,
            next_maneuver_context_set,
            current_monitored_scene_with_results.monitor_result_map_set,
        )
        next_monitor_result_map_set = next_rules.check(current_monitored_scene, transitioned_monitor_result_map_set, next_monitored_scene)

        return MonitoredSceneWithResults(
            monitored_scene=next_monitored_scene,
            monitor_result_map_set=next_monitor_result_map_set,
            maneuver_suggestions=next_rules.suggest_maneuvers(next_monitored_scene, time_step),
        )
