"""The scope's syntax, the default specification, and the counts and object names of a generated model."""

from pathlib import Path

import pytest

from functional_level.models.model_parser import ModelParser
from scenegems_tool.assurance.campaign import class_catalog
from scenegems_tool.subsystems.design_space_exploration.design_space import (
    DEFAULT_SCOPE,
    ScopeError,
    catalog_object_names,
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


def test_the_objects_the_generator_named_get_the_names_of_the_catalog():
    model = (DATA / "generated_model.problem").read_text(encoding="utf-8")
    specification, generated = model.split("declare", 1)
    named = catalog_object_names(model)
    assert named == specification + "declare" + generated.replace("tS1", "ts1").replace("tS2", "ts2").replace("staticObstacle1", "obst1")
    assert "declare os.\ndeclare ts1, obst1, ts2.\n" in named
    for line in ("TS(ts1).", "StaticObstacle(obst1).", "overtakingToPort(ts1, os).", "atDangerousHeadOnSectorOf(obst1, os).", "headOn(ts2, os).", "!exists(TS::new)."):
        assert f"\n{line}\n" in named
    # the same FEC as before, and nothing left to rename
    assert count_instances(named) == (3, 1)
    assert ModelParser.parse_problem(named).fec_shape_hash() == ModelParser.parse_problem(model).fec_shape_hash()
    assert catalog_object_names(named) == named


def test_the_specification_before_the_model_keeps_its_names():
    model = "class TS.\npred near(TS tS1, TS tS2) <-> tS1 != tS2.\ndeclare tS1, tS2.\nTS(tS1).\nTS(tS2).\nnear(tS1, tS2).\n"
    assert catalog_object_names(model) == "class TS.\npred near(TS tS1, TS tS2) <-> tS1 != tS2.\ndeclare ts1, ts2.\nTS(ts1).\nTS(ts2).\nnear(ts1, ts2).\n"


def test_an_object_keeps_its_name_when_the_catalog_name_is_taken():
    model = "class TS.\nclass StaticObstacle.\ndeclare ts1.\ndeclare tS1, tS2, staticObstacle1.\nTS(ts1).\nTS(tS1).\nTS(tS2).\nStaticObstacle(staticObstacle1).\n"
    assert catalog_object_names(model) == "class TS.\nclass StaticObstacle.\ndeclare ts1.\ndeclare tS1, ts2, obst1.\nTS(ts1).\nTS(tS1).\nTS(ts2).\nStaticObstacle(obst1).\n"


def test_only_names_the_generator_gives_an_object_of_a_class_of_the_text_change():
    model = (
        "abstract class Item.\nclass Buoy extends Item.\nclass OSPassenger.\nclass AIS.\n"
        "declare alpha, tS1, buoy1, oSPassenger2, aIS1, tSx.\n"
        "Buoy(alpha).\nTS(tS1).\nBuoy(buoy1).\nOSPassenger(oSPassenger2).\nAIS(aIS1).\nBuoy(tSx).\nnext(aIS1, oSPassenger2).\n"
    )
    assert catalog_object_names(model) == (
        "abstract class Item.\nclass Buoy extends Item.\nclass OSPassenger.\nclass AIS.\n"
        "declare alpha, tS1, buoy1, osPassenger2, ais1, tSx.\n"
        "Buoy(alpha).\nTS(tS1).\nBuoy(buoy1).\nOSPassenger(osPassenger2).\nAIS(ais1).\nBuoy(tSx).\nnext(ais1, osPassenger2).\n"
    )


def test_a_text_without_a_model_and_a_catalog_fec_stay_as_they_are():
    assert catalog_object_names("class TS.\nclass StaticObstacle.\n") == "class TS.\nclass StaticObstacle.\n"
    assert catalog_object_names(default_specification()) == default_specification()
    for scenario_class in {scenario_class.folder: scenario_class for scenario_class in class_catalog.ClassCatalog.default()}.values():
        content = scenario_class.read_content()
        assert catalog_object_names(content) == content, scenario_class.class_id


def test_the_counts_agree_with_the_catalog_for_every_family():
    catalog = class_catalog.ClassCatalog.default()
    seen = set()
    for scenario_class in catalog:
        if scenario_class.folder in seen:
            continue
        seen.add(scenario_class.folder)
        assert count_instances(scenario_class.read_content()) == (scenario_class.vessel_count, scenario_class.obstacle_count)
    assert seen
