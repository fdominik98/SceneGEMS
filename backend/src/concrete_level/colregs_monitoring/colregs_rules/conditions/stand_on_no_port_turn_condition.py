from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
from concrete_level.colregs_monitoring.colregs_rules.conditions.rule_condition import RuleCondition
from concrete_level.colregs_monitoring.colregs_rules.maneuver_suggestions import ManeuverSuggestions
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.colregs_monitoring.situation_context import COLREGSType
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.relation import Relation
from utils.colregs_approximations import COLREGSConstraints


class StandOnNoPortTurnCondition(RuleCondition):
    """Rule 17(c): the stand-on vessel of a crossing does not alter course to port for a vessel on her own port side.

    Kept per vessel (keyed by the vessel with itself), like Rule 17(a)(i), so that a failure
    names the vessel that broke it and the planner's repair steers that vessel, not the
    give-way vessel of the encounter. It binds while the vessel stands on in a crossing from
    port that is still running: the give-way vessel of such a crossing is always on the
    stand-on vessel's port side, so any course change to port fails. A turn to port made
    before the vessel was released also fails Rule 17(a)(i); this rule judges the side only.

    Rule 17(b) needs no exception here: the clearance of an encounter is gone exactly when a
    safety domain is violated, and the monitor ends a running encounter at that moment
    (``SituationContextStateMachine.step``), so the rule no longer binds when the stand-on
    vessel has to take whatever action best aids to avoid collision.
    """

    def __init__(self, relation: Relation, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(relation, actor, colregs_constants)

    def condition(self, current_monitored_scene: MonitoredScene, next_monitored_scene: MonitoredScene) -> COLREGSRuleResult:
        """Failed on a turn to port while bound; passed when the obligation ends in this step; unknown otherwise."""
        if self.is_bound(next_monitored_scene):
            maneuver_state = next_monitored_scene.maneuver_state_set.get(self.relation)
            if maneuver_state is not None and maneuver_state.is_course_change_to_the_left:
                return COLREGSRuleResult.FAILED
            return COLREGSRuleResult.UNKNOWN
        if self.is_bound(current_monitored_scene):
            return COLREGSRuleResult.PASSED
        return COLREGSRuleResult.UNKNOWN

    def next_result(self, previous_result: COLREGSRuleResult, current_monitored_scene: MonitoredScene, next_monitored_scene: MonitoredScene) -> COLREGSRuleResult:
        """A pass holds until the vessel is bound again (see ``StandOnCoursePersistenceCondition.next_result``)."""
        result = super().next_result(previous_result, current_monitored_scene, next_monitored_scene)
        if result is COLREGSRuleResult.UNKNOWN and previous_result is COLREGSRuleResult.PASSED and not self.is_bound(next_monitored_scene):
            return COLREGSRuleResult.PASSED
        return result

    def is_bound(self, monitored_scene: MonitoredScene) -> bool:
        """The vessel stands on in a crossing from port that has not ended at this scene."""
        for relation, situation_context in monitored_scene.situation_context_set.items():
            if self.actor not in relation or situation_context.situation_type is not COLREGSType.CROSSING_FROM_PORT:
                continue
            if not situation_context.is_stand_on_actor(self.actor):
                continue
            colregs_state = monitored_scene.colregs_state_set.get(relation)
            if colregs_state is None or not colregs_state.actors_passed_each_other:
                return True
        return False

    def maneuver_suggestions(self, current_monitored_scene: MonitoredScene, time_step: int) -> ManeuverSuggestions:
        # Narrowing the side here could leave a vessel that is also give-way in another
        # encounter with no allowed manoeuvre; the failure alone rejects a turn to port.
        return ManeuverSuggestions()
