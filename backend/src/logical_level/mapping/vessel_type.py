"""
Ship types:
tanker, MMSI: 413474690 : 93 x 17 m
tanker, MMSI: 412377520 : 146 x 21 m
tanker, MMSI: 413441230 : 82 x 12 m
tanker, MMSI: 413697340 : 96 x 16 m

container, MMSI: 413146000 : 263 x 32 m
container, MMSI: 412713000 : 294 x 32 m
container, MMSI: 212602000 : 259 x 32 m

cargo vessel, MMSI: 413700110 : 159 x 23 m
cargo vessel, MMSI: 412766340 : 179 x 28 m

High Speed Craft, MMSI: 477937400 : 47 x 12 m
High Speed Craft, MMSI: 477937500 : 47 x 12 m
High Speed Craft, MMSI: 477937200 : 47 x 12 m
High Speed Craft, MMSI: 477525000 : 40 x 15 m
High Speed Craft, MMSI: 477385000 :	45 x 12 m

Passenger ship, MMSI: 477995974 : 25 x 8 m
Passenger ship, MMSI: 477995293 : 30 x 8 m

"""

import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import yaml

from utils.file_system_utils import VESSEL_TYPES_FOLDER


class SteeringType(str, Enum):
    """How a vessel turns.

    - rudder: a fixed propeller and a rudder behind it; the turning force grows with the speed.
    - skid: two fixed propellers side by side, steered by their thrust difference.
    - vectored_thrust: one propeller that turns with the helm (an outboard engine or an azimuth thruster).
    """

    RUDDER = "rudder"
    SKID = "skid"
    VECTORED_THRUST = "vectored_thrust"


# What a vessel type or a scene file without these columns gets: the hull every vessel had
# before the columns existed (skid steered, 0.4 L wide, 0.06 L deep, block coefficient 0.6).
DEFAULT_STEERING_TYPE = SteeringType.SKID.value
DEFAULT_BLOCK_COEFFICIENT = 0.6
DEFAULT_LENGTH_TO_BEAM = 2.5
DEFAULT_BEAM_TO_DRAFT = 0.4 / 0.06
HEIGHT_TO_DRAFT = 2.5  # hull height (keel to deck) over the draft


@dataclass(frozen=True, repr=False)
class VesselType:
    name: str
    min_length: float
    max_length: float
    min_beam: float
    max_beam: float
    max_speed: float
    max_angular_speed: float
    max_acceleration: float
    steering_type: str = DEFAULT_STEERING_TYPE
    block_coefficient: float = DEFAULT_BLOCK_COEFFICIENT  # displaced volume over length * breadth * draft
    length_to_beam: float = DEFAULT_LENGTH_TO_BEAM  # length over breadth
    beam_to_draft: float = DEFAULT_BEAM_TO_DRAFT  # breadth over draft

    def __post_init__(self):
        object.__setattr__(self, "steering_type", SteeringType(self.steering_type).value)
        if not 0.0 < self.block_coefficient <= 1.0:
            raise ValueError(f"vessel type {self.name}: block_coefficient must be in (0, 1], got {self.block_coefficient}")
        if self.length_to_beam <= 0 or self.beam_to_draft <= 0:
            raise ValueError(f"vessel type {self.name}: length_to_beam and beam_to_draft must be positive, got {self.length_to_beam} and {self.beam_to_draft}")

    def breadth_of(self, length: float) -> float:
        """Breadth of a vessel of this type and length: its hull ratio, within the type's beam range."""
        return min(max(length / self.length_to_beam, self.min_beam), self.max_beam)

    def draft_of(self, breadth: float) -> float:
        return breadth / self.beam_to_draft

    def __repr__(self):
        return self.name

    def __str__(self):
        return self.name


class VesselTypeMap(dict[Optional[str], VesselType]):
    def __init__(self, vessel_types_file: Optional[str] = None):
        super().__init__()
        if vessel_types_file is None:
            vessel_types_file_path = os.path.join(VESSEL_TYPES_FOLDER, "vessel_types.yaml")
            vessel_types_file = open(vessel_types_file_path, "r").read()

        self.load_vessel_types(vessel_types_file)

    def load_vessel_types(self, vessel_types_file: str):
        self.clear()
        vessel_types = yaml.safe_load(vessel_types_file) or {}
        for vessel_type_name, vessel_type_data in vessel_types.items():
            self[vessel_type_name] = VesselType(**{"name": vessel_type_name, **vessel_type_data})
        self[None] = self["UnspecifiedVesselType"]
