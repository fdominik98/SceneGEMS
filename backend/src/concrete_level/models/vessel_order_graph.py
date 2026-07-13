from typing import Dict, List, Optional, Tuple

from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.multi_level_scenario import MultiLevelScenario
from concrete_level.models.relation import Relation
from functional_level.metamodels.functional_object import FuncObject
from functional_level.metamodels.functional_scenario import FunctionalScenario


class VesselOrderNode:
    def __init__(self, vessel: ConcreteVessel) -> None:
        self.vessel = vessel
        self.relations: List[Relation] = []
        self.in_degree = 0
        self.out_degree = 0

    def __eq__(self, value: object) -> bool:
        return isinstance(value, VesselOrderNode) and self.vessel == value.vessel

    def __repr__(self) -> str:
        return self.vessel.__repr__()


class VesselOrderGraph:
    def __init__(self, scenario: MultiLevelScenario):
        self.nodes: Dict[ConcreteVessel, VesselOrderNode] = {}
        self.in_degree: Dict[VesselOrderNode, int] = {}
        self.out_degree: Dict[VesselOrderNode, int] = {}
        self.relations: List[Relation] = [Relation(scenario.to_concrete_actor(obj1), scenario.to_concrete_actor(obj2)) for obj1, obj2 in scenario.functional_scenario.all_colregs_relation_pairs]

        for rel in self.relations:
            self.add_nodes(rel)
        for rel in self.relations:
            self.add_edge(rel)

    def add_nodes(self, rel: Relation):
        node1 = VesselOrderNode(rel[0])
        if rel[0] not in self.nodes:
            self.nodes[rel[0]] = node1
        node2 = VesselOrderNode(rel[1])
        if rel[1] not in self.nodes:
            self.nodes[rel[1]] = node2

    def add_edge(self, rel: Relation):
        node1 = self.nodes[rel[0]]
        node2 = self.nodes[rel[1]]
        node1.relations.append(rel)
        node1.out_degree += 1
        node2.in_degree += 1

    def sort(self) -> list[VesselOrderNode]:
        # sort by net degree. If net degree is the same the one with the lowest out degree comes first
        return sorted(self.nodes.values(), key=lambda node: (node.out_degree - node.in_degree, node.out_degree))

    def get_relation(self, vessel1: ConcreteVessel, vessel2: ConcreteVessel) -> Optional[Relation]:
        for rel in self.relations:
            if rel[0] == vessel1 and rel[1] == vessel2 or rel[0] == vessel2 and rel[1] == vessel1:
                return rel
        return None
