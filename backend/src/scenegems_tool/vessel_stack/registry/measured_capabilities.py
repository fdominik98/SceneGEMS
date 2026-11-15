"""Loads measured_capabilities.yaml, the single data location for measured capability values."""

import dataclasses
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, Mapping, Optional, Tuple

import yaml

from logical_level.mapping.vessel_type import SteeringType
from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities, EnvironmentSupport, RepeatabilityTier

MEASURED_CAPABILITIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "measured_capabilities.yaml")


def _optional_float(value: Any) -> Optional[float]:
    return None if value is None else float(value)


def _steering_types(value: Any) -> FrozenSet[SteeringType]:
    """A list of steering types (rudder, skid, vectored_thrust); a single name is a list of one."""
    names = [value] if isinstance(value, str) else list(value or ())
    if not names:
        raise ValueError("steering_types must name at least one steering type")
    return frozenset(SteeringType(name) for name in names)


_CAPABILITY_PARSERS: Dict[str, Callable[[Any], Any]] = {
    "faster_than_real_time": bool,
    "lockstep": bool,
    "repeatability_tier": RepeatabilityTier,
    "exact_up_to_speedup": _optional_float,
    "wind": EnvironmentSupport,
    "waves": EnvironmentSupport,
    "max_speedup": _optional_float,
    "steering_types": _steering_types,
}
_RECORD_FIELDS = {"notes", "deviation_bounds_m", "deviation_bounds_m_by_layer", "host_max_speedup", "evidence"}


@dataclass(frozen=True)
class CapabilityMeasurement:
    spec_id: str
    overrides: Tuple[Tuple[str, Any], ...]  # (Capabilities field, measured value)
    notes: Tuple[Tuple[str, str], ...] = ()
    deviation_bounds_m: Tuple[Tuple[float, float], ...] = ()  # (speedup, max deviation in meters)
    # (simulation layer spec id, ((speedup, max deviation in meters), ...)) for an adapter measured on several chains.
    deviation_bounds_m_by_layer: Tuple[Tuple[str, Tuple[Tuple[float, float], ...]], ...] = ()
    # (host label, max speedup) for stacks whose pace depends on the machine; max_speedup stays null for them.
    host_max_speedup: Tuple[Tuple[str, float], ...] = ()
    evidence: str = ""

    def max_speedup_on(self, host: Optional[str]) -> Optional[float]:
        return dict(self.host_max_speedup).get(host) if host is not None else None

    def apply(self, capabilities: Capabilities) -> Capabilities:
        return dataclasses.replace(capabilities, **dict(self.overrides))


def parse_capability_measurement(spec_id: str, entry: Mapping[str, Any]) -> CapabilityMeasurement:
    unknown = set(entry) - set(_CAPABILITY_PARSERS) - _RECORD_FIELDS
    if unknown:
        raise ValueError(f"{spec_id}: unknown measured capability fields {sorted(unknown)}")
    overrides = tuple((name, parse(entry[name])) for name, parse in _CAPABILITY_PARSERS.items() if name in entry)
    notes = tuple((str(name), str(text)) for name, text in (entry.get("notes") or {}).items())
    bounds = _speedup_bounds(entry.get("deviation_bounds_m"))
    bounds_by_layer = tuple(sorted((str(layer_id), _speedup_bounds(layer_bounds)) for layer_id, layer_bounds in (entry.get("deviation_bounds_m_by_layer") or {}).items()))
    host_limits = tuple(sorted((str(host), float(limit)) for host, limit in (entry.get("host_max_speedup") or {}).items()))
    return CapabilityMeasurement(
        spec_id=spec_id,
        overrides=overrides,
        notes=notes,
        deviation_bounds_m=bounds,
        deviation_bounds_m_by_layer=bounds_by_layer,
        host_max_speedup=host_limits,
        evidence=str(entry.get("evidence", "")).strip(),
    )


def _speedup_bounds(entry: Optional[Mapping[Any, Any]]) -> Tuple[Tuple[float, float], ...]:
    return tuple(sorted((float(speedup), float(deviation)) for speedup, deviation in (entry or {}).items()))


def load_capability_measurements(path: str = MEASURED_CAPABILITIES_FILE) -> Dict[str, CapabilityMeasurement]:
    with open(path, encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    return {str(spec_id): parse_capability_measurement(str(spec_id), entry or {}) for spec_id, entry in data.items()}
