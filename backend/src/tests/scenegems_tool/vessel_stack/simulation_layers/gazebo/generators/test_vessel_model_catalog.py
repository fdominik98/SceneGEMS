"""The preset vessel model catalog: loading, bounds and the values a preset gives a vessel."""

import dataclasses
import textwrap

import pytest

from concrete_level.models.concrete_actors import ConcreteVessel
from logical_level.mapping.vessel_type import VesselTypeMap
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import OVERRIDE_KEYS, derive_vessel_dynamics, steady_turn_of
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_model_catalog import (
    BOUND_KEYS,
    UnknownVesselModelPreset,
    VesselOutOfPresetBounds,
    load_vessel_model_catalog,
    read_vessel_model_catalog,
    vessel_dynamics_overrides,
)

PRESET = """
    cargo:
        name: Test cargo ship
        source: a test
        steering_type: rudder
        particulars:
            length: 150.0
        bounds:
            length: [120.0, 180.0]
            breadth: [18.0, 28.0]
            max_speed: [5.0, 14.0]
        dynamics:
            block_coefficient: 0.7
            rudder_max_angle_deg: 40.0
        notes: a note
"""


def write(folder, name: str, text: str) -> None:
    (folder / name).write_text(textwrap.dedent(text), encoding="utf-8")


def vessel_of(type_name: str, base_length: float, **changes) -> ConcreteVessel:
    """A vessel as the scene builder makes it from a shipped vessel type and a length, with fields changed afterwards."""
    length = base_length
    vessel_type = VesselTypeMap()[type_name]
    breadth = vessel_type.breadth_of(length)
    draft = vessel_type.draft_of(breadth)
    total = 1025 * vessel_type.block_coefficient * length * breadth * draft
    vessel = ConcreteVessel(
        id=0,
        type=type_name,
        length=length,
        breadth=breadth,
        height=2.5 * draft,
        draft=draft,
        mass=total * 0.998,
        safety_radius=4 * length,
        _is_os=True,
        _max_speed=vessel_type.max_speed,
        _max_angular_speed=vessel_type.max_angular_speed,
        _max_acceleration=vessel_type.max_acceleration,
        _rudder_mass=0.0,
        _rudder_length=0.02 * length,
        _rudder_width=0.1,
        _rudder_height=2.0 * draft,
        _propeller_diameter=0.6 * draft,
        _thruster_mass=total * 0.001,
        _motor_length=0.9 * draft,
        _steering_type=vessel_type.steering_type,
        _block_coefficient=vessel_type.block_coefficient,
    )
    return dataclasses.replace(vessel, **changes)


@pytest.fixture
def catalog(tmp_path):
    write(tmp_path, "ships.yaml", PRESET)
    return read_vessel_model_catalog(str(tmp_path))


class TestLoading:
    def test_a_preset_is_read_with_its_bounds_and_values(self, catalog):
        preset = catalog.get("cargo")
        assert (preset.name, preset.source, preset.steering_type, preset.notes) == ("Test cargo ship", "a test", "rudder", "a note")
        assert preset.bounds == {"length": (120.0, 180.0), "breadth": (18.0, 28.0), "max_speed": (5.0, 14.0)}
        assert preset.dynamics == {"block_coefficient": 0.7, "rudder_max_angle_deg": 40.0}
        assert preset.particulars == {"length": 150.0}

    def test_an_unknown_preset_is_named_with_the_known_ones(self, catalog):
        with pytest.raises(UnknownVesselModelPreset, match="mariner.*cargo"):
            catalog.get("mariner")

    def test_every_file_of_the_folder_is_read(self, tmp_path):
        write(tmp_path, "a.yaml", PRESET)
        write(tmp_path, "b.yaml", PRESET.replace("cargo:", "other:"))
        assert sorted(read_vessel_model_catalog(str(tmp_path)).presets) == ["cargo", "other"]

    def test_an_empty_folder_is_an_empty_catalog(self, tmp_path):
        assert read_vessel_model_catalog(str(tmp_path)).presets == {}

    @pytest.mark.parametrize(
        "change, message",
        [
            (("steering_type: rudder", "steering_type: sail"), "steering_type must be one of"),
            (("block_coefficient: 0.7", "hull_colour: 3"), "unknown vessel dynamics keys"),
            (("block_coefficient: 0.7", "block_coefficient: full"), "must be a number"),
            (("length: [120.0, 180.0]", "length: [180.0, 120.0]"), "is above its high"),
            (("length: [120.0, 180.0]", "length: 150.0"), r"must be \[low, high\]"),
            (("breadth: [18.0, 28.0]", "beam: [18.0, 28.0]"), "unknown bounds"),
            (("source: a test", "origin: a test"), "unknown keys"),
            (("        name: Test cargo ship\n", ""), "missing"),
        ],
    )
    def test_a_wrong_entry_fails_with_the_file_and_the_preset(self, tmp_path, change, message):
        write(tmp_path, "ships.yaml", PRESET.replace(*change))
        with pytest.raises(ValueError, match=message) as error:
            read_vessel_model_catalog(str(tmp_path))
        assert "ships.yaml: cargo" in str(error.value)

    def test_a_preset_defined_in_two_files_fails(self, tmp_path):
        write(tmp_path, "a.yaml", PRESET)
        write(tmp_path, "b.yaml", PRESET)
        with pytest.raises(ValueError, match="b.yaml.*cargo is already defined"):
            read_vessel_model_catalog(str(tmp_path))


class TestBounds:
    def test_a_vessel_within_every_bound_fits(self, catalog):
        vessel = vessel_of("CargoShip", 150.0)
        assert catalog.get("cargo").mismatches(vessel) == []
        assert [preset.id for preset in catalog.eligible(vessel)] == ["cargo"]

    def test_the_bounds_are_inclusive(self, catalog):
        assert catalog.get("cargo").fits(vessel_of("CargoShip", 120.0, breadth=18.0))
        assert catalog.get("cargo").fits(vessel_of("CargoShip", 180.0, breadth=28.0))

    @pytest.mark.parametrize(
        "changes, reason",
        [
            ({"length": 200.0}, "its length of 200 m is outside 120 to 180 m"),
            ({"breadth": 30.0}, "its breadth of 30 m is outside 18 to 28 m"),
            ({"_max_speed": 20.0}, "its max speed of 20 m/s is outside 5 to 14 m/s"),
            ({"_steering_type": "skid"}, "its steering type is skid, the preset's is rudder"),
        ],
    )
    def test_a_vessel_outside_a_bound_does_not_fit_and_the_reason_says_why(self, catalog, changes, reason):
        vessel = vessel_of("CargoShip", 150.0, **changes)
        assert catalog.get("cargo").mismatches(vessel) == [reason]
        assert catalog.eligible(vessel) == []

    def test_every_reason_is_listed(self, catalog):
        vessel = vessel_of("CargoShip", 150.0, length=300.0, _steering_type="vectored_thrust")
        assert len(catalog.get("cargo").mismatches(vessel)) == 2

    def test_a_bound_left_out_is_not_checked(self, catalog):
        assert catalog.get("cargo").fits(vessel_of("CargoShip", 150.0, draft=50.0, _max_angular_speed=3.0))


class TestDynamics:
    def test_a_preset_gives_a_fitting_vessel_its_values(self, catalog):
        assert catalog.dynamics_for(vessel_of("CargoShip", 150.0), "cargo") == {"block_coefficient": 0.7, "rudder_max_angle_deg": 40.0}

    def test_a_vessel_out_of_bounds_is_refused_with_the_reason(self, catalog):
        with pytest.raises(VesselOutOfPresetBounds, match="cannot take the vessel model preset cargo .Test cargo ship.: its length of 300 m"):
            catalog.dynamics_for(vessel_of("CargoShip", 300.0), "cargo")

    def test_without_a_preset_the_overrides_are_the_override_files(self, catalog):
        assert vessel_dynamics_overrides(vessel_of("CargoShip", 150.0), None, catalog) == {}

    def test_a_preset_goes_on_top_of_the_override_files(self, catalog):
        vessel = vessel_of("CargoShip", 150.0)
        overrides = vessel_dynamics_overrides(vessel, "cargo", catalog)
        assert overrides["block_coefficient"] == 0.7
        dynamics = derive_vessel_dynamics(vessel, 0.0, overrides)
        assert dynamics.hull.block_coefficient == 0.7
        assert dynamics.steering_max_angle == pytest.approx(0.6981317)  # 40 degrees
        assert (dynamics.length, dynamics.breadth, dynamics.draft) == (vessel.length, vessel.breadth, vessel.draft)  # the vessel's own

    def test_what_the_console_shows_of_a_preset(self, catalog):
        shown = catalog.get("cargo").as_dict()
        assert shown["id"] == "cargo" and shown["steeringType"] == "rudder"
        assert shown["bounds"]["length"] == [120.0, 180.0]
        assert "dynamics" not in shown


class TestShippedCatalog:
    @pytest.fixture(scope="class")
    def shipped(self):
        return load_vessel_model_catalog()

    def test_the_documented_ships_are_there(self, shipped):
        assert set(shipped.presets) == {
            "mariner",
            "container_ship_175",
            "tanker_190000_dwt",
            "offshore_supply_vessel",
            "naval_vessel",
            "otter_usv",
            "hanjin_pretoria",
            "csl_spirit",
            "captain_plaushevskiy",
            "statendam",
        }

    def test_every_preset_is_well_formed(self, shipped):
        for preset in shipped.presets.values():
            assert preset.name and preset.source, preset.id
            assert set(preset.bounds) <= set(BOUND_KEYS) and "length" in preset.bounds, preset.id
            assert set(preset.dynamics) <= OVERRIDE_KEYS, preset.id
            if "length" in preset.particulars:
                low, high = preset.bounds["length"]
                assert low <= preset.particulars["length"] <= high, preset.id

    def test_the_panamax_presets_have_a_panamax_beam(self, shipped):
        for preset_id in ("hanjin_pretoria", "csl_spirit", "statendam"):
            assert 30.0 <= shipped.get(preset_id).particulars["breadth"] <= 32.31

    def test_a_panamax_container_ship_of_the_shipped_types_can_take_the_hanjin_pretoria(self, shipped):
        vessel = vessel_of("ContainerShip", 266.0)
        assert "hanjin_pretoria" in [preset.id for preset in shipped.eligible(vessel)]

    def test_a_small_vessel_is_offered_no_ship(self, shipped):
        assert shipped.eligible(vessel_of("FishingShip", 12.0)) == []

    def test_a_skid_steered_vessel_is_offered_no_rudder_ship(self, shipped):
        vessel = vessel_of("ContainerShip", 266.0, _steering_type="skid")
        assert shipped.eligible(vessel) == []

    def test_every_preset_gives_a_valid_model_for_a_vessel_of_its_own_size(self, shipped):
        for preset in shipped.presets.values():
            particulars = preset.particulars
            length = particulars["length"]
            breadth = particulars.get("breadth", length / 6.5)
            draft = particulars.get("draft", breadth / 3.0)
            speed = min(max(particulars.get("speed", 8.0), preset.bounds.get("max_speed", (0.0, 1e9))[0]), preset.bounds.get("max_speed", (0.0, 1e9))[1])
            turn_rate = min(0.3 * speed / length, preset.bounds.get("max_angular_speed", (0.0, 1e9))[1])
            vessel = vessel_of("CargoShip", 150.0, length=length, breadth=breadth, draft=draft, height=2.5 * draft, _max_speed=speed, _max_angular_speed=turn_rate, _steering_type=preset.steering_type)
            assert preset.mismatches(vessel) == [], preset.id
            dynamics = derive_vessel_dynamics(vessel, 0.0, vessel_dynamics_overrides(vessel, preset.id, shipped))
            assert dynamics.steering_type == preset.steering_type
            assert dynamics.roll_metacentric_height > 0 and dynamics.max_thrust > 0, preset.id

    def test_the_statendam_turns_as_tightly_as_one_plain_rudder_can(self, shipped):
        """The sea trial's final diameter is 258 m (1.18 ship lengths), turned with twin flap rudders in the propellers' wash.

        The model's one plain rudder cannot hold that turn: its own sideways motion in the turn takes
        away its angle of attack. The calibration then leaves the hull the least yaw damping, and
        the model turns on about one and a half ship lengths: tighter than the automatic model of a
        vessel whose max turn rate asks for less.
        """
        vessel = vessel_of("PassengerShip", 219.4, breadth=30.8, draft=7.55, height=18.9, _max_speed=11.163, _max_angular_speed=0.012)
        preset = derive_vessel_dynamics(vessel, 0.0, vessel_dynamics_overrides(vessel, "statendam", shipped))
        automatic = derive_vessel_dynamics(vessel, 0.0, {"rudder_max_angle_deg": 45.0})

        def diameter(dynamics) -> float:
            surge, sway, yaw_rate = steady_turn_of(dynamics, speed=10.412)
            return 2.0 * (surge**2 + sway**2) ** 0.5 / abs(yaw_rate)

        assert 258.0 < diameter(preset) < 1.55 * 219.4
        assert diameter(preset) < diameter(automatic)
        assert preset.steering_max_angle == pytest.approx(0.7853982)  # 45 degrees

    def test_a_turning_circle_within_the_rudders_reach_is_met(self):
        """A measured turning circle of three ship lengths: the model's steady turn has that diameter at the trial's speed."""
        vessel = vessel_of("CargoShip", 160.0)
        dynamics = derive_vessel_dynamics(vessel, 0.0, {"turn_diameter_ratio": 3.0, "turn_speed": 7.7})
        surge, sway, yaw_rate = steady_turn_of(dynamics, speed=7.7)
        assert 2.0 * (surge**2 + sway**2) ** 0.5 / yaw_rate == pytest.approx(3.0 * 160.0, rel=0.01)
