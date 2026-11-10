"""The shape hashes of a functional scenario: equal for the same shape whatever the objects are called, different for different shapes."""

import pytest

from functional_level.models.model_parser import ModelParser
from scenegems_tool.assurance.campaign.class_catalog import ClassCatalog

CATALOG = ClassCatalog.default()
TWO_VESSELS = "2vessel_0obstacle_scenarios"
OWN_SHIP_TYPE = "vesselType(os, OSPassengerShip)"


def _scenario(class_id: str, replace=("", "")):
    text = CATALOG.get(class_id).read_content()
    if replace[0]:
        assert replace[0] in text
        text = text.replace(*replace)
    return ModelParser.parse_problem(text)


def _family(folder: str):
    return [ModelParser.parse_problem(scenario_class.read_content()) for scenario_class in CATALOG if scenario_class.folder == folder]


def _one_per_family():
    first = {}
    for scenario_class in CATALOG:
        first.setdefault(scenario_class.folder, scenario_class.class_id)
    return sorted(first.values())


@pytest.mark.parametrize("class_id", _one_per_family())
def test_both_hashes_exist_for_a_fec_of_every_catalog_family(class_id):
    scenario = _scenario(class_id)
    # the own ship has a vessel type, and an obstacle may have an obstacle type: a type is a node of the graph too
    assert scenario.vessel_type_interpretation
    for hops in (0, 1, 2):
        assert isinstance(scenario.fsm_shape_hash(hops), int)
        assert isinstance(scenario.fec_shape_hash(hops), int)


def test_a_shape_hash_does_not_depend_on_how_the_objects_are_called():
    plain = _scenario(f"{TWO_VESSELS}/fec0")
    renamed = _scenario(f"{TWO_VESSELS}/fec0", ("ts1", "other_ship"))
    assert plain.fsm_shape_hash() == renamed.fsm_shape_hash()
    assert plain.fec_shape_hash() == renamed.fec_shape_hash()
    assert plain.fsm_shape_hash() == _scenario(f"{TWO_VESSELS}/fec0").fsm_shape_hash()  # parsed again: other objects, the same shape


def test_the_fsm_hash_tells_the_vessel_type_apart_and_the_fec_hash_does_not():
    passenger_ship = _scenario(f"{TWO_VESSELS}/fec0")
    tanker = _scenario(f"{TWO_VESSELS}/fec0", (OWN_SHIP_TYPE, "vesselType(os, Tanker)"))
    assert passenger_ship.fsm_shape_hash() != tanker.fsm_shape_hash()
    assert passenger_ship.fec_shape_hash() == tanker.fec_shape_hash()
    # without a hop the type is an edge to something unnamed: its name is in the neighborhood one hop away
    assert passenger_ship.fsm_shape_hash(0) == tanker.fsm_shape_hash(0)


def test_the_vessel_types_no_vessel_has_do_not_change_the_hash():
    text = CATALOG.get(f"{TWO_VESSELS}/fec0").read_content()
    fewer_types = ModelParser.parse_problem(text.replace("SailingVessel, MilitaryVessel, MiniUSV}", "SailingVessel}"))
    plain = ModelParser.parse_problem(text)
    assert len(fewer_types.vessel_types) == len(plain.vessel_types) - 2
    assert fewer_types.fsm_shape_hash() == plain.fsm_shape_hash()
    assert fewer_types.fec_shape_hash() == plain.fec_shape_hash()


@pytest.mark.parametrize("folder, size", [("2vessel_0obstacle_scenarios", 7), ("2vessel_1obstacle_scenarios", 7), ("3vessel_0obstacle_scenarios", 28), ("4vessel_0obstacle_scenarios", 84)])
def test_every_fec_of_a_family_has_a_hash_of_its_own(folder, size):
    scenarios = _family(folder)
    assert len(scenarios) == size
    assert len({scenario.fec_shape_hash() for scenario in scenarios}) == size
    assert len({scenario.fsm_shape_hash() for scenario in scenarios}) == size


def test_families_with_and_without_an_obstacle_differ():
    without = {scenario.fec_shape_hash() for scenario in _family("2vessel_0obstacle_scenarios")}
    with_one = {scenario.fec_shape_hash() for scenario in _family("2vessel_1obstacle_scenarios")}
    assert without.isdisjoint(with_one)
