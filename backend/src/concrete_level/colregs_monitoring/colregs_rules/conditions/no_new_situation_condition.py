from typing import List

from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
from concrete_level.colregs_monitoring.colregs_rules.conditions.rule_condition import RuleCondition
from concrete_level.colregs_monitoring.colregs_rules.maneuver_suggestions import ManeuverSuggestions
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.colregs_monitoring.situation_context import COLREGSType
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.relation import Relation
from utils.colregs_approximations import COLREGSConstraints


class NoNewSituationCondition(RuleCondition):
    """Rule 8(c): an alteration of course made to avoid collision must not result in another close-quarters situation.

    Kept per vessel (keyed by the vessel with itself). The vessel is resolving an encounter
    once it has made a course change in one that is still running. While it is, a new
    COLREGS situation that begins for it, with any vessel and in any role, fails the rule.
    Who caused the new situation is not judged: the vessel that altered course is the one
    that has to keep clear of creating it. A speed change alone does not count, since
    8(c) is about an alteration of course.
    """

    def __init__(self, relation: Relation, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(relation, actor, colregs_constants)

    def condition(self, current_monitored_scene: MonitoredScene, next_monitored_scene: MonitoredScene) -> COLREGSRuleResult:
        """Rule 8(c) over one step.

        Failed when a new situation begins for the vessel while it is resolving another
        one. Passed when every encounter it altered course in has ended without that.
        Unknown while it is still resolving one, and while it is resolving none.
        """
        if not self.is_resolving_in_step(current_monitored_scene, next_monitored_scene):
            return COLREGSRuleResult.UNKNOWN
        if self.new_situation_relations(current_monitored_scene, next_monitored_scene):
            return COLREGSRuleResult.FAILED
        if not self.resolved_relations(next_monitored_scene):
            return COLREGSRuleResult.PASSED
        return COLREGSRuleResult.UNKNOWN

    def next_result(self, previous_result: COLREGSRuleResult, current_monitored_scene: MonitoredScene, next_monitored_scene: MonitoredScene) -> COLREGSRuleResult:
        """A pass holds until the vessel alters course in a running encounter again.

        The rule is kept per vessel and stays active for the whole run, so the rule state
        machine never retires it; without this the pass of one step would fall back to
        unknown on the next (see ``StandOnCoursePersistenceCondition.next_result``).
        """
        result = super().next_result(previous_result, current_monitored_scene, next_monitored_scene)
        if result is COLREGSRuleResult.UNKNOWN and previous_result is COLREGSRuleResult.PASSED and not self.is_resolving_in_step(current_monitored_scene, next_monitored_scene):
            return COLREGSRuleResult.PASSED
        return result

    def maneuver_suggestions(self, current_monitored_scene: MonitoredScene, time_step: int) -> ManeuverSuggestions:
        # Which manoeuvre types keep the vessel out of a new situation depends on where the
        # other vessels are, not on the manoeuvre type, so the rule narrows nothing here.
        return ManeuverSuggestions()

    def running_relations(self, monitored_scene: MonitoredScene) -> List[Relation]:
        """The encounters of this vessel that are running at the scene: a situation, and not yet past and clear."""
        running: List[Relation] = []
        for relation, situation_context in monitored_scene.situation_context_set.items():
            if self.actor not in relation or situation_context.situation_type is COLREGSType.OTHER:
                continue
            colregs_state = monitored_scene.colregs_state_set.get(relation)
            if colregs_state is not None and colregs_state.actors_passed_each_other:
                continue
            running.append(relation)
        return running

    def resolved_relations(self, monitored_scene: MonitoredScene) -> List[Relation]:
        """The running encounters in which this vessel has made a course change.

        The manoeuvre flags are dropped when an encounter begins, so a course change made
        before the encounter existed does not count as resolving it.
        """
        resolved: List[Relation] = []
        for relation in self.running_relations(monitored_scene):
            colregs_state = monitored_scene.colregs_state_set.get(relation)
            if colregs_state is None:
                continue
            if colregs_state.actors_have_been_in_right_maneuver.get(self.actor, False) or colregs_state.actors_have_been_in_left_maneuver.get(self.actor, False):
                resolved.append(relation)
        return resolved

    def is_resolving_in_step(self, current_monitored_scene: MonitoredScene, next_monitored_scene: MonitoredScene) -> bool:
        """The vessel is manoeuvring to resolve an encounter during this step.

        Either it had already altered course in an encounter running when the step began,
        or it is in a course change at the end of the step with such an encounter running:
        the alteration that creates the new situation may be the one made in this step.
        """
        if self.resolved_relations(current_monitored_scene):
            return True
        if not self.running_relations(current_monitored_scene):
            return False
        maneuver_state = next_monitored_scene.maneuver_state_set.get(self.relation)
        return maneuver_state is not None and maneuver_state.is_course_change

    def new_situation_relations(self, current_monitored_scene: MonitoredScene, next_monitored_scene: MonitoredScene) -> List[Relation]:
        """The pairs of this vessel that were in no situation when the step began and are in one when it ends.

        An encounter that is relabelled (a crossing that develops into an overtaking) is
        the same encounter, not a new one, so only a pair coming out of OTHER counts.
        """
        new_relations: List[Relation] = []
        for relation, next_context in next_monitored_scene.situation_context_set.items():
            if self.actor not in relation or next_context.situation_type is COLREGSType.OTHER:
                continue
            current_context = current_monitored_scene.situation_context_set.get(relation)
            if current_context is None or current_context.situation_type is COLREGSType.OTHER:
                new_relations.append(relation)
        return new_relations
