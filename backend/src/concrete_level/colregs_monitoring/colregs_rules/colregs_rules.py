from abc import ABC
from dataclasses import dataclass
from math import degrees

from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.relation import Relation
from utils.colregs_approximations import COLREGSConstraints


@dataclass(frozen=True)
class COLREGSRule(ABC):
    relation: Relation
    name: str
    description: str

    def __str__(self) -> str:
        return f"{self.relation} - {self.name}"

    def __repr__(self) -> str:
        return str(self)

    def __hash__(self) -> int:
        return hash(str(self) + self.description)


class GoAroundCollisionDomainSuggestion(COLREGSRule):
    def __init__(self, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(Relation(actor, actor), "Go Around Collision Domain Suggestion", f"The vessel should go around the collision circle to avoid collision.")


class OverturningSuggestion(COLREGSRule):
    def __init__(self, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(Relation(actor, actor), "Overturning Suggestion", f"The vessel should go around the collision circle to avoid collision.")


class PersistingCourseAfterCourseChangeRule(COLREGSRule):
    def __init__(self, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(
            Relation(actor, actor),
            "Persisting Course After Course Change (Rule 8): Action to Avoid Collision: Action Must Be Readily Apparent",
            f"The changed heading should persist after the course change is finished.",
        )


class ReadilyApparentCourseChangeRule(COLREGSRule):
    def __init__(self, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(
            Relation(actor, actor),
            "Course Change (Rule 8): Action to Avoid Collision: Action Must Be Readily Apparent",
            f"Course change should be ≥ {degrees(colregs_constants.READILY_APPARENT_HEADING_CHANGE)}° within {colregs_constants.READILY_APPARENT_COURSE_CHANGE_TIME} seconds if taken.",
        )


class ReadilyApparentCoursePersistenceRule(COLREGSRule):
    def __init__(self, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(
            Relation(actor, actor),
            "Persisting Course (Rule 8): Action to Avoid Collision: Action Must Be Readily Apparent",
            f"The changed heading should persist for at least {colregs_constants.HEADING_PERSISTENCE_TIME} seconds.",
        )


class ReadilyApparentSpeedChangeRule(COLREGSRule):
    def __init__(self, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(
            Relation(actor, actor),
            "Speed Change (Rule 8): Action to Avoid Collision: Action Must Be Readily Apparent",
            f"Speed change should be ≥ {colregs_constants.READILY_APPARENT_SPEED_CHANGE}° within {colregs_constants.READILY_APPARENT_COURSE_CHANGE_TIME} seconds if taken.",
        )


class SafeDistanceRule(COLREGSRule):
    def __init__(self, relation: Relation, colregs_constants: COLREGSConstraints):
        super().__init__(relation, "Safe Distance (Rule 8): Action to Avoid Collision: Action Must Be Readily Apparent", f"The vessel should maintain a safe distance from the other vessel.")


class GiveWayEarlyActionRule(COLREGSRule):
    def __init__(self, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(
            Relation(actor, actor),
            "Rule 16: Action By Give-Way Vessel",
            f"Every vessel which is directed to keep out of the way of another vessel shall, so far as possible, take early and substantial action (in {colregs_constants.IMMEDIATE_HEADING_CHANGE_TIME} seconds) to keep well clear.",
        )


class StandOnCoursePersistenceRule(COLREGSRule):
    def __init__(self, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(
            Relation(actor, actor),
            "Rule 17: Action by Stand-on vessel",
            f"The vessel is to keep out of the way the other shall keep her course and speed unless collision is unavoidable by one vessel alone.",
        )
