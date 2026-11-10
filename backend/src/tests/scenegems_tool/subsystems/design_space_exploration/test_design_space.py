"""The scope's syntax, the default specification and the counts of a generated model."""

from pathlib import Path

import pytest

from functional_level.models.model_parser import ModelParser
from scenegems_tool.assurance.campaign import class_catalog
from scenegems_tool.subsystems.design_space_exploration.design_space import (
    DEFAULT_SCOPE,
    ScopeError,
    count_instances,
    default_specification,
    exploration_hash,
    parse_scope,
)

DATA = Path(__file__).parent / "data"


def test_a_scope_is_read_as_the_entries_the_generator_takes():
    assert parse_scope("TS = 2, StaticObstacle = 0") == ("TS=2", "StaticObstacle=0")
    assert parse_scope(" TS=1..3 ,StaticObstacle = 0 .. 1 ") == ("TS=1..3", "StaticObstacle=0..1")
    assert parse_scope("TS = 2..2") == ("TS=2",)
    assert parse_scope(DEFAULT_SCOPE) == ("TS=2", "StaticObstacle=0")


@pytest.mark.parametrize(
    "scope, reason",
    [
        ("", "the scope is empty"),
        ("   ", "the scope is empty"),
        ("TS", "'TS' is not a scope entry"),
        ("TS = two", "'TS = two' is not a scope entry"),
        ("TS = 2,", "'' is not a scope entry"),
        ("TS = 2..*", "is not a scope entry"),
        ("TS = -1", "is not a scope entry"),
        ("2 = TS", "is not a scope entry"),
        ("TS = 3..1", "the upper bound 1 is below the lower bound 3"),
        ("TS = 2, TS = 3", "names TS twice"),
        ("TS = 100000", "a scope bound is at most 1000"),
    ],
)
def test_a_scope_that_is_not_a_list_of_entries_is_refused_with_the_reason(scope, reason):
    with pytest.raises(ScopeError, match=reason.replace("(", r"\(").replace(")", r"\)").replace("*", r"\*")):
        parse_scope(scope)


def test_the_hash_pins_the_specification_and_the_scope_whatever_the_line_endings_and_the_spacing():
    specification = "class A.\nclass B.\n"
    pinned = exploration_hash(specification, "A = 1, B = 0..2")
    assert pinned == exploration_hash(specification.replace("\n", "\r\n"), "A=1,B=0..2")
    assert pinned != exploration_hash(specification, "A = 1, B = 0..3")
    assert pinned != exploration_hash(specification + "class C.\n", "A = 1, B = 0..2")
    assert len(pinned) == 64


def test_the_default_specification_is_the_first_part_of_the_catalog_fecs_with_the_own_ship_fixed():
    specification = default_specification()
    catalog = class_catalog.ClassCatalog.default()
    families = {scenario_class.folder: scenario_class for scenario_class in catalog}  # one FEC per family
    assert len(families) >= 9
    for scenario_class in families.values():
        first_part = scenario_class.read_content().split("declare", 1)[0].rstrip()
        assert specification.startswith(first_part), scenario_class.class_id
    # the functional model parser splits a FEC at its first declare, so nothing before the pin may say the word
    before_pin, pin = specification.split("declare", 1)
    assert "declare" not in before_pin
    assert pin.split() == ["os.", "OS(os).", "vesselType(os,", "OSPassengerShip).", "!exists(OS::new)."]
    assert "\r" not in specification


def test_a_generated_model_counts_and_parses_as_a_catalog_fec_does():
    model = (DATA / "generated_model.problem").read_text(encoding="utf-8")
    assert count_instances(model) == class_catalog.count_instances(model) == (3, 1)
    scenario = ModelParser.parse_problem(model)
    assert scenario.vessel_number == 3 and scenario.obstacle_number == 1


def test_the_counts_agree_with_the_catalog_for_every_family():
    catalog = class_catalog.ClassCatalog.default()
    seen = set()
    for scenario_class in catalog:
        if scenario_class.folder in seen:
            continue
        seen.add(scenario_class.folder)
        assert count_instances(scenario_class.read_content()) == (scenario_class.vessel_count, scenario_class.obstacle_count)
    assert seen
