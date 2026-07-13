import unittest
from typing import List, Tuple
from unittest.mock import Mock

from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.multi_level_scenario import MultiLevelScenario
from concrete_level.models.relation import Relation
from concrete_level.models.vessel_order_graph import VesselOrderGraph, VesselOrderNode
from functional_level.metamodels.functional_scenario import FunctionalScenario
from utils.colregs_approximations import vessel_radius


class TestVesselOrderGraphSort(unittest.TestCase):
    """Test cases for the VesselOrderGraph.sort() method."""

    def create_mock_vessel(self, vessel_id: int, is_os: bool = True) -> ConcreteVessel:
        """Helper method to create a mock ConcreteVessel."""
        return ConcreteVessel(
            id=vessel_id,
            type="cargo_ship",
            length=100.0,
            breadth=20.0,
            height=10.0,
            draft=4.0,
            mass=1000.0,
            safety_radius=vessel_radius(100.0),
            _is_os=is_os,
            _max_speed=15.0,
            _max_angular_speed=0.1,
            _max_acceleration=2.0,
            _rudder_mass=100.0,
            _rudder_length=10.0,
            _rudder_width=20.0,
            _rudder_height=10.0,
            _propeller_diameter=10.0,
            _thruster_mass=100.0,
            _motor_length=10.0,
        )

    def create_mock_scenario(self, relations: List[Relation]) -> MultiLevelScenario:
        """Helper method to create a mock MultiLevelScenario."""
        mock_scenario = Mock(spec=MultiLevelScenario)
        mock_scenario.functional_scenario = Mock(spec=FunctionalScenario)
        mock_scenario.functional_scenario.all_colregs_relation_pairs = relations
        mock_scenario.to_concrete_actor = lambda x: x
        return mock_scenario

    def test_sort_empty_graph(self):
        """Test sort method with an empty graph (no vessels)."""
        # Create empty scenario
        mock_scenario = self.create_mock_scenario([])
        graph = VesselOrderGraph(mock_scenario)

        # Sort should return empty list
        result = graph.sort()
        assert result == []

    def test_sort_single_vessel(self):
        """Test sort method with a single vessel."""
        vessel1 = self.create_mock_vessel(1)
        mock_scenario = self.create_mock_scenario([])
        graph = VesselOrderGraph(mock_scenario)

        # Manually add a single vessel node
        graph.nodes[vessel1] = VesselOrderNode(vessel1)

        result = graph.sort()
        assert len(result) == 1
        assert result[0].vessel == vessel1
        assert result[0].out_degree == 0
        assert result[0].in_degree == 0

    def test_sort_two_vessels_no_relations(self):
        """Test sort method with two vessels but no relations between them."""
        vessel1 = self.create_mock_vessel(1)
        vessel2 = self.create_mock_vessel(2)
        mock_scenario = self.create_mock_scenario([])
        graph = VesselOrderGraph(mock_scenario)

        # Manually add vessel nodes
        graph.nodes[vessel1] = VesselOrderNode(vessel1)
        graph.nodes[vessel2] = VesselOrderNode(vessel2)

        result = graph.sort()
        assert len(result) == 2
        # Both should have net degree 0, order doesn't matter
        for node in result:
            assert node.out_degree == 0
            assert node.in_degree == 0

    def test_sort_two_vessels_with_relation(self):
        """Test sort method with two vessels and one relation."""
        vessel1 = self.create_mock_vessel(1)
        vessel2 = self.create_mock_vessel(2)
        relations = [Relation(vessel1, vessel2)]  # vessel1 -> vessel2
        mock_scenario = self.create_mock_scenario(relations)
        graph = VesselOrderGraph(mock_scenario)

        result = graph.sort()
        assert len(result) == 2

        # vessel1 should have out_degree=1, in_degree=0 (net degree = 1)
        # vessel2 should have out_degree=0, in_degree=1 (net degree = -1)
        # So vessel2 should come first
        assert result[0].vessel == vessel2
        assert result[0].out_degree == 0
        assert result[0].in_degree == 1

        assert result[1].vessel == vessel1
        assert result[1].out_degree == 1
        assert result[1].in_degree == 0

    def test_sort_three_vessels_chain(self):
        """Test sort method with three vessels in a chain: A -> B -> C."""
        vessel1 = self.create_mock_vessel(1)
        vessel2 = self.create_mock_vessel(2)
        vessel3 = self.create_mock_vessel(3)
        relations = [Relation(vessel1, vessel2), Relation(vessel2, vessel3)]
        mock_scenario = self.create_mock_scenario(relations)
        graph = VesselOrderGraph(mock_scenario)

        result = graph.sort()
        assert len(result) == 3

        # Expected net degrees:
        # vessel1: out_degree=1, in_degree=0 -> net = 1
        # vessel2: out_degree=1, in_degree=1 -> net = 0
        # vessel3: out_degree=0, in_degree=1 -> net = -1

        # Order should be: vessel3, vessel2, vessel1
        assert result[0].vessel == vessel3
        assert result[0].out_degree == 0
        assert result[0].in_degree == 1

        assert result[1].vessel == vessel2
        assert result[1].out_degree == 1
        assert result[1].in_degree == 1

        assert result[2].vessel == vessel1
        assert result[2].out_degree == 1
        assert result[2].in_degree == 0

    def test_sort_vessels_same_net_degree(self):
        """Test sort method with vessels having the same net degree."""
        vessel1 = self.create_mock_vessel(1)
        vessel2 = self.create_mock_vessel(2)
        vessel3 = self.create_mock_vessel(3)
        vessel4 = self.create_mock_vessel(4)

        # Create a diamond pattern: 1->2, 1->3, 2->4, 3->4
        relations = [(vessel1, vessel2), (vessel1, vessel3), (vessel2, vessel4), (vessel3, vessel4)]
        mock_scenario = self.create_mock_scenario(relations)
        graph = VesselOrderGraph(mock_scenario)

        result = graph.sort()
        assert len(result) == 4

        # Expected net degrees:
        # vessel1: out_degree=2, in_degree=0 -> net = 2
        # vessel2: out_degree=1, in_degree=1 -> net = 0
        # vessel3: out_degree=1, in_degree=1 -> net = 0
        # vessel4: out_degree=0, in_degree=2 -> net = -2

        # vessel4 should be first (lowest net degree)
        assert result[0].vessel == vessel4
        assert result[0].out_degree == 0
        assert result[0].in_degree == 2

        # vessel1 should be last (highest net degree)
        assert result[3].vessel == vessel1
        assert result[3].out_degree == 2
        assert result[3].in_degree == 0

        # vessel2 and vessel3 should be in the middle (same net degree)
        middle_vessels = [result[1].vessel, result[2].vessel]
        assert vessel2 in middle_vessels
        assert vessel3 in middle_vessels

    def test_sort_complex_graph(self):
        """Test sort method with a complex graph structure."""
        vessels = [self.create_mock_vessel(i) for i in range(1, 6)]

        # Create a complex graph: multiple sources and sinks
        relations = [
            (vessels[0], vessels[1]),  # 1 -> 2
            (vessels[0], vessels[2]),  # 1 -> 3
            (vessels[1], vessels[3]),  # 2 -> 4
            (vessels[2], vessels[3]),  # 3 -> 4
            (vessels[3], vessels[4]),  # 4 -> 5
        ]
        mock_scenario = self.create_mock_scenario(relations)
        graph = VesselOrderGraph(mock_scenario)

        result = graph.sort()
        assert len(result) == 5

        # Expected net degrees:
        # vessel1: out_degree=2, in_degree=0 -> net = 2
        # vessel2: out_degree=1, in_degree=1 -> net = 0
        # vessel3: out_degree=1, in_degree=1 -> net = 0
        # vessel4: out_degree=1, in_degree=2 -> net = -1
        # vessel5: out_degree=0, in_degree=1 -> net = -1

        # Verify specific positions
        assert result[0].vessel == vessels[4]  # Lowest net degree + Lowest out degree
        assert result[1].vessel == vessels[3]  # Lowest net degree
        assert result[4].vessel == vessels[0]  # Highest net degree

    def test_sort_returns_vessel_order_nodes(self):
        """Test that sort method returns VesselOrderNode objects."""
        vessel1 = self.create_mock_vessel(1)
        vessel2 = self.create_mock_vessel(2)
        relations = [(vessel1, vessel2)]
        mock_scenario = self.create_mock_scenario(relations)
        graph = VesselOrderGraph(mock_scenario)

        result = graph.sort()
        assert len(result) == 2

        # Verify all returned objects are VesselOrderNode instances
        for node in result:
            assert isinstance(node, VesselOrderNode)
            assert hasattr(node, "vessel")
            assert hasattr(node, "out_degree")
            assert hasattr(node, "in_degree")

    def test_sort_stability(self):
        """Test that sort method is stable for vessels with same net degree."""
        vessel1 = self.create_mock_vessel(1)
        vessel2 = self.create_mock_vessel(2)
        vessel3 = self.create_mock_vessel(3)

        # Create two independent relations so vessel2 and vessel3 have same net degree
        relations = [(vessel1, vessel2), (vessel1, vessel3)]
        mock_scenario = self.create_mock_scenario(relations)
        graph = VesselOrderGraph(mock_scenario)

        # Run sort multiple times to check stability
        results = []
        for _ in range(5):
            result = graph.sort()
            results.append([node.vessel.id for node in result])

        # All results should be identical
        for result in results[1:]:
            assert result == results[0]

    def test_sort_with_self_loops(self):
        """Test sort method behavior with self-loops (if they exist)."""
        vessel1 = self.create_mock_vessel(1)
        vessel2 = self.create_mock_vessel(2)

        # Note: This test assumes the graph can handle self-loops
        # In practice, COLREGS relations might not include self-loops
        relations = [(vessel1, vessel1), (vessel1, vessel2)]
        mock_scenario = self.create_mock_scenario(relations)
        graph = VesselOrderGraph(mock_scenario)

        result = graph.sort()
        assert len(result) == 2

        # vessel1 should have out_degree=2, in_degree=1 -> net = 1
        # vessel2 should have out_degree=0, in_degree=1 -> net = -1
        vessel1_node = next(node for node in result if node.vessel == vessel1)
        vessel2_node = next(node for node in result if node.vessel == vessel2)

        assert vessel1_node.out_degree == 2
        assert vessel1_node.in_degree == 1
        assert vessel2_node.out_degree == 0
        assert vessel2_node.in_degree == 1
