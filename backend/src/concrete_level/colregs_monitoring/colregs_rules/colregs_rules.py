from abc import ABC
from dataclasses import dataclass, field
from math import degrees

from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.relation import Relation
from utils.colregs_approximations import COLREGSConstraints

# Kinds of monitored item.
RULE_KIND = "rule"  # a normative COLREGS rule: a violation is a compliance failure
SUGGESTION_KIND = "suggestion"  # advisory guidance: not a formal rule, never counts as a failure


@dataclass(frozen=True, repr=False)
class COLREGSRule(ABC):
    """A single monitored COLREGS rule or advisory suggestion.

    The display text is assembled from structured parts so every rule is
    labelled consistently:

    - ``rule_number`` : the COLREGS rule number ("8", "16", "17"), or "" for a
      suggestion that is not tied to a numbered rule.
    - ``title`` : a short human-readable name in title case.
    - ``kind`` : ``RULE_KIND`` or ``SUGGESTION_KIND``.
    - ``subject_actor_id`` / ``subject_actor_name`` : the vessel the rule
      constrains. ``subject_actor_id`` is ``-1`` when the rule applies to the
      encounter as a whole rather than to one vessel.

    ``description`` is excluded from equality and hashing: it embeds
    configuration values (times, angles), so keeping it out of identity means a
    rule stays the same rule when the config changes.
    """

    relation: Relation
    rule_number: str
    title: str
    description: str = field(compare=False)
    kind: str = RULE_KIND
    subject_actor_id: int = -1
    subject_actor_name: str = field(default="", compare=False)

    @property
    def name(self) -> str:
        if self.kind == SUGGESTION_KIND:
            return f"Suggestion: {self.title}"
        return f"Rule {self.rule_number}: {self.title}"

    @property
    def is_suggestion(self) -> bool:
        return self.kind == SUGGESTION_KIND

    @property
    def scope(self) -> str:
        """Human label for what the rule constrains: one vessel or the encounter."""
        if self.subject_actor_name:
            return self.subject_actor_name
        return str(self.relation)

    def __str__(self) -> str:
        return f"{self.name} ({self.scope})"

    def __repr__(self) -> str:
        return str(self)


class GoAroundCollisionDomainSuggestion(COLREGSRule):
    def __init__(self, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(
            Relation(actor, actor),
            "",
            "Pass Around the Collision Domain",
            "Suggestion: alter course enough to pass around the other vessel's collision domain instead of steering through it.",
            SUGGESTION_KIND,
            actor.id,
            actor.name,
        )


class OverturningSuggestion(COLREGSRule):
    def __init__(self, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(
            Relation(actor, actor),
            "",
            "Avoid Turning Across the Other Vessel",
            "Suggestion: avoid a course change that turns across the other vessel's path; steer behind or well clear of it instead.",
            SUGGESTION_KIND,
            actor.id,
            actor.name,
        )


class PersistingCourseAfterCourseChangeRule(COLREGSRule):
    def __init__(self, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(
            Relation(actor, actor),
            "8",
            "Course Held After the Manoeuvre",
            "Once an avoidance course change is complete, the vessel should keep the changed heading and not drift back toward its original course.",
            RULE_KIND,
            actor.id,
            actor.name,
        )


class ReadilyApparentCourseChangeRule(COLREGSRule):
    def __init__(self, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(
            Relation(actor, actor),
            "8",
            "Readily Apparent Course Change",
            f"If a course change is used to avoid collision, it should be at least {degrees(colregs_constants.READILY_APPARENT_HEADING_CHANGE):.0f} deg "
            f"within {colregs_constants.READILY_APPARENT_COURSE_CHANGE_TIME} seconds so that it is readily apparent to the other vessel.",
            RULE_KIND,
            actor.id,
            actor.name,
        )


class ReadilyApparentCoursePersistenceRule(COLREGSRule):
    def __init__(self, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(
            Relation(actor, actor),
            "8",
            "Course Change Persistence",
            f"After a readily apparent course change, the new heading should be held for at least {colregs_constants.HEADING_PERSISTENCE_TIME} seconds.",
            RULE_KIND,
            actor.id,
            actor.name,
        )


class ReadilyApparentSpeedChangeRule(COLREGSRule):
    def __init__(self, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(
            Relation(actor, actor),
            "8",
            "Readily Apparent Speed Change",
            f"If a speed change is used to avoid collision, it should be at least {colregs_constants.READILY_APPARENT_SPEED_CHANGE} m/s "
            f"within {colregs_constants.READILY_APPARENT_COURSE_CHANGE_TIME} seconds so that it is readily apparent to the other vessel.",
            RULE_KIND,
            actor.id,
            actor.name,
        )


class SafeDistanceRule(COLREGSRule):
    def __init__(self, relation: Relation, colregs_constants: COLREGSConstraints):
        super().__init__(
            relation,
            "8",
            "Passing at a Safe Distance",
            "Action taken to avoid collision should result in the vessels passing at a safe distance, checked until the other vessel is finally past and clear.",
            RULE_KIND,
        )


class GiveWayEarlyActionRule(COLREGSRule):
    def __init__(self, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(
            Relation(actor, actor),
            "16",
            "Give-Way Vessel Takes Early and Substantial Action",
            "A vessel directed to keep out of the way of another should, so far as possible, take early and substantial action "
            f"(within about {colregs_constants.IMMEDIATE_HEADING_CHANGE_TIME} seconds) to keep well clear.",
            RULE_KIND,
            actor.id,
            actor.name,
        )


class StandOnCoursePersistenceRule(COLREGSRule):
    def __init__(self, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(
            Relation(actor, actor),
            "17",
            "Stand-On Vessel Keeps Course and Speed",
            "The stand-on vessel should keep her course and speed while the give-way vessel is expected to act, "
            "changing only when it is clear the give-way vessel is not taking appropriate action or collision cannot be avoided by her action alone.",
            RULE_KIND,
            actor.id,
            actor.name,
        )
