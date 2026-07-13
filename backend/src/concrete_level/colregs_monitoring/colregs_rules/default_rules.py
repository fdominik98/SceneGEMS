from concrete_level.colregs_monitoring.colregs_rules.colregs_rules import (
    GiveWayEarlyActionRule,
    GoAroundCollisionDomainSuggestion,
    OverturningSuggestion,
    PersistingCourseAfterCourseChangeRule,
    ReadilyApparentCourseChangeRule,
    ReadilyApparentCoursePersistenceRule,
    ReadilyApparentSpeedChangeRule,
    SafeDistanceRule,
    StandOnCoursePersistenceRule,
)
from concrete_level.colregs_monitoring.colregs_rules.conditions.give_way_early_action_condition import GiveWayEarlyActionCondition
from concrete_level.colregs_monitoring.colregs_rules.conditions.go_around_collision_domain_condition import GoAroundCollisionDomainCondition
from concrete_level.colregs_monitoring.colregs_rules.conditions.overturning_condition import OverturningCondition
from concrete_level.colregs_monitoring.colregs_rules.conditions.persisting_course_after_course_change_condition import PersistingCourseAfterCourseChangeCondition
from concrete_level.colregs_monitoring.colregs_rules.conditions.readily_apparent_course_change_condition import ReadilyApparentCourseChangeCondition
from concrete_level.colregs_monitoring.colregs_rules.conditions.readily_apparent_course_persistence_condition import ReadilyApparentCoursePersistenceCondition
from concrete_level.colregs_monitoring.colregs_rules.conditions.readily_apparent_speed_change_condition import ReadilyApparentSpeedChangeCondition
from concrete_level.colregs_monitoring.colregs_rules.conditions.rule_condition import COLREGSRuleConditionMap, COLREGSRuleConditionMapSet
from concrete_level.colregs_monitoring.colregs_rules.conditions.safe_distance_condition import SafeDistanceCondition
from concrete_level.colregs_monitoring.colregs_rules.conditions.stand_on_course_persistence_condition import StandOnCoursePersistenceCondition
from concrete_level.colregs_monitoring.maneuver_context import ManeuverContext, ManeuverContextSet
from concrete_level.colregs_monitoring.situation_context import COLREGSType, SituationContext, SituationContextSet


def make_maneuver_default_rules(maneuver_context: ManeuverContext) -> COLREGSRuleConditionMap:
    """Create default rules for a vessel"""
    actor = maneuver_context.vessel
    relation = maneuver_context.relation
    colregs_constants = maneuver_context.colregs_constants
    return COLREGSRuleConditionMap(
        {
            ReadilyApparentCourseChangeRule(actor, colregs_constants): ReadilyApparentCourseChangeCondition(relation, actor, colregs_constants),
            ReadilyApparentSpeedChangeRule(actor, colregs_constants): ReadilyApparentSpeedChangeCondition(relation, actor, colregs_constants),
            ReadilyApparentCoursePersistenceRule(actor, colregs_constants): ReadilyApparentCoursePersistenceCondition(relation, actor, colregs_constants),
            PersistingCourseAfterCourseChangeRule(actor, colregs_constants): PersistingCourseAfterCourseChangeCondition(relation, actor, colregs_constants),
            StandOnCoursePersistenceRule(actor, colregs_constants): StandOnCoursePersistenceCondition(relation, actor, colregs_constants),
            # overturning_suggestion: OverturningCondition(maneuver_context.relation, maneuver_context.vessel),
        }
    )


def make_head_on_situation_default_rules(situation_context: SituationContext) -> COLREGSRuleConditionMap:
    actor1 = situation_context.actor1
    actor2 = situation_context.actor2
    relation = situation_context.relation
    colregs_constants = situation_context.colregs_constants
    return COLREGSRuleConditionMap(
        {
            SafeDistanceRule(relation, colregs_constants): SafeDistanceCondition(relation, colregs_constants),
            GiveWayEarlyActionRule(actor1, colregs_constants): GiveWayEarlyActionCondition(relation, actor1, colregs_constants),
            GoAroundCollisionDomainSuggestion(actor1, colregs_constants): GoAroundCollisionDomainCondition(relation, actor1, colregs_constants),
            GiveWayEarlyActionRule(actor2, colregs_constants): GiveWayEarlyActionCondition(relation, actor2, colregs_constants),
            GoAroundCollisionDomainSuggestion(actor2, colregs_constants): GoAroundCollisionDomainCondition(relation, actor2, colregs_constants),
        }
    )


def make_overtaking_to_port_situation_default_rules(situation_context: SituationContext) -> COLREGSRuleConditionMap:
    actor1 = situation_context.actor1
    relation = situation_context.relation
    colregs_constants = situation_context.colregs_constants
    return COLREGSRuleConditionMap(
        {
            SafeDistanceRule(relation, colregs_constants): SafeDistanceCondition(relation, colregs_constants),
            GiveWayEarlyActionRule(actor1, colregs_constants): GiveWayEarlyActionCondition(relation, actor1, colregs_constants),
            GoAroundCollisionDomainSuggestion(actor1, colregs_constants): GoAroundCollisionDomainCondition(relation, actor1, colregs_constants),
        }
    )


def make_overtaking_to_starboard_situation_default_rules(situation_context: SituationContext) -> COLREGSRuleConditionMap:
    actor1 = situation_context.actor1
    relation = situation_context.relation
    colregs_constants = situation_context.colregs_constants
    return COLREGSRuleConditionMap(
        {
            SafeDistanceRule(relation, colregs_constants): SafeDistanceCondition(relation, colregs_constants),
            GiveWayEarlyActionRule(actor1, colregs_constants): GiveWayEarlyActionCondition(relation, actor1, colregs_constants),
            GoAroundCollisionDomainSuggestion(actor1, colregs_constants): GoAroundCollisionDomainCondition(relation, actor1, colregs_constants),
        }
    )


def make_crossing_from_port_situation_default_rules(situation_context: SituationContext) -> COLREGSRuleConditionMap:
    actor1 = situation_context.actor1
    relation = situation_context.relation
    colregs_constants = situation_context.colregs_constants
    return COLREGSRuleConditionMap(
        {
            SafeDistanceRule(relation, colregs_constants): SafeDistanceCondition(relation, colregs_constants),
            GiveWayEarlyActionRule(actor1, colregs_constants): GiveWayEarlyActionCondition(relation, actor1, colregs_constants),
            GoAroundCollisionDomainSuggestion(actor1, colregs_constants): GoAroundCollisionDomainCondition(relation, actor1, colregs_constants),
        }
    )


def make_other_situation_default_rules(other_situation_context: SituationContext) -> COLREGSRuleConditionMap:
    colregs_constants = other_situation_context.colregs_constants
    return COLREGSRuleConditionMap(
        {
            SafeDistanceRule(other_situation_context.relation, colregs_constants): SafeDistanceCondition(other_situation_context.relation, colregs_constants),
        }
    )


def make_two_way_crossing_from_port_situation_default_rules(situation_context: SituationContext) -> COLREGSRuleConditionMap:
    actor1 = situation_context.actor1
    actor2 = situation_context.actor2
    relation = situation_context.relation
    colregs_constants = situation_context.colregs_constants
    return COLREGSRuleConditionMap(
        {
            SafeDistanceRule(situation_context.relation, colregs_constants): SafeDistanceCondition(situation_context.relation, colregs_constants),
            GiveWayEarlyActionRule(actor1, colregs_constants): GiveWayEarlyActionCondition(relation, actor1, colregs_constants),
            GoAroundCollisionDomainSuggestion(actor1, colregs_constants): GoAroundCollisionDomainCondition(relation, actor1, colregs_constants),
            GiveWayEarlyActionRule(actor2, colregs_constants): GiveWayEarlyActionCondition(relation, actor2, colregs_constants),
            GoAroundCollisionDomainSuggestion(actor2, colregs_constants): GoAroundCollisionDomainCondition(relation, actor2, colregs_constants),
        }
    )


def make_two_way_crossing_from_starboard_situation_default_rules(situation_context: SituationContext) -> COLREGSRuleConditionMap:
    actor1 = situation_context.actor1
    actor2 = situation_context.actor2
    relation = situation_context.relation
    colregs_constants = situation_context.colregs_constants
    return COLREGSRuleConditionMap(
        {
            SafeDistanceRule(relation, colregs_constants): SafeDistanceCondition(relation, colregs_constants),
            GiveWayEarlyActionRule(actor1, colregs_constants): GiveWayEarlyActionCondition(relation, actor1, colregs_constants),
            GoAroundCollisionDomainSuggestion(actor1, colregs_constants): GoAroundCollisionDomainCondition(relation, actor1, colregs_constants),
            GiveWayEarlyActionRule(actor2, colregs_constants): GiveWayEarlyActionCondition(relation, actor2, colregs_constants),
            GoAroundCollisionDomainSuggestion(actor2, colregs_constants): GoAroundCollisionDomainCondition(relation, actor2, colregs_constants),
        }
    )


SITUATION_RULE_MAP = {
    COLREGSType.HEAD_ON: make_head_on_situation_default_rules,
    COLREGSType.OVERTAKING_TO_PORT: make_overtaking_to_port_situation_default_rules,
    COLREGSType.OVERTAKING_TO_STARBOARD: make_overtaking_to_starboard_situation_default_rules,
    COLREGSType.CROSSING_FROM_PORT: make_crossing_from_port_situation_default_rules,
    COLREGSType.TWO_WAY_CROSSING_FROM_PORT: make_two_way_crossing_from_port_situation_default_rules,
    COLREGSType.TWO_WAY_CROSSING_FROM_STARBOARD: make_two_way_crossing_from_starboard_situation_default_rules,
    COLREGSType.OTHER: make_other_situation_default_rules,
}


def make_default_situation_context_rules(situation_context_set: SituationContextSet) -> COLREGSRuleConditionMapSet:
    return COLREGSRuleConditionMapSet({relation: SITUATION_RULE_MAP[situation_context.situation_type](situation_context) for relation, situation_context in situation_context_set.items()})


def make_default_maneuver_context_rules(maneuver_context_set: ManeuverContextSet) -> COLREGSRuleConditionMapSet:
    return COLREGSRuleConditionMapSet({relation: make_maneuver_default_rules(maneuver_context) for relation, maneuver_context in maneuver_context_set.items()})
