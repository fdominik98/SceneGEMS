import random
from typing import Dict, List

from functional_level.metamodels.functional_scenario import FunctionalScenario


class VesselTypeSampler:
    @staticmethod
    def sample(
        scenarios: List[FunctionalScenario],
        sample_size,
        distribution: Dict[str, float] = {},
    ) -> List[float]:
        random.shuffle(scenarios)
        # sized_distribution = {vessel_type : math.floor(percentage * sample_size / 100) for vessel_type, percentage in distribution.items()}
        result = [0.0, 0.0, 0.0]
        current_distribution = {vessel_type: 0 for vessel_type in distribution.keys()}
        for scenario in scenarios:
            if len(current_distribution) == 0:
                result[0] += len(scenario.overtaking_interpretation)
                result[1] += len(scenario.head_on_interpretation) / 2
                result[2] += len(scenario.crossing_from_port_interpretation)
            # else:
            #     for obj in scenario.concrete_scene.non_os:
            #         if obj.vessel_type in sized_distribution and current_distribution[obj.vessel_type] < sized_distribution[obj.vessel_type]:
            #             current_distribution[obj.vessel_type] += 1
            #             if scenario.overtaking(obj, None):
            #                 result[0] += 1
            #             elif scenario.head_on(obj, None):
            #                 result[1] += 1
            #             elif scenario.crossing(obj, None):
            #                 result[2] += 1
        # achieved_size = sum(current_distribution.values())
        # if sample_size != achieved_size:
        #     print(f'More sample is needed : >{sample_size - achieved_size}')
        # achieved_distribution = {vessel_type : size / achieved_size * 100 for vessel_type, size in current_distribution.items()}
        # print(achieved_distribution)
        return result
