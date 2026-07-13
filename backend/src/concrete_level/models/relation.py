from __future__ import annotations

from typing import Tuple
from concrete_level.models.concrete_actors import ConcreteActor

class Relation(Tuple[ConcreteActor, ConcreteActor]):
    def __new__(cls, actor1: ConcreteActor, actor2: ConcreteActor):
        return super().__new__(cls, (actor1, actor2))

    def __str__(self) -> str:
        return f"{self[0].name} - {self[1].name}"

    def __repr__(self) -> str:
        return str(self)

    @property
    def actor1(self) -> ConcreteActor:
        return self[0]

    @property
    def actor2(self) -> ConcreteActor:
        return self[1]

    @staticmethod
    def canonical(actor1: ConcreteActor, actor2: ConcreteActor) -> Relation:
        if actor1.id <= actor2.id:
            return Relation(actor1, actor2)
        return Relation(actor2, actor1)
