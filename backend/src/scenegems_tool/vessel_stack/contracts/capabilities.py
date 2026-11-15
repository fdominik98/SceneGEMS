"""Capability model shared by every adapter and layer spec.

Every field default means "this spec sets no limit", so a spec declares only what it
restricts, and the capabilities of a chain are the weakest link over its specs (of the
steering types: the ones every spec of the chain runs).
Measured values (tier, max speedup, environment support) are not written here or in the
specs: they live in vessel_stack/registry/measured_capabilities.yaml.
"""

import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, FrozenSet, Iterable, List, Optional

from logical_level.mapping.vessel_type import SteeringType


class RepeatabilityTier(str, Enum):
    EXACT = "exact"  # bit-identical across repeats
    BOUNDED = "bounded"  # repeats differ within a measured deviation bound
    NONE = "none"  # no repeatability claim (for example a human in the loop)


class EnvironmentSupport(str, Enum):
    SUPPORTED = "supported"
    UNMEASURED = "unmeasured"  # applied to the simulator, effect not confirmed by a measurement
    UNSUPPORTED = "unsupported"


_TIER_RANK = {RepeatabilityTier.NONE: 0, RepeatabilityTier.BOUNDED: 1, RepeatabilityTier.EXACT: 2}
_SUPPORT_RANK = {EnvironmentSupport.UNSUPPORTED: 0, EnvironmentSupport.UNMEASURED: 1, EnvironmentSupport.SUPPORTED: 2}
ALL_STEERING_TYPES: FrozenSet[SteeringType] = frozenset(SteeringType)


def weaker_tier(first: RepeatabilityTier, second: RepeatabilityTier) -> RepeatabilityTier:
    return first if _TIER_RANK[first] <= _TIER_RANK[second] else second


def weaker_support(first: EnvironmentSupport, second: EnvironmentSupport) -> EnvironmentSupport:
    return first if _SUPPORT_RANK[first] <= _SUPPORT_RANK[second] else second


@dataclass(frozen=True)
class Capabilities:
    faster_than_real_time: bool = True
    lockstep: bool = True
    repeatability_tier: RepeatabilityTier = RepeatabilityTier.EXACT
    # A bounded stack that was measured bit-identical up to this speedup.
    exact_up_to_speedup: Optional[float] = None
    wind: EnvironmentSupport = EnvironmentSupport.SUPPORTED
    waves: EnvironmentSupport = EnvironmentSupport.SUPPORTED
    # None: not measured yet. math.inf: the spec sets no speed limit of its own.
    max_speedup: Optional[float] = math.inf
    interactive_only: bool = False
    # The steering types (rudder, skid, vectored thrust) of the vessels the spec can run. A spec
    # that models no steering (the kinematic layer, a real vessel) runs them all.
    steering_types: FrozenSet[SteeringType] = ALL_STEERING_TYPES

    def __post_init__(self) -> None:
        object.__setattr__(self, "steering_types", frozenset(SteeringType(item) for item in self.steering_types))

    @property
    def speedup_limit(self) -> Optional[float]:
        """Highest usable speedup: 1 when the chain cannot run faster than real time, None when not measured."""
        if not self.faster_than_real_time:
            return 1.0
        return self.max_speedup

    def repeatability_at(self, speedup: float) -> RepeatabilityTier:
        if self.exact_up_to_speedup is not None and speedup <= self.exact_up_to_speedup:
            return RepeatabilityTier.EXACT
        return self.repeatability_tier

    def combine(self, other: "Capabilities") -> "Capabilities":
        """Weakest link of two specs on one chain."""
        tier = weaker_tier(self.repeatability_tier, other.repeatability_tier)
        exact_limit = min(self._exact_limit(), other._exact_limit())
        return Capabilities(
            faster_than_real_time=self.faster_than_real_time and other.faster_than_real_time,
            lockstep=self.lockstep and other.lockstep,
            repeatability_tier=tier,
            exact_up_to_speedup=exact_limit if tier != RepeatabilityTier.EXACT and exact_limit > 0 else None,
            wind=weaker_support(self.wind, other.wind),
            waves=weaker_support(self.waves, other.waves),
            max_speedup=None if self.max_speedup is None or other.max_speedup is None else min(self.max_speedup, other.max_speedup),
            interactive_only=self.interactive_only or other.interactive_only,
            steering_types=self.steering_types & other.steering_types,
        )

    def _exact_limit(self) -> float:
        if self.repeatability_tier == RepeatabilityTier.EXACT:
            return math.inf
        return self.exact_up_to_speedup if self.exact_up_to_speedup is not None else 0.0

    def as_dict(self) -> Dict[str, Any]:
        """Plain values: an enum as its value, the steering types as their values in the order of SteeringType."""
        data = {name: value.value if isinstance(value, Enum) else value for name, value in asdict(self).items()}
        data["steering_types"] = steering_type_values(self.steering_types)
        return data


def steering_type_values(steering_types: Iterable[SteeringType]) -> List[str]:
    """The values of a set of steering types, in the order of SteeringType."""
    chosen = set(steering_types)
    return [steering.value for steering in SteeringType if steering in chosen]


def steering_type_text(steering_types: Iterable[SteeringType]) -> str:
    """The steering types in words: "rudder, skid and vectored thrust"."""
    words = [value.replace("_", " ") for value in steering_type_values(steering_types)]
    if not words:
        return "no steering type"
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"


def weakest_link(capabilities: Iterable[Capabilities]) -> Capabilities:
    result = Capabilities()
    for item in capabilities:
        result = result.combine(item)
    return result
