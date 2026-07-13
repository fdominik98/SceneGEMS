from itertools import chain, permutations
from typing import Dict, List, Set, Tuple

from concrete_level.models.concrete_actors import ConcreteStaticObstacle, ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.multi_level_scenario import MultiLevelScenario
from functional_level.metamodels.functional_scenario import FuncObject
from functional_level.metamodels.interpretation import BinaryInterpretation
from functional_level.models.functional_scenario_builder import FunctionalScenarioBuilder
from logical_level.constraint_satisfaction.assignments import Assignments
from logical_level.constraint_satisfaction.evaluation_cache import EvaluationCache
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from logical_level.mapping.instance_initializer import RandomInstanceInitializer
from logical_level.mapping.logical_scenario_builder import LogicalScenarioBuilder
from logical_level.models.actor_variable import ActorVariable, StaticObstacleVariable, VesselVariable
from logical_level.models.logical_scenario import LogicalScenario
from logical_level.models.relation_constraints_concept.composites import RelationConstrComposite, RelationConstrTerm
from logical_level.models.relation_constraints_concept.literals import (
    AtVis,
    BinaryLiteral,
    InBowSectorOf,
    InPortSideSectorOf,
    InStarboardSideSectorOf,
    InSternSectorOf,
    InVis,
    OnCollisionCourse,
    OutVis,
)

class ConcreteSceneAbstractor:
    @staticmethod
    def get_abstractions_from_concrete(scene: ConcreteScene, init_method=RandomInstanceInitializer.name) -> MultiLevelScenario:
        
        builder = FunctionalScenarioBuilder()

        abstractions: List[Tuple[ActorVariable, FuncObject]] = [ConcreteSceneAbstractor.create_vessel_abstraction(vessel, builder) for vessel in scene.vessels]
        abstractions.extend([ConcreteSceneAbstractor.create_static_obstacle_abstraction(obstacle, builder) for obstacle in scene.obstacles])

        actor_variables: List[ActorVariable] = [var for var, _ in abstractions]

        relation_constr_exprs: Set[RelationConstrComposite] = set()

        assignments = Assignments(actor_variables).update_from_individual(scene.individual)
        eval_cache = EvaluationCache(assignments)

        constraint_interpretation_map: List[Tuple[type[BinaryLiteral], BinaryInterpretation]] = [
            (OnCollisionCourse, builder.may_collide_interpretation),
            (AtVis, builder.at_visibility_distance_interpretation),
            (OutVis, builder.out_visibility_distance_interpretation),
            (InVis, builder.in_visibility_distance_interpretation),
            (InBowSectorOf, builder.in_bow_sector_of_interpretation),
            (InPortSideSectorOf, builder.in_port_side_sector_of_interpretation),
            (
                InStarboardSideSectorOf,
                builder.in_starboard_side_sector_of_interpretation,
            ),
            (InSternSectorOf, builder.in_stern_sector_of_interpretation),
        ]

        for (var1, obj1), (var2, obj2) in permutations(abstractions, 2):
            if not var2.is_vessel:
                continue

            for Constr, interpretation in constraint_interpretation_map:
                pred = Constr(var1, var2)
                if pred.holds(eval_cache):
                    interpretation.add(obj1, obj2)
                    relation_constr_exprs.add(pred)

        functional_scenario = builder.build()

        xl = list(chain.from_iterable([var.lower_bounds for var in actor_variables]))
        xu = list(chain.from_iterable([var.upper_bounds for var in actor_variables]))
        initializer = LogicalScenarioBuilder.get_initializer(init_method, actor_variables)
        logical_scenario = LogicalScenario(initializer, RelationConstrTerm(relation_constr_exprs), xl, xu)

        return MultiLevelScenario(scene, logical_scenario, functional_scenario)

    @staticmethod
    def get_abstractions_from_eval(eval_data: EvaluationData) -> MultiLevelScenario:
        return ConcreteSceneAbstractor.get_abstractions_from_concrete(eval_data.best_scene, eval_data.init_method)

    @staticmethod
    def get_equivalence_class_distribution(scenes: List[ConcreteScene], is_second_level_abstraction=False) -> Dict[int, Tuple[ConcreteScene, int]]:
        equivalence_classes: Dict[int, Tuple[ConcreteScene, int]] = {}
        for scene in scenes:
            if not scene.has_functional_hash:
                raise ValueError("Scene does not have a functional hash. Annotate hash!")
            if is_second_level_abstraction:
                hash = scene.second_level_hash
            else:
                hash = scene.first_level_hash
                
            if hash is None:
                print(f"WARNING:Scene {scene} does not have a functional hash. Annotate hash!")
                continue

            if hash not in equivalence_classes:
                equivalence_classes[hash] = (scene, 1)
            else:
                _, count = equivalence_classes[hash]
                equivalence_classes[hash] = (scene, count + 1)
        return equivalence_classes
    
    
    @staticmethod
    def create_static_obstacle_abstraction(obstacle: ConcreteStaticObstacle, builder: FunctionalScenarioBuilder) -> Tuple[StaticObstacleVariable, FuncObject]:
        logical_variable = obstacle.logical_variable
        obstacle_type_obj = builder.add_new_obstacle_type(obstacle.type)
        obj = builder.add_new_obstacle(obstacle.name, obstacle.id)
        builder.static_obstacle_type_interpretation.add(obj, obstacle_type_obj)
        return logical_variable, obj
    
    @staticmethod
    def create_vessel_abstraction(vessel: ConcreteVessel, builder: FunctionalScenarioBuilder) -> Tuple[VesselVariable, FuncObject]:
        logical_variable = vessel.logical_variable
        vessel_type_obj = builder.add_new_vessel_type(vessel.type)
        if vessel.is_os:
            obj = builder.add_new_os(vessel.name, vessel.id)
        else:
            obj = builder.add_new_ts(vessel.name, vessel.id)
        builder.vessel_type_interpretation.add(obj, vessel_type_obj)
        return logical_variable, obj