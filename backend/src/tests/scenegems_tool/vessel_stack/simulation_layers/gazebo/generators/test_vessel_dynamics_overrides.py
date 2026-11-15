"""Loading of the vessel dynamics override files: sections, precedence, and loud failures."""

import dataclasses
import re
from pathlib import Path
from typing import Set

import pytest

from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import ASSUMPTION_KEYS, VALUE_KEYS, derive_vessel_dynamics
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics_overrides import VesselDynamicsOverrides, load_vessel_dynamics_overrides
from tests.scenegems_tool.vessel_stack.scenarios import make_vessel
from utils.file_system_utils import VESSEL_DYNAMICS_FOLDER


def write(folder, name: str, text: str) -> None:
    (folder / name).write_text(text, encoding="utf-8")


def test_the_shipped_folder_loads_and_holds_no_overrides_yet():
    overrides = load_vessel_dynamics_overrides(VESSEL_DYNAMICS_FOLDER)
    assert overrides.by_vessel_type == {}
    assert overrides.by_vessel_id == {}


def shipped_header() -> str:
    """The comment at the head of the shipped override file, which tells its reader the keys."""
    text = (Path(VESSEL_DYNAMICS_FOLDER) / "vessel_dynamics.yaml").read_text(encoding="utf-8")
    return "\n".join(line for line in text.splitlines() if line.startswith("#"))


def header_section(start: str, end: str) -> Set[str]:
    """The words of the header between two of its headings."""
    header = shipped_header()
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", header[header.index(start) + len(start) : header.index(end)]))


def test_the_shipped_header_lists_exactly_the_assumption_keys():
    words = header_section("# Assumption keys", "# Value keys")
    assert ASSUMPTION_KEYS <= words, f"missing: {sorted(ASSUMPTION_KEYS - words)}"
    assert not VALUE_KEYS & words, "a value key among the assumption keys"
    assert {word for word in words if "_" in word} == ASSUMPTION_KEYS, "every assumption key has an underscore, so any other such word is a key that no longer exists"


def test_the_shipped_header_lists_exactly_the_value_keys():
    words = header_section("# Value keys", "# Example:")
    assert VALUE_KEYS <= words, f"missing: {sorted(VALUE_KEYS - words)}"
    assert not ASSUMPTION_KEYS & words, "an assumption key among the value keys"
    assert {word for word in words if "_" in word} <= VALUE_KEYS, "a key that no longer exists"


def test_the_shipped_header_names_no_key_of_the_former_box_hull():
    assert "collision_" not in shipped_header()


def test_the_example_of_the_shipped_header_is_a_valid_override_file(tmp_path):
    header = shipped_header()
    example = "\n".join(line[2:] for line in header[header.index("# Example:") :].splitlines()[1:])
    write(tmp_path, "example.yaml", example)
    overrides = load_vessel_dynamics_overrides(str(tmp_path))
    assert overrides.by_vessel_type == {"CargoShip": {"block_coefficient": 0.75}}
    assert overrides.by_vessel_id == {3: {"max_thrust": 250000.0}}
    cargo_ship = dataclasses.replace(make_vessel(3, False), type="CargoShip")
    assert derive_vessel_dynamics(cargo_ship, overrides=overrides.for_vessel(cargo_ship)).max_thrust == 250000.0


def test_empty_folder_gives_no_overrides(tmp_path):
    assert load_vessel_dynamics_overrides(str(tmp_path)) == VesselDynamicsOverrides({}, {})


def test_type_and_id_sections_are_read(tmp_path):
    write(tmp_path, "a.yaml", "vessel_types:\n  CargoShip:\n    block_coefficient: 0.75\nvessel_ids:\n  3:\n    max_thrust: 250000\n")
    overrides = load_vessel_dynamics_overrides(str(tmp_path))
    assert overrides.by_vessel_type == {"CargoShip": {"block_coefficient": 0.75}}
    assert overrides.by_vessel_id == {3: {"max_thrust": 250000.0}}


def test_id_entry_wins_over_the_type_entry_key_by_key():
    overrides = VesselDynamicsOverrides(
        by_vessel_type={"OSPassengerShip": {"block_coefficient": 0.7, "propeller_kt": 0.25}},
        by_vessel_id={0: {"block_coefficient": 0.8}},
    )
    assert overrides.for_vessel(make_vessel(0, True)) == {"block_coefficient": 0.8, "propeller_kt": 0.25}


def test_vessel_without_an_entry_gets_nothing():
    overrides = VesselDynamicsOverrides(by_vessel_type={"CargoShip": {"block_coefficient": 0.7}}, by_vessel_id={5: {"max_thrust": 1.0}})
    assert overrides.for_vessel(make_vessel(0, True)) == {}


def test_several_files_are_merged(tmp_path):
    write(tmp_path, "a.yaml", "vessel_types:\n  CargoShip:\n    block_coefficient: 0.75\n")
    write(tmp_path, "b.yaml", "vessel_ids:\n  1:\n    max_thrust: 5\n")
    overrides = load_vessel_dynamics_overrides(str(tmp_path))
    assert set(overrides.by_vessel_type) == {"CargoShip"}
    assert set(overrides.by_vessel_id) == {1}


def test_unknown_section_fails(tmp_path):
    write(tmp_path, "a.yaml", "vessels:\n  1: {}\n")
    with pytest.raises(ValueError, match=r"a.yaml: unknown sections \['vessels'\]"):
        load_vessel_dynamics_overrides(str(tmp_path))


def test_unknown_key_fails_and_lists_the_known_ones(tmp_path):
    write(tmp_path, "a.yaml", "vessel_types:\n  CargoShip:\n    block_coeficient: 0.75\n")
    with pytest.raises(ValueError, match=r"unknown vessel dynamics keys \['block_coeficient'\]; known keys:"):
        load_vessel_dynamics_overrides(str(tmp_path))


@pytest.mark.parametrize("value", ["heavy", "'1.5'", "true", "[1, 2]"])
def test_non_numeric_value_fails(tmp_path, value):
    write(tmp_path, "a.yaml", f"vessel_ids:\n  1:\n    max_thrust: {value}\n")
    with pytest.raises(ValueError, match="must be a number"):
        load_vessel_dynamics_overrides(str(tmp_path))


def test_entry_that_is_not_a_mapping_fails(tmp_path):
    write(tmp_path, "a.yaml", "vessel_ids:\n  1: 5\n")
    with pytest.raises(ValueError, match="expected a mapping of vessel dynamics keys to numbers"):
        load_vessel_dynamics_overrides(str(tmp_path))


def test_file_that_is_not_a_mapping_fails(tmp_path):
    write(tmp_path, "a.yaml", "- 1\n- 2\n")
    with pytest.raises(ValueError, match="expected the sections"):
        load_vessel_dynamics_overrides(str(tmp_path))


def test_an_entry_in_two_files_fails(tmp_path):
    write(tmp_path, "a.yaml", "vessel_ids:\n  1:\n    max_thrust: 5\n")
    write(tmp_path, "b.yaml", "vessel_ids:\n  1:\n    max_thrust: 6\n")
    with pytest.raises(ValueError, match="b.yaml: vessel_ids 1 is already defined in another vessel dynamics file"):
        load_vessel_dynamics_overrides(str(tmp_path))


def test_integer_values_become_floats(tmp_path):
    write(tmp_path, "a.yaml", "vessel_ids:\n  1:\n    max_thrust: 5\n")
    value = load_vessel_dynamics_overrides(str(tmp_path)).by_vessel_id[1]["max_thrust"]
    assert isinstance(value, float)


def test_empty_sections_are_allowed(tmp_path):
    write(tmp_path, "a.yaml", "vessel_types: {}\nvessel_ids:\n")
    assert load_vessel_dynamics_overrides(str(tmp_path)).by_vessel_id == {}
