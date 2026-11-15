"""SceneBuilder.build_from_assignments: a vessel's hull and steering follow its vessel type."""

import pytest

from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.trajectory_generation.scene_builder import SceneBuilder
from logical_level.constraint_satisfaction.assignments import Assignments
from logical_level.mapping.vessel_type import SteeringType, VesselType
from logical_level.models.actor_variable import OSVariable, TSVariable

LIMITS = {"min_length": 20.0, "max_length": 400.0, "min_beam": 5.0, "max_beam": 60.0, "max_speed": 12.0, "max_angular_speed": 0.01, "max_acceleration": 0.05}
CARGO = VesselType(name="Cargo", steering_type="rudder", block_coefficient=0.72, length_to_beam=6.5, beam_to_draft=2.5, **LIMITS)
OLD = VesselType(name="Old", **LIMITS)


def build(own_type: VesselType, own_length: float, target_type: VesselType = OLD, target_length: float = 50.0):
    variables = [OSVariable(0, own_type), TSVariable(1, target_type)]
    # x, y, heading, length, speed per vessel
    assignments = Assignments(variables).update_from_individual([0.0, 0.0, 0.0, own_length, 5.0, 3000.0, 0.0, 3.14, target_length, 5.0])
    scene = SceneBuilder.build_from_assignments(assignments)
    own = scene.get_by_id(0)
    target = scene.get_by_id(1)
    assert isinstance(own, ConcreteVessel) and isinstance(target, ConcreteVessel)
    return own, target


class TestHull:
    def test_breadth_draft_and_height_follow_the_type_ratios(self):
        own, _ = build(CARGO, 195.0)
        assert own.breadth == pytest.approx(30.0)
        assert own.draft == pytest.approx(12.0)
        assert own.height == pytest.approx(30.0)

    def test_breadth_is_kept_within_the_beam_range(self):
        own, _ = build(CARGO, 26.0)
        assert own.breadth == 5.0  # 4 m by the ratio

    def test_mass_is_the_displacement_at_the_type_block_coefficient(self):
        own, _ = build(CARGO, 195.0)
        displacement = 1025 * 0.72 * 195.0 * 30.0 * 12.0
        assert own.mass + 2 * own.thruster_mass == pytest.approx(displacement)
        assert own.block_coefficient == 0.72

    def test_a_type_without_hull_columns_gives_the_hull_of_before(self):
        own, _ = build(OLD, 50.0)
        assert own.breadth == pytest.approx(0.4 * 50.0)
        assert own.draft == pytest.approx(0.06 * 50.0)
        assert own.height == pytest.approx(0.15 * 50.0)
        assert own.block_coefficient == 0.6


class TestSteering:
    def test_each_vessel_takes_the_steering_type_of_its_own_type(self):
        own, target = build(CARGO, 195.0)
        assert own.steering_type is SteeringType.RUDDER
        assert target.steering_type is SteeringType.SKID
