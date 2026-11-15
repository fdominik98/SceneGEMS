"""The catalog of preset vessel models (backend/assets/domain_config/vessel_models/*.yaml).

A preset is a named set of vessel dynamics values for the generated Gazebo vessel model, taken
from a documented ship. It can be chosen for a vessel only when the vessel has the preset's
steering type and lies within its bounds: the vessel keeps its own dimensions and limits, and
the preset replaces the hull and steering assumptions it lists. Without a preset the model is
generated from the vessel alone.

Each file is a mapping of preset id to:

    name, source      text
    steering_type     rudder, skid or vectored_thrust
    particulars       the source ship's own numbers, for the record (not applied)
    bounds            [low, high] for length, breadth, draft, max_speed, max_angular_speed
    dynamics          vessel dynamics override keys to numbers (DynamicsAssumptions and VesselDynamics fields)
    notes             text, optional

Unknown keys, a wrong steering type, an empty or reversed bound, a non-numeric value and a
preset id defined twice all fail loudly.
"""

import functools
import glob
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

import yaml

from concrete_level.models.concrete_actors import ConcreteVessel
from logical_level.mapping.vessel_type import SteeringType
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import OVERRIDE_KEYS
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics_overrides import load_vessel_dynamics_overrides
from utils.file_system_utils import VESSEL_MODELS_FOLDER

BOUND_KEYS = ("length", "breadth", "draft", "max_speed", "max_angular_speed")
_BOUND_UNITS = {"length": "m", "breadth": "m", "draft": "m", "max_speed": "m/s", "max_angular_speed": "rad/s"}
_ENTRY_KEYS = frozenset({"name", "source", "steering_type", "particulars", "bounds", "dynamics", "notes"})
_REQUIRED_KEYS = ("name", "source", "steering_type", "bounds")


class UnknownVesselModelPreset(ValueError):
    pass


class VesselOutOfPresetBounds(ValueError):
    pass


@dataclass(frozen=True)
class VesselModelPreset:
    id: str
    name: str
    source: str
    steering_type: str
    bounds: Mapping[str, Tuple[float, float]]
    dynamics: Mapping[str, float] = field(default_factory=dict)
    particulars: Mapping[str, float] = field(default_factory=dict)
    notes: str = ""

    def mismatches(self, vessel: ConcreteVessel) -> List[str]:
        """Why the vessel cannot take this preset; empty when it can."""
        reasons = []
        if vessel.steering_type.value != self.steering_type:
            reasons.append(f"its steering type is {vessel.steering_type.value}, the preset's is {self.steering_type}")
        for key, (low, high) in self.bounds.items():
            value = float(getattr(vessel, key))
            if not low <= value <= high:
                reasons.append(f"its {key.replace('_', ' ')} of {value:g} {_BOUND_UNITS[key]} is outside {low:g} to {high:g} {_BOUND_UNITS[key]}")
        return reasons

    def fits(self, vessel: ConcreteVessel) -> bool:
        return not self.mismatches(vessel)

    def as_dict(self) -> Dict[str, Any]:
        """What the console shows of a preset."""
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "steeringType": self.steering_type,
            "bounds": {key: list(bound) for key, bound in self.bounds.items()},
            "particulars": dict(self.particulars),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class VesselModelCatalog:
    presets: Mapping[str, VesselModelPreset] = field(default_factory=dict)

    def get(self, preset_id: str) -> VesselModelPreset:
        if preset_id not in self.presets:
            raise UnknownVesselModelPreset(f"unknown vessel model preset {preset_id!r}; known presets: {sorted(self.presets)}")
        return self.presets[preset_id]

    def eligible(self, vessel: ConcreteVessel) -> List[VesselModelPreset]:
        """The presets the vessel can take, by id."""
        return [preset for _, preset in sorted(self.presets.items()) if preset.fits(vessel)]

    def dynamics_for(self, vessel: ConcreteVessel, preset_id: str) -> Dict[str, float]:
        """The preset's vessel dynamics values for a vessel within its bounds."""
        preset = self.get(preset_id)
        reasons = preset.mismatches(vessel)
        if reasons:
            raise VesselOutOfPresetBounds(f"vessel {vessel.id} ({vessel.type}) cannot take the vessel model preset {preset.id} ({preset.name}): {'; '.join(reasons)}")
        return dict(preset.dynamics)


def _number(where: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where} must be a number, got {value!r}")
    return float(value)


def _parse_bounds(where: str, bounds: Any) -> Dict[str, Tuple[float, float]]:
    if not isinstance(bounds, Mapping) or not bounds:
        raise ValueError(f"{where}: bounds must name at least one of {list(BOUND_KEYS)}")
    unknown = set(bounds) - set(BOUND_KEYS)
    if unknown:
        raise ValueError(f"{where}: unknown bounds {sorted(map(str, unknown))}; known bounds: {list(BOUND_KEYS)}")
    parsed = {}
    for key, bound in bounds.items():
        if not isinstance(bound, (list, tuple)) or len(bound) != 2:
            raise ValueError(f"{where}: the {key} bound must be [low, high], got {bound!r}")
        low, high = _number(f"{where}: the {key} bound's low", bound[0]), _number(f"{where}: the {key} bound's high", bound[1])
        if low > high:
            raise ValueError(f"{where}: the {key} bound's low {low:g} is above its high {high:g}")
        parsed[key] = (low, high)
    return parsed


def _parse_preset(where: str, preset_id: str, entry: Any) -> VesselModelPreset:
    if not isinstance(entry, Mapping):
        raise ValueError(f"{where}: expected a mapping with {sorted(_ENTRY_KEYS)}")
    unknown = set(entry) - _ENTRY_KEYS
    if unknown:
        raise ValueError(f"{where}: unknown keys {sorted(map(str, unknown))}; known keys: {sorted(_ENTRY_KEYS)}")
    missing = [key for key in _REQUIRED_KEYS if key not in entry]
    if missing:
        raise ValueError(f"{where}: missing {missing}")
    try:
        steering_type = SteeringType(entry["steering_type"]).value
    except ValueError:
        raise ValueError(f"{where}: steering_type must be one of {[steering.value for steering in SteeringType]}, got {entry['steering_type']!r}") from None
    dynamics = entry.get("dynamics") or {}
    if not isinstance(dynamics, Mapping):
        raise ValueError(f"{where}: dynamics must be a mapping of vessel dynamics keys to numbers")
    unknown_dynamics = set(dynamics) - OVERRIDE_KEYS
    if unknown_dynamics:
        raise ValueError(f"{where}: unknown vessel dynamics keys {sorted(map(str, unknown_dynamics))}; known keys: {sorted(OVERRIDE_KEYS)}")
    particulars = entry.get("particulars") or {}
    if not isinstance(particulars, Mapping):
        raise ValueError(f"{where}: particulars must be a mapping of names to numbers")
    return VesselModelPreset(
        id=preset_id,
        name=str(entry["name"]),
        source=str(entry["source"]),
        steering_type=steering_type,
        bounds=_parse_bounds(where, entry["bounds"]),
        dynamics={str(key): _number(f"{where}: dynamics {key}", value) for key, value in dynamics.items()},
        particulars={str(key): _number(f"{where}: particulars {key}", value) for key, value in particulars.items()},
        notes=str(entry.get("notes") or ""),
    )


def read_vessel_model_catalog(folder: str) -> VesselModelCatalog:
    presets: Dict[str, VesselModelPreset] = {}
    for path in sorted(glob.glob(os.path.join(folder, "*.yaml"))):
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
        if not isinstance(data, Mapping):
            raise ValueError(f"{name}: expected a mapping of preset id to preset")
        for preset_id, entry in data.items():
            preset_id = str(preset_id)
            if preset_id in presets:
                raise ValueError(f"{name}: the vessel model preset {preset_id} is already defined in another file")
            presets[preset_id] = _parse_preset(f"{name}: {preset_id}", preset_id, entry)
    return VesselModelCatalog(presets)


@functools.lru_cache(maxsize=1)
def load_vessel_model_catalog() -> VesselModelCatalog:
    """The shipped catalog; read once per process."""
    return read_vessel_model_catalog(VESSEL_MODELS_FOLDER)


def vessel_dynamics_overrides(vessel: ConcreteVessel, preset_id: Optional[str] = None, catalog: Optional[VesselModelCatalog] = None) -> Dict[str, float]:
    """The vessel dynamics overrides of a vessel: the override files' entries for it, and on top a chosen preset's values.

    Raises UnknownVesselModelPreset or VesselOutOfPresetBounds for a preset the vessel cannot take.
    """
    overrides = load_vessel_dynamics_overrides().for_vessel(vessel)
    if preset_id is not None:
        overrides.update((catalog or load_vessel_model_catalog()).dynamics_for(vessel, preset_id))
    return overrides
