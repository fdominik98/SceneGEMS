"""Steering type and block coefficient of a ConcreteVessel: stored, serialized and defaulted for old files."""

import json

import pytest

from concrete_level.models.concrete_actors import ConcreteActor, ConcreteVessel
from logical_level.mapping.vessel_type import SteeringType

FIELDS = {
    "id": 1,
    "type": "CargoShip",
    "length": 195.0,
    "breadth": 30.0,
    "height": 30.0,
    "draft": 12.0,
    "mass": 5.0e7,
    "safety_radius": 780.0,
    "_is_os": True,
    "_max_speed": 12.0,
    "_max_angular_speed": 0.008,
    "_max_acceleration": 0.05,
    "_rudder_mass": 0.0,
    "_rudder_length": 3.9,
    "_rudder_width": 0.1,
    "_rudder_height": 24.0,
    "_propeller_diameter": 7.2,
    "_thruster_mass": 5.0e4,
    "_motor_length": 10.8,
}


class TestFields:
    def test_a_vessel_carries_its_steering_type_and_block_coefficient(self):
        vessel = ConcreteVessel(**FIELDS, _steering_type="rudder", _block_coefficient=0.72)
        assert vessel.steering_type is SteeringType.RUDDER
        assert vessel.block_coefficient == 0.72

    def test_a_vessel_built_without_them_is_the_skid_steered_hull_of_before(self):
        vessel = ConcreteVessel(**FIELDS)
        assert vessel.steering_type is SteeringType.SKID
        assert vessel.block_coefficient == 0.6

    def test_an_enum_member_is_stored_as_its_value(self):
        vessel = ConcreteVessel(**FIELDS, _steering_type=SteeringType.VECTORED_THRUST)
        assert vessel.to_dict()["_steering_type"] == "vectored_thrust"

    def test_an_unknown_steering_type_is_refused(self):
        with pytest.raises(ValueError):
            ConcreteVessel(**FIELDS, _steering_type="oars")


class TestSerialization:
    def test_the_fields_survive_a_json_round_trip(self):
        vessel = ConcreteVessel(**FIELDS, _steering_type="vectored_thrust", _block_coefficient=0.45)
        restored = ConcreteActor.from_dict(json.loads(json.dumps(vessel.to_dict())))
        assert restored == vessel
        assert restored.steering_type is SteeringType.VECTORED_THRUST and restored.block_coefficient == 0.45

    def test_a_scene_file_from_before_the_fields_loads_as_a_skid_steered_hull(self):
        old = {**FIELDS, "is_vessel": True}
        vessel = ConcreteActor.from_dict(old)
        assert vessel.steering_type is SteeringType.SKID and vessel.block_coefficient == 0.6

    def test_a_legacy_dict_with_only_a_radius_loads_too(self):
        legacy = {"id": 2, "type": "T", "length": 30.0, "radius": 120.0, "is_vessel": True, "_is_os": False, "_max_speed": 10.0, "_max_angular_speed": 0.05, "_max_acceleration": 0.4}
        vessel = ConcreteActor.from_dict(legacy)
        assert vessel.breadth == pytest.approx(12.0) and vessel.steering_type is SteeringType.SKID


class TestVesselType:
    def test_the_vessel_type_of_a_vessel_repeats_its_hull(self):
        vessel = ConcreteVessel(**FIELDS, _steering_type="rudder", _block_coefficient=0.72)
        vessel_type = vessel.vessel_type
        assert vessel_type.steering_type == "rudder" and vessel_type.block_coefficient == 0.72
        assert vessel_type.breadth_of(vessel.length) == vessel.breadth
        assert vessel_type.draft_of(vessel.breadth) == pytest.approx(vessel.draft)
