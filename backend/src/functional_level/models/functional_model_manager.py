from typing import List

from functional_level.metamodels.functional_scenario import FunctionalScenario
from functional_level.models.model_parser import ModelParser


class FunctionalModelManager:
    __scenario_cache_map = {
        (2, 0): None,
        (2, 1): None,
        (3, 0): None,
        (3, 1): None,
        (4, 0): None,
        (5, 0): None,
        (6, 0): None,
    }

    __ambiguous_scenario_cache_map = {
        (2, 0): None,
        (2, 1): None,
        (3, 0): None,
        (3, 1): None,
        (4, 0): None,
        (5, 0): None,
        (6, 0): None,
    }

    @classmethod
    def get_x_vessel_y_obstacle_ambiguous_scenarios(cls, vessel_number: int, obstacle_number: int) -> List[FunctionalScenario]:
        actor_number_by_type = (vessel_number, obstacle_number)
        if cls.__ambiguous_scenario_cache_map[actor_number_by_type] is None:
            cls.__ambiguous_scenario_cache_map[actor_number_by_type] = ModelParser.load_ambiguous_functional_scenarios(vessel_number, obstacle_number)
        return cls.__ambiguous_scenario_cache_map[actor_number_by_type]

    @classmethod
    def get_x_vessel_y_obstacle_scenarios(cls, vessel_number: int, obstacle_number: int) -> List[FunctionalScenario]:
        actor_number_by_type = (vessel_number, obstacle_number)
        if cls.__scenario_cache_map[actor_number_by_type] is None:
            cls.__scenario_cache_map[actor_number_by_type] = ModelParser.load_functional_scenarios(vessel_number, obstacle_number)
        return cls.__scenario_cache_map[actor_number_by_type]
