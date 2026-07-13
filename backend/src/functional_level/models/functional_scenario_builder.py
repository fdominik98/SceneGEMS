from typing import Dict

from functional_level.metamodels.functional_object import FuncObject
from functional_level.metamodels.functional_scenario import FunctionalScenario
from functional_level.metamodels.interpretation import (
    OSInterpretation,
    StaticObstacleInterpretation,
    StaticObstacleTypeInterpretation,
    TSInterpretation,
    VesselTypeInterpretation,
    atVisibilityDistanceInterpretation,
    inBowSectorOfInterpretation,
    inPortSideSectorOfInterpretation,
    inStarboardSideSectorOfInterpretation,
    inSternSectorOfInterpretation,
    inVisibilityDistanceInterpretation,
    mayCollideInterpretation,
    outVisibilityDistanceInterpretation,
    staticObstacleTypeInterpretation,
    vesselTypeInterpretation,
)
from functional_level.models.object_generator import ObjectGenerator

class FunctionalScenarioBuilder:
    def __init__(self):
        self.OS_interpretation = OSInterpretation()
        self.TS_interpretation = TSInterpretation()
        self.Static_obstacle_interpretation = StaticObstacleInterpretation()
        self.Vessel_type_interpretation = VesselTypeInterpretation()
        self.Static_obstacle_type_interpretation = StaticObstacleTypeInterpretation()

        self.out_visibility_distance_interpretation = outVisibilityDistanceInterpretation()
        self.at_visibility_distance_interpretation = atVisibilityDistanceInterpretation()
        self.in_visibility_distance_interpretation = inVisibilityDistanceInterpretation()

        self.may_collide_interpretation = mayCollideInterpretation()

        self.in_bow_sector_of_interpretation = inBowSectorOfInterpretation()
        self.in_port_side_sector_of_interpretation = inPortSideSectorOfInterpretation()
        self.in_starboard_side_sector_of_interpretation = inStarboardSideSectorOfInterpretation()
        self.in_stern_sector_of_interpretation = inSternSectorOfInterpretation()

        self.vessel_type_interpretation = vesselTypeInterpretation()
        self.static_obstacle_type_interpretation = staticObstacleTypeInterpretation()

        self.object_generator = ObjectGenerator()
        self.objects: Dict[str, FuncObject] = dict()

    def add_new_vessel_type(self, name: str, id=None) -> FuncObject:
        obj = self.object_generator.new_vessel_type(id)
        self.objects[name] = obj
        self.Vessel_type_interpretation.add(obj, name)
        return obj

    def add_new_obstacle_type(self, name: str, id=None) -> FuncObject:
        obj = self.object_generator.new_obstacle_type(id)
        self.objects[name] = obj
        self.Static_obstacle_type_interpretation.add(obj, name)
        return obj

    def add_new_os(self, obj_name: str, id=None) -> FuncObject:
        self.objects[obj_name] = self.object_generator.new_os(id)
        self.OS_interpretation.add(self.objects[obj_name])
        return self.objects[obj_name]

    def add_new_ts(self, obj_name: str, id=None) -> FuncObject:
        self.objects[obj_name] = self.object_generator.new_ts(id)
        self.TS_interpretation.add(self.objects[obj_name])
        return self.objects[obj_name]

    def add_new_obstacle(self, obj_name: str, id=None) -> FuncObject:
        self.objects[obj_name] = self.object_generator.new_obstacle(id)
        self.Static_obstacle_interpretation.add(self.objects[obj_name])
        return self.objects[obj_name]

    def add_at_visibility_distance_and_may_collide(self, o1, o2):
        self.at_visibility_distance_interpretation.add(o1, o2)
        self.may_collide_interpretation.add(o1, o2)

    def add_head_on(self, o1, o2):
        self.in_bow_sector_of_interpretation.add(o1, o2)
        self.in_bow_sector_of_interpretation.add(o2, o1)
        self.add_at_visibility_distance_and_may_collide(o1, o2)

    def add_overtaking_to_port(self, o1, o2):
        self.in_stern_sector_of_interpretation.add(o1, o2)
        self.in_port_side_sector_of_interpretation.add(o2, o1)
        self.add_at_visibility_distance_and_may_collide(o1, o2)

    def add_overtaking_to_starboard(self, o1, o2):
        self.in_stern_sector_of_interpretation.add(o1, o2)
        self.in_starboard_side_sector_of_interpretation.add(o2, o1)
        self.add_at_visibility_distance_and_may_collide(o1, o2)

    def add_crossing_from_port(self, o1, o2):
        self.in_port_side_sector_of_interpretation.add(o1, o2)
        self.in_starboard_side_sector_of_interpretation.add(o2, o1)
        self.add_at_visibility_distance_and_may_collide(o1, o2)

    def add_at_dangerous_head_on_sector_of(self, o1, o2):
        self.in_bow_sector_of_interpretation.add(o1, o2)
        self.add_at_visibility_distance_and_may_collide(o1, o2)

    def add_vessel_type(self, o1, o2):
        self.vessel_type_interpretation.add(o1, o2)

    def build(self) -> FunctionalScenario:
        return FunctionalScenario(
            OS_interpretation=self.OS_interpretation,
            TS_interpretation=self.TS_interpretation,
            Static_obstacle_interpretation=self.Static_obstacle_interpretation,
            Vessel_type_interpretation=self.Vessel_type_interpretation,
            Static_obstacle_type_interpretation=self.Static_obstacle_type_interpretation,
            out_visibility_distance_interpretation=self.out_visibility_distance_interpretation,
            at_visibility_distance_interpretation=self.at_visibility_distance_interpretation,
            in_visibility_distance_interpretation=self.in_visibility_distance_interpretation,
            may_collide_interpretation=self.may_collide_interpretation,
            in_bow_sector_of_interpretation=self.in_bow_sector_of_interpretation,
            in_port_side_sector_of_interpretation=self.in_port_side_sector_of_interpretation,
            in_starboard_side_sector_of_interpretation=self.in_starboard_side_sector_of_interpretation,
            in_stern_sector_of_interpretation=self.in_stern_sector_of_interpretation,
            vessel_type_interpretation=self.vessel_type_interpretation,
            static_obstacle_type_interpretation=self.static_obstacle_type_interpretation,
        )
