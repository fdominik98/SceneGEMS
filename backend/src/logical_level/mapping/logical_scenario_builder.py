from itertools import chain
from typing import Any, Dict, List, Optional, Set, Tuple

from functional_level.metamodels.functional_object import FuncObject
from functional_level.metamodels.functional_scenario import FunctionalScenario
from logical_level.mapping.instance_initializer import DeterministicInitializer, InstanceInitializer, LatinHypercubeInitializer, RandomInstanceInitializer
from logical_level.mapping.static_obstacle import StaticObstacleTypeMap
from logical_level.mapping.vessel_type import VesselTypeMap
from logical_level.models.actor_variable import ActorVariable, OSVariable, StaticObstacleVariable, TSVariable
from logical_level.models.logical_scenario import LogicalScenario
from logical_level.models.relation_constraints_concept.composites import RelationConstrComposite, RelationConstrTerm
from logical_level.models.relation_constraints_concept.literals import AtVis, InBowSectorOf, InPortSideSectorOf, InStarboardSideSectorOf, InSternSectorOf, InVis, OutVis
from logical_level.models.relation_constraints_concept.predicates import (
    BinaryPredicate,
    AtCrossingFromPortCR,
    AtDangerousHeadOnSectorOfCR,
    AtHeadOnCR,
    MayCollideSoon,
    NotInBowSectorOf,
    OutVisOrMayNotCollide,
    AtOvertakingToPortCR,
    AtOvertakingToStarboardCR,
)
from utils.colregs_approximations import COLREGSConstraints

class LogicalScenarioBuilder:
    @staticmethod
    def build_from_functional(
        functional_scenario: FunctionalScenario,
        vessel_type_map: VesselTypeMap,
        obstacle_type_map: StaticObstacleTypeMap,
        colregs_constants: COLREGSConstraints,
        init_method=RandomInstanceInitializer.name,
    ) -> LogicalScenario:
        os = functional_scenario.os_object
        object_variable_map : Dict[FuncObject, ActorVariable] = {os: OSVariable(os.id, vessel_type_map[functional_scenario.find_vessel_type_name(os)])}
        object_variable_map |= {ts: TSVariable(ts.id, vessel_type_map[functional_scenario.find_vessel_type_name(ts)]) for ts in functional_scenario.ts_objects}
        object_variable_map |= {
            o: StaticObstacleVariable(
                o.id,
                obstacle_type_map[functional_scenario.find_obstacle_type_name(o)],
            )
            for o in functional_scenario.obstacle_objects
        }

        # Define interpretations and their corresponding LogicalScenarioBuilder methods
        predicate_constraint_map: List[Tuple[Any, type[BinaryPredicate]]] = [
            (functional_scenario.dangerous_head_on_sector_of, AtDangerousHeadOnSectorOfCR),
            (functional_scenario.head_on, AtHeadOnCR),
            (functional_scenario.overtaking_to_port, AtOvertakingToPortCR),
            (functional_scenario.overtaking_to_starboard, AtOvertakingToStarboardCR),
            (functional_scenario.crossing_from_port, AtCrossingFromPortCR),
            (functional_scenario.out_vis_or_may_not_collide, OutVisOrMayNotCollide),
        ]

        # predicate_constraint_map : List[Tuple[Any, type[BinaryPredicate]]] = [
        #     (functional_scenario.in_bow_sector_of_interpretation.contains, InBowSectorOf),
        #     #(lambda tuple : not functional_scenario.in_bow_sector_of_interpretation.contains(tuple), NotInBowSectorOf),
        #     (functional_scenario.in_stern_sector_of_interpretation.contains, InSternSectorOf),
        #     (functional_scenario.in_starboard_side_sector_of_interpretation.contains, InStarboardSideSectorOf),
        #     (functional_scenario.in_port_side_sector_of_interpretation.contains, InPortSideSectorOf),
        #     (functional_scenario.may_collide_interpretation.contains, MayCollideSoon),
        #     (functional_scenario.in_visibility_distance_interpretation.contains, InVis),
        #     (functional_scenario.at_visibility_distance_interpretation.contains, AtVis),
        #     (functional_scenario.out_visibility_distance_interpretation.contains, OutVis),
        #     (functional_scenario.out_vis_or_may_not_collide, OutVisOrMayNotCollide)
        # ]

        # Generate relation constraint expressions
        relation_constr_exprs : Set[RelationConstrComposite] = set()
        for o1, o2 in functional_scenario.all_sea_object_pair_permutations:
            for pred, Constr in predicate_constraint_map:
                if pred(o1, o2):
                    relation_constr_exprs.add(Constr(object_variable_map[o1], object_variable_map[o2], colregs_constants))

        actor_variables: List[ActorVariable] = sorted(object_variable_map.values(), key=lambda x: x.id)

        return LogicalScenario(
            LogicalScenarioBuilder.get_initializer(init_method, actor_variables),
            RelationConstrTerm(relation_constr_exprs),
            *LogicalScenarioBuilder.get_bounds(actor_variables),
        )

    @staticmethod
    def get_bounds(
        actor_variables: List[ActorVariable],
    ) -> Tuple[List[float], List[float]]:
        xl = list(chain.from_iterable([var.lower_bounds for var in actor_variables]))
        xu = list(chain.from_iterable([var.upper_bounds for var in actor_variables]))
        return xl, xu

    @staticmethod
    def get_initializer(init_method: str, vessel_vars: List[ActorVariable]) -> InstanceInitializer:
        if init_method == RandomInstanceInitializer.name or init_method == None:
            return RandomInstanceInitializer(vessel_vars)
        elif init_method == DeterministicInitializer.name:
            return DeterministicInitializer(vessel_vars)
        elif init_method == LatinHypercubeInitializer.name:
            return LatinHypercubeInitializer(vessel_vars)
        else:
            raise Exception("unknown parameter")
