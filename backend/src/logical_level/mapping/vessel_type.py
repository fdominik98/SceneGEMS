

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

from dataclasses import dataclass
import os
from typing import Optional

import yaml

from utils.file_system_utils import VESSEL_TYPES_FOLDER
from utils.global_constants import EPSILON


@dataclass(frozen=True, repr=False)
class VesselType():
    name: str
    min_length: float
    max_length: float
    min_beam: float
    max_beam: float
    max_speed: float
    max_angular_speed: float
    max_acceleration: float

    def do_match(self, length: float, speed: float, beam=None) -> bool:
        return (
            self.min_length - EPSILON <= length <= self.max_length + EPSILON
            and EPSILON <= speed <= self.max_speed + EPSILON
            and (beam is None or self.min_beam - EPSILON <= beam <= self.max_beam + EPSILON)
        )

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