from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Iterator, Set

from logical_level.constraint_satisfaction.assignments import Assignments
from logical_level.constraint_satisfaction.evaluation_cache import EvaluationCache
from logical_level.models.penalty import Penalty


class RelationConstrComposite(ABC):
    # When True, Literal.penalty uses closed [lb, ub] (plus float tolerance) so holds()
    # matches the generator's intended intervals. The optimizer keeps EPSILON-shrunk
    # penalties so solutions sit inside the band.
    _closed_membership = False

    def __init__(self, components: Set["RelationConstrComposite"]):
        super().__init__()
        self.components: Set["RelationConstrComposite"] = components

    @classmethod
    @contextmanager
    def closed_membership(cls) -> Iterator[None]:
        previous = cls._closed_membership
        cls._closed_membership = True
        try:
            yield
        finally:
            cls._closed_membership = previous

    @abstractmethod
    def _evaluate_penalty(self, eval_cache: EvaluationCache) -> Penalty:
        pass

    def evaluate_penalty(self, assignments: Assignments) -> Penalty:
        cache = EvaluationCache(assignments)
        penalty = self._evaluate_penalty(cache)
        return penalty

    def holds(self, eval_cache: EvaluationCache) -> bool:
        with RelationConstrComposite.closed_membership():
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
