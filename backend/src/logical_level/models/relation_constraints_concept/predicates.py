from typing import Set

from logical_level.constraint_satisfaction.evaluation_cache import EvaluationCache
from logical_level.models.actor_variable import ActorVariable, StaticObstacleVariable
from logical_level.models.penalty import Penalty
from logical_level.models.relation_constraints_concept.composites import RelationConstrClause, RelationConstrComposite, RelationConstrTerm
from logical_level.models.relation_constraints_concept.literals import AtVis, InBowSectorOf, InPortSideSectorOf, InStarboardSideSectorOf, InSternSectorOf, InVis, LowTCPA, OnCollisionCourse, OutVis
from utils.colregs_approximations import COLREGSConstraints


class BinaryPredicate(RelationConstrTerm):
    def __init__(
        self,
        name: str,
        var1: ActorVariable,
        var2: ActorVariable,
        components: Set[RelationConstrComposite],
    ):
        super().__init__(components)
        self.name = name
        self.var1: ActorVariable = var1
        self.var2: ActorVariable = var2

    def __str__(self) -> str:
        return f"{self.name}({self.var1}, {self.var2})"

    def __repr__(self) -> str:
        return str(self)

    def _evaluate_penalty(self, eval_cache: EvaluationCache) -> Penalty:
        penalty = super()._evaluate_penalty(eval_cache)
        return Penalty(
            value=penalty.value,
            actor_penalties=penalty.actor_penalties,
            info={(self.var1, self.var2): [f"{str(self)}={penalty.value} : {penalty.info.get((self.var1, self.var2), [])}"]},
        )


class NotInBowSectorOf(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable):
        super().__init__("!InBowSectorOf", var1, var2, {InBowSectorOf(var1, var2, negated=True)})


class AtVisAndMayCollideSoon(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "AtVisAndMayCollideSoon",
            var1,
            var2,
            {OnCollisionCourse(var1, var2), LowTCPA(var1, var2, colregs_constants), AtVis(var1, var2)},
        )


class InVisAndMayCollideSoon(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "InVisAndMayCollideSoon",
            var1,
            var2,
            {OnCollisionCourse(var1, var2), LowTCPA(var1, var2, colregs_constants), InVis(var1, var2)},
        )


class NotOutVisAndMayCollideSoon(BinaryPredicate):
    """Collision risk while not out of visibility: inside visibility or at its boundary band.

    The union of the `AtVis` band the scene generator places encounters in and the
    `InVis` region, so an encounter can be recognised at the moment it begins.
    """

    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "NotOutVisAndMayCollideSoon",
            var1,
            var2,
            {OnCollisionCourse(var1, var2), LowTCPA(var1, var2, colregs_constants), OutVis(var1, var2, negated=True)},
        )


class MayCollideSoon(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__("MayCollideSoon", var1, var2, {OnCollisionCourse(var1, var2), LowTCPA(var1, var2, colregs_constants)})


class AtVisAndMayCollide(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "AtVisAndMayCollide",
            var1,
            var2,
            {OnCollisionCourse(var1, var2), AtVis(var1, var2)},
        )


class OutVisOrMayNotCollide(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "OutVisOrMayNotCollide",
            var1,
            var2,
            {
                RelationConstrClause({OnCollisionCourse(var1, var2, negated=True), OutVis(var1, var2)}),
            },
        )


class InMastheadSectorOf(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "InMastheadSectorOf",
            var1,
            var2,
            {
                RelationConstrClause(
                    {
                        InPortSideSectorOf(var1, var2),
                        InStarboardSideSectorOf(var1, var2),
                    }
                ),
            },
        )


class HeadOn(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "HeadOn",
            var1,
            var2,
            {
                InBowSectorOf(var1, var2),
                InBowSectorOf(var2, var1),
            },
        )


class CrossingFromPort(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        not_in_mutual_head_on_sector = RelationConstrClause(
            {
                InBowSectorOf(var1, var2, negated=True),
                InBowSectorOf(var2, var1, negated=True),
            }
        )
        super().__init__(
            "CrossingFromPort",
            var1,
            var2,
            {
                InPortSideSectorOf(var1, var2),
                InStarboardSideSectorOf(var2, var1),
                not_in_mutual_head_on_sector,
            },
        )


class OvertakingToPort(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "OvertakingToPort",
            var1,
            var2,
            {
                InSternSectorOf(var1, var2),
                InPortSideSectorOf(var2, var1),
            },
        )


class OvertakingToStarboard(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "OvertakingToStarboard",
            var1,
            var2,
            {
                InSternSectorOf(var1, var2),
                InStarboardSideSectorOf(var2, var1),
            },
        )


class TwoWayCrossingFromPort(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "TwoWayCrossingFromPort",
            var1,
            var2,
            {
                InPortSideSectorOf(var1, var2),
                InPortSideSectorOf(var2, var1),
            },
        )


class TwoWayCrossingFromStarboard(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "TwoWayCrossingFromStarboard",
            var1,
            var2,
            {
                InStarboardSideSectorOf(var1, var2),
                InStarboardSideSectorOf(var2, var1),
            },
        )


class AtHeadOnCR(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "AtHeadOnCR",
            var1,
            var2,
            {
                HeadOn(var1, var2, colregs_constants),
                AtVisAndMayCollideSoon(var1, var2, colregs_constants),
            },
        )


class AtCrossingFromPortCR(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "AtCrossingFromPortCR",
            var1,
            var2,
            {
                CrossingFromPort(var1, var2, colregs_constants),
                AtVisAndMayCollideSoon(var1, var2, colregs_constants),
            },
        )


class AtOvertakingToPortCR(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "AtOvertakingToPortCR",
            var1,
            var2,
            {
                OvertakingToPort(var1, var2, colregs_constants),
                AtVisAndMayCollideSoon(var1, var2, colregs_constants),
            },
        )


class AtOvertakingToStarboardCR(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "AtOvertakingToStarboardCR",
            var1,
            var2,
            {
                OvertakingToStarboard(var1, var2, colregs_constants),
                AtVisAndMayCollideSoon(var1, var2, colregs_constants),
            },
        )


class AtTwoWayCrossingFromPortCR(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "AtTwoWayCrossingFromPortCR",
            var1,
            var2,
            {
                TwoWayCrossingFromPort(var1, var2, colregs_constants),
                AtVisAndMayCollideSoon(var1, var2, colregs_constants),
            },
        )


class AtTwoWayCrossingFromStarboardCR(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "AtTwoWayCrossingFromStarboardCR",
            var1,
            var2,
            {
                TwoWayCrossingFromStarboard(var1, var2, colregs_constants),
                AtVisAndMayCollideSoon(var1, var2, colregs_constants),
            },
        )


class AtDangerousHeadOnSectorOfCR(BinaryPredicate):
    def __init__(self, var1: StaticObstacleVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "AtDangerousHeadOnSectorOfCR",
            var1,
            var2,
            {InBowSectorOf(var1, var2), AtVisAndMayCollideSoon(var1, var2, colregs_constants)},
        )


class InHeadOnCR(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "InHeadOnCR",
            var1,
            var2,
            {
                HeadOn(var1, var2, colregs_constants),
                InVisAndMayCollideSoon(var1, var2, colregs_constants),
            },
        )


class InCrossingFromPortCR(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "InCrossingFromPortCR",
            var1,
            var2,
            {
                CrossingFromPort(var1, var2, colregs_constants),
                InVisAndMayCollideSoon(var1, var2, colregs_constants),
            },
        )


class InOvertakingToPortCR(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "InOvertakingToPortCR",
            var1,
            var2,
            {
                OvertakingToPort(var1, var2, colregs_constants),
                InVisAndMayCollideSoon(var1, var2, colregs_constants),
            },
        )


class InOvertakingToStarboardCR(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "InOvertakingToStarboardCR",
            var1,
            var2,
            {
                OvertakingToStarboard(var1, var2, colregs_constants),
                InVisAndMayCollideSoon(var1, var2, colregs_constants),
            },
        )


class InTwoWayCrossingFromPortCR(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "InTwoWayCrossingFromPortCR",
            var1,
            var2,
            {
                TwoWayCrossingFromPort(var1, var2, colregs_constants),
                InVisAndMayCollideSoon(var1, var2, colregs_constants),
            },
        )


class InTwoWayCrossingFromStarboardCR(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "InTwoWayCrossingFromStarboardCR",
            var1,
            var2,
            {
                TwoWayCrossingFromStarboard(var1, var2, colregs_constants),
                InVisAndMayCollideSoon(var1, var2, colregs_constants),
            },
        )


class InDangerousHeadOnSectorOfCR(BinaryPredicate):
    def __init__(self, var1: StaticObstacleVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "InDangerousHeadOnSectorOfCR",
            var1,
            var2,
            {InBowSectorOf(var1, var2), InVisAndMayCollideSoon(var1, var2, colregs_constants)},
        )


# The AtOrIn*CR predicates accept the encounter geometry anywhere from the visibility
# boundary inwards. The monitor uses them to classify an initial scene, which the
# scene generator builds with the vessels at the visibility boundary (At*CR).


class AtOrInHeadOnCR(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "AtOrInHeadOnCR",
            var1,
            var2,
            {
                HeadOn(var1, var2, colregs_constants),
                NotOutVisAndMayCollideSoon(var1, var2, colregs_constants),
            },
        )


class AtOrInCrossingFromPortCR(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "AtOrInCrossingFromPortCR",
            var1,
            var2,
            {
                CrossingFromPort(var1, var2, colregs_constants),
                NotOutVisAndMayCollideSoon(var1, var2, colregs_constants),
            },
        )


class AtOrInOvertakingToPortCR(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "AtOrInOvertakingToPortCR",
            var1,
            var2,
            {
                OvertakingToPort(var1, var2, colregs_constants),
                NotOutVisAndMayCollideSoon(var1, var2, colregs_constants),
            },
        )


class AtOrInOvertakingToStarboardCR(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "AtOrInOvertakingToStarboardCR",
            var1,
            var2,
            {
                OvertakingToStarboard(var1, var2, colregs_constants),
                NotOutVisAndMayCollideSoon(var1, var2, colregs_constants),
            },
        )


class AtOrInTwoWayCrossingFromPortCR(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "AtOrInTwoWayCrossingFromPortCR",
            var1,
            var2,
            {
                TwoWayCrossingFromPort(var1, var2, colregs_constants),
                NotOutVisAndMayCollideSoon(var1, var2, colregs_constants),
            },
        )


class AtOrInTwoWayCrossingFromStarboardCR(BinaryPredicate):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants: COLREGSConstraints):
        super().__init__(
            "AtOrInTwoWayCrossingFromStarboardCR",
            var1,
            var2,
            {
                TwoWayCrossingFromStarboard(var1, var2, colregs_constants),
                NotOutVisAndMayCollideSoon(var1, var2, colregs_constants),
            },
        )
