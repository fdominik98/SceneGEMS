from dataclasses import dataclass
import os
from typing import Optional

import yaml
from utils.file_system_utils import STATIC_OBSTACLE_TYPES_FOLDER
from utils.global_constants import EPSILON


@dataclass(frozen=True)
class StaticObstacleType:
    name: str
    min_radius: float
    max_radius: float

    def do_match(self, radius: float) -> bool:
        return self.min_radius - EPSILON <= radius <= self.max_radius + EPSILON

    def __repr__(self):
        return self.name

    def __str__(self):
        return self.name
    
    
class StaticObstacleTypeMap(dict[Optional[str], StaticObstacleType]):
    def __init__(self, obstacle_types_file: Optional[str] = None):
        super().__init__()
        if obstacle_types_file is None:
            obstacle_types_file_path = os.path.join(STATIC_OBSTACLE_TYPES_FOLDER, "static_obstacle_types.yaml")
            obstacle_types_file = open(obstacle_types_file_path, "r").read()
        
        self.load_obstacle_types(obstacle_types_file)
        
    def load_obstacle_types(self, obstacle_types_file: str):
        self.clear()
        obstacle_types = yaml.safe_load(obstacle_types_file) or {}
        for obstacle_type_name, obstacle_type_data in obstacle_types.items():
            self[obstacle_type_name] = StaticObstacleType(**{"name": obstacle_type_name, **obstacle_type_data})
        self[None] = self["UnspecifiedObstacleType"]
    