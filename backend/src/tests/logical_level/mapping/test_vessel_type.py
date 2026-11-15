"""Vessel types: the constraints of a vessel, its steering type and hull ratios included."""

import pytest

from logical_level.mapping.vessel_type import DEFAULT_BEAM_TO_DRAFT, DEFAULT_BLOCK_COEFFICIENT, DEFAULT_LENGTH_TO_BEAM, SteeringType, VesselType, VesselTypeMap

LIMITS = {"min_length": 50.0, "max_length": 400.0, "min_beam": 10.0, "max_beam": 60.0, "max_speed": 12.0, "max_angular_speed": 0.01, "max_acceleration": 0.05}

OLD_FILE = """
UnspecifiedVesselType:
    min_length: 10.0
    max_length: 400.0
    min_beam: 2.0
    max_beam: 80.0
    max_speed: 25.0
    max_angular_speed: 0.03
    max_acceleration: 0.3
"""


class TestDefaults:
    def test_a_type_without_the_hull_columns_is_the_skid_steered_hull_of_before(self):
        vessel_type = VesselType(name="Old", **LIMITS)
        assert vessel_type.steering_type == "skid"
        assert vessel_type.block_coefficient == DEFAULT_BLOCK_COEFFICIENT == 0.6
        assert vessel_type.length_to_beam == DEFAULT_LENGTH_TO_BEAM == 2.5
        assert vessel_type.beam_to_draft == pytest.approx(DEFAULT_BEAM_TO_DRAFT) == pytest.approx(0.4 / 0.06)

    def test_a_file_without_the_hull_columns_still_loads(self):
        vessel_type = VesselTypeMap(OLD_FILE)["UnspecifiedVesselType"]
        assert vessel_type.steering_type == "skid" and vessel_type.block_coefficient == 0.6


class TestSteeringType:
    @pytest.mark.parametrize("steering", ["rudder", "skid", "vectored_thrust"])
    def test_every_steering_type_is_accepted(self, steering):
        assert VesselType(name="T", steering_type=steering, **LIMITS).steering_type == steering

    def test_an_enum_member_is_stored_as_its_value(self):
        vessel_type = VesselType(name="T", steering_type=SteeringType.RUDDER, **LIMITS)
        assert vessel_type.steering_type == "rudder" and type(vessel_type.steering_type) is str

    def test_an_unknown_steering_type_is_refused(self):
        with pytest.raises(ValueError, match="sail"):
            VesselType(name="T", steering_type="sail", **LIMITS)


class TestHullRatios:
    def test_breadth_follows_the_length_to_beam_ratio(self):
        vessel_type = VesselType(name="T", length_to_beam=6.5, **LIMITS)
        assert vessel_type.breadth_of(195.0) == pytest.approx(30.0)

    def test_breadth_stays_within_the_beam_range(self):
        vessel_type = VesselType(name="T", length_to_beam=6.5, **LIMITS)
        assert vessel_type.breadth_of(52.0) == 10.0  # 8 m by the ratio
        assert vessel_type.breadth_of(400.0) == 60.0  # 61.5 m by the ratio

    def test_draft_follows_the_beam_to_draft_ratio(self):
        assert VesselType(name="T", beam_to_draft=2.5, **LIMITS).draft_of(30.0) == pytest.approx(12.0)

    @pytest.mark.parametrize("field, value", [("block_coefficient", 0.0), ("block_coefficient", 1.2), ("length_to_beam", 0.0), ("beam_to_draft", -1.0)])
    def test_impossible_hull_values_are_refused(self, field, value):
        with pytest.raises(ValueError, match="vessel type T"):
            VesselType(name="T", **{**LIMITS, field: value})


class TestShippedVesselTypes:
    @pytest.fixture(scope="class")
    def vessel_types(self):
        return VesselTypeMap()

    def test_every_type_states_its_steering_and_hull(self, vessel_types):
        for name, vessel_type in vessel_types.items():
            assert vessel_type.steering_type in {steering.value for steering in SteeringType}, name
            assert 0.3 <= vessel_type.block_coefficient <= 0.9, name

    def test_ships_have_a_rudder_and_the_mini_usv_is_skid_steered(self, vessel_types):
        assert vessel_types["CargoShip"].steering_type == "rudder"
        assert vessel_types["MiniUSV"].steering_type == "skid"

    def test_a_panamax_container_ship_gets_a_panamax_beam(self, vessel_types):
        breadth = vessel_types["ContainerShip"].breadth_of(266.0)
        assert 30.0 <= breadth <= 37.0
        assert 8.0 <= vessel_types["ContainerShip"].draft_of(breadth) <= 13.5

    def test_fixed_size_types_keep_their_beam(self, vessel_types):
        assert vessel_types["OSPassengerShip"].breadth_of(30.0) == 10.0
        assert vessel_types["MiniUSV"].breadth_of(1.0) == 0.5
