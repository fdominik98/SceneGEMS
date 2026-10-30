"""COLREGSRule.rule_id: the stable id of a rule on the wire."""

from concrete_level.colregs_monitoring.colregs_rules.colregs_rules import GoAroundCollisionDomainSuggestion, SafeDistanceRule, StandOnCoursePersistenceRule
from concrete_level.models.relation import Relation
from scenegems_tool.vessel_stack.calibration.reference_scenarios import make_vessel
from tests.concrete_level.colregs_monitoring.monitor_runs import OWN_SHIP, TARGET, constants


def test_the_id_is_built_from_the_identity_fields():
    assert SafeDistanceRule(Relation(OWN_SHIP, TARGET), constants()).rule_id == "rule:8:passing-at-a-safe-distance:0-1:-"
    assert StandOnCoursePersistenceRule(TARGET, constants()).rule_id == "rule:17:stand-on-vessel-keeps-course-and-speed:1-1:1"
    assert GoAroundCollisionDomainSuggestion(OWN_SHIP, constants()).rule_id == "suggestion:-:pass-around-the-collision-domain:0-0:0"


def test_equal_rules_have_equal_ids_and_different_rules_different_ones():
    assert StandOnCoursePersistenceRule(TARGET, constants()).rule_id == StandOnCoursePersistenceRule(TARGET, constants()).rule_id
    assert StandOnCoursePersistenceRule(TARGET, constants()).rule_id != StandOnCoursePersistenceRule(OWN_SHIP, constants()).rule_id


def test_the_id_does_not_depend_on_names():
    renamed = make_vessel(1, True)  # an own ship type, so another name for the same id
    assert renamed.name != TARGET.name
    assert StandOnCoursePersistenceRule(renamed, constants()).rule_id == StandOnCoursePersistenceRule(TARGET, constants()).rule_id
