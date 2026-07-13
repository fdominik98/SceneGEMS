from abc import ABC, abstractmethod
from typing import Set

from logical_level.constraint_satisfaction.assignments import Assignments
from logical_level.constraint_satisfaction.evaluation_cache import EvaluationCache
from logical_level.models.penalty import Penalty


class RelationConstrComposite(ABC):
    def __init__(self, components: Set["RelationConstrComposite"]):
        super().__init__()
        self.components: Set["RelationConstrComposite"] = components

    @abstractmethod
    def _evaluate_penalty(self, eval_cache: EvaluationCache) -> Penalty:
        pass

    def evaluate_penalty(self, assignments: Assignments) -> Penalty:
        cache = EvaluationCache(assignments)
        penalty = self._evaluate_penalty(cache)
        return penalty

    def holds(self, eval_cache: EvaluationCache) -> bool:
        return self._evaluate_penalty(eval_cache).is_zero


class RelationConstrTerm(RelationConstrComposite):
    def __init__(self, components: Set["RelationConstrComposite"] = set()):
        super().__init__(components)

    def _evaluate_penalty(self, eval_cache: EvaluationCache) -> Penalty:
        penalties = [comp._evaluate_penalty(eval_cache) for comp in self.components]
        sum_penalty = sum(penalties, Penalty(0, {}, {}))
        return Penalty(
            value=sum_penalty.value,
            actor_penalties=sum_penalty.actor_penalties,
            info=sum_penalty.info,
        )

    def __repr__(self) -> str:
        return f'({" ∧ ".join(f"{comp}" for comp in self.components)})'


class RelationConstrClause(RelationConstrComposite):
    def __init__(self, components: Set["RelationConstrComposite"] = set()):
        super().__init__(components)

    def _evaluate_penalty(self, eval_cache: EvaluationCache) -> Penalty:
        penalties = [comp._evaluate_penalty(eval_cache) for comp in self.components]
        sum_penalty = sum(penalties, Penalty(0, {}, {}))
        min_penalty = min(penalties)
        return Penalty(
            value=min_penalty.value,
            actor_penalties=min_penalty.actor_penalties,
            info=sum_penalty.info,
        )

    def __repr__(self) -> str:
        return f'({" ∨ ".join(f"{comp}" for comp in self.components)})'
