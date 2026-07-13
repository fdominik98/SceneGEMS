import json
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from logical_level.models.actor_variable import ActorVariable


@dataclass(frozen=True)
class Penalty:
    value: float
    actor_penalties: Dict[ActorVariable, float]
    info: Dict[Tuple[ActorVariable, ActorVariable], List[str]]

    def __add__(self, other):
        if not isinstance(other, Penalty):
            return NotImplemented

        new_actor_penalties = self.actor_penalties.copy()  # Start with a copy of dict1
        for var, value in other.actor_penalties.items():
            if var in new_actor_penalties:
                new_actor_penalties[var] += value  # Add values for keys present in both
            else:
                new_actor_penalties[var] = value  # Add new key-value pairs

        merged_infos = {key: self.info.get(key, []) + other.info.get(key, []) for key in set(self.info) | set(other.info)}

        return Penalty(
            value=self.value + other.value,
            actor_penalties=new_actor_penalties,
            info=merged_infos,
        )

    def __eq__(self, other):
        if isinstance(other, Penalty):
            return self.value == other.value
        return NotImplemented

    def __lt__(self, other):
        if isinstance(other, Penalty):
            return self.value < other.value
        return NotImplemented

    def __le__(self, other):
        return self == other or self < other

    def __repr__(self):
        return self.pretty_info()

    @property
    def is_zero(self) -> bool:
        return self.value == 0.0

    def pretty_info(self, actors: Optional[Tuple[ActorVariable, ActorVariable]] = None) -> str:
        if actors is None:
            return "\n".join([f"{key[0].name} → {key[1].name} : {json.dumps(value, indent=3)}" for key, value in self.info.items()])
        if actors not in self.info:
            return ""
        return json.dumps(self.info[actors], indent=3)
