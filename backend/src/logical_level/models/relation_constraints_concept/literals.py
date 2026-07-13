from abc import ABC, abstractmethod

import numpy as np

from logical_level.constraint_satisfaction.evaluation_cache import EvaluationCache, GeometricProperties
from logical_level.models.actor_variable import ActorVariable
from logical_level.models.penalty import Penalty
from logical_level.models.relation_constraints_concept.composites import RelationConstrComposite
from logical_level.models.values import ActorValues
from utils.colregs_approximations import COLREGSConstraints
from utils.global_constants import BEAM_ROTATION_ANGLE, EPSILON, HALF_BOW_ANGLE, HALF_SIDE_ANGLE, MAX_DISTANCE, MAX_TEMPORAL_DISTANCE, SIDE_ANGLE


class Literal(RelationConstrComposite, ABC):
    def __init__(self, literal_type: str, max_dist, negated):
        super().__init__(components=set())
        self.literal_type = literal_type
        self.max_dist = max_dist
        self.negated = negated

    @property
    def name(self):
        prefix = "!" if self.negated else ""
        return prefix + self.literal_type

    @abstractmethod
    def _evaluate_penalty(self, eval_cache: EvaluationCache) -> Penalty:
        pass

    @abstractmethod
    def _penalty_value(self, eval_cache: EvaluationCache) -> float:
        pass

    def holds(self, eval_cache: EvaluationCache) -> bool:
        return self._penalty_value(eval_cache) == 0.0

    def penalty(self, val, lb, ub) -> float:
        if not self.negated:
            dist = self._penalty(val, lb + EPSILON, ub - EPSILON)
            return self._normalize(dist, lb, ub)
        else:
            dist1 = self._penalty(val, 0 + EPSILON, lb - EPSILON)
            dist2 = self._penalty(val, ub + EPSILON, self.max_dist - EPSILON)
            return min(self._normalize(dist1, 0, lb), self._normalize(dist2, ub, self.max_dist))

    def _penalty(self, val, lb, ub):
        if val < lb:
            distance = lb - val
        elif val > ub:
            distance = val - ub
        else:
            return 0.0
        return min(max(0.0, distance), self.max_dist)

    def _normalize(self, dist, lb, ub) -> float:
        denom = max(lb, self.max_dist - ub)
        if denom == 0:
            return 0.0  # Avoid division by zero
        normalized = dist / denom
        # Clamp normalized value to [0.0, 1.0]
        return min(max(0.0, normalized), 1.0)


class BinaryLiteral(Literal, ABC):
    def __init__(
        self,
        var1: ActorVariable,
        var2: ActorVariable,
        literal_type,
        max_penalty,
        negated,
    ):
        super().__init__(literal_type, max_penalty, negated)
        self.var1: ActorVariable = var1
        self.var2: ActorVariable = var2

    def _evaluate_penalty(self, eval_cache: EvaluationCache) -> Penalty:
        penalty_value = self._penalty_value(eval_cache)
        return Penalty(
            value=penalty_value,
            actor_penalties={self.var1: penalty_value, self.var2: penalty_value},
            info={(self.var1, self.var2): [rf"{self.name}({self.var1, self.var2})={penalty_value}"]},
        )

    def _penalty_value(self, eval_cache: EvaluationCache) -> float:
        return self._do_evaluate_penalty(eval_cache.get_props(self.var1, self.var2))

    @abstractmethod
    def _do_evaluate_penalty(self, geo_props: GeometricProperties) -> float:
        pass

    def __repr__(self) -> str:
        return f"{self.name}({self.var1}, {self.var2})"


class UnaryLiteral(Literal, ABC):
    def __init__(self, var: ActorVariable, literal_type, max_penalty, negated):
        super().__init__(literal_type, max_penalty, negated)
        self.var: ActorVariable = var

    def _evaluate_penalty(self, eval_cache: EvaluationCache) -> Penalty:
        penalty_value = self._penalty_value(eval_cache)
        return Penalty(
            value=penalty_value,
            actor_penalties={self.var: penalty_value},
            info={(self.var, self.var): [rf"{self.name}({self.var}) : {penalty_value}"]},
        )

    def _penalty_value(self, eval_cache: EvaluationCache) -> float:
        values = eval_cache.assignments[self.var]
        return self._do_evaluate_penalty(values)

    @abstractmethod
    def _do_evaluate_penalty(self, value: ActorValues) -> float:
        pass

    def __repr__(self) -> str:
        return f"{self.name}({self.var})"


# ############ VISIBILITY DISTANCE ##################
class AtVis(BinaryLiteral):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, negated: bool = False):
        super().__init__(var1, var2, "AtVis", MAX_DISTANCE, negated)

    def _do_evaluate_penalty(self, geo_props: GeometricProperties) -> float:
        return self.penalty(
            geo_props.o_distance,
            geo_props.vis_distance - geo_props.drift_threshold,
            geo_props.vis_distance + geo_props.drift_threshold,
        )


class InVis(BinaryLiteral):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, negated: bool = False):
        super().__init__(var1, var2, "InVis", MAX_DISTANCE, negated)

    def _do_evaluate_penalty(self, geo_props: GeometricProperties) -> float:
        return self.penalty(geo_props.o_distance, 0, geo_props.vis_distance - geo_props.drift_threshold)


class OutVis(BinaryLiteral):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, negated: bool = False):
        super().__init__(var1, var2, "OutVis", MAX_DISTANCE, negated)

    def _do_evaluate_penalty(self, geo_props: GeometricProperties) -> float:
        return self.penalty(
            geo_props.o_distance,
            geo_props.vis_distance + geo_props.drift_threshold,
            MAX_DISTANCE,
        )


# ############ RELATIVE BEARING ##################
class InBeamSectorOf(BinaryLiteral, ABC):
    def __init__(
        self,
        var1: ActorVariable,
        var2: ActorVariable,
        literal_type: str,
        rotation_angle: float,
        negated: bool = False,
    ):
        super().__init__(var1, var2, literal_type, np.pi, negated)
        self.rotation_matrix = np.array(
            [
                [np.cos(rotation_angle), -np.sin(rotation_angle)],
                [np.sin(rotation_angle), np.cos(rotation_angle)],
            ]
        )

    def __rotated_v2(self, geo_props: GeometricProperties):
        return np.dot(self.rotation_matrix, geo_props.val2.v)

    def _do_evaluate_penalty(self, geo_props: GeometricProperties) -> float:
        angle_p21_v2_rot = np.arccos(np.dot(geo_props.p21, self.__rotated_v2(geo_props)) / max(geo_props.o_distance, EPSILON) / max(geo_props.val2.sp, EPSILON))
        return self.penalty(angle_p21_v2_rot, 0.0, HALF_SIDE_ANGLE)


class InPortSideSectorOf(InBeamSectorOf):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, negated: bool = False):
        super().__init__(var1, var2, "InPortSectorOf", BEAM_ROTATION_ANGLE, negated)


class InStarboardSideSectorOf(InBeamSectorOf):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, negated: bool = False):
        super().__init__(
            var1,
            var2,
            "InStarboardSectorOf",
            -BEAM_ROTATION_ANGLE,
            negated,
        )


class InBowSectorOf(BinaryLiteral):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, negated: bool = False):
        super().__init__(var1, var2, "InBowSectorOf", np.pi, negated)

    def _do_evaluate_penalty(self, geo_props: GeometricProperties) -> float:
        return self.penalty(
            geo_props.angle_p21_v2,
            0.0,
            max(geo_props.angle_half_col_cone, HALF_BOW_ANGLE),
        )


class InSternSectorOf(BinaryLiteral):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, negated: bool = False):
        super().__init__(var1, var2, "InSternSectorOf", np.pi, negated)

    def _do_evaluate_penalty(self, geo_props: GeometricProperties) -> float:
        return self.penalty(geo_props.angle_p21_v2, SIDE_ANGLE, np.pi)


# ############ MAY COLLISION ##################
class OnCollisionCourse(BinaryLiteral):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, negated: bool = False):
        super().__init__(var1, var2, "OnCollisionCourse", MAX_DISTANCE, negated)

    def _do_evaluate_penalty(self, geo_props: GeometricProperties) -> float:
        return self.penalty(geo_props.dcpa, 0, geo_props.safety_dist)


class LowTCPA(BinaryLiteral):
    def __init__(self, var1: ActorVariable, var2: ActorVariable, colregs_constants : COLREGSConstraints, negated: bool = False):
        self.colregs_constants = colregs_constants
        super().__init__(var1, var2, "LowTCPA", MAX_TEMPORAL_DISTANCE, negated)

    def _do_evaluate_penalty(self, geo_props: GeometricProperties) -> float:
        return self.penalty(geo_props.tcpa, 0, self.colregs_constants.SAFE_TEMPORAL_DISTANCE)
