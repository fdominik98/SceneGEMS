import hashlib
import re
from collections import Counter
from pathlib import Path

import pytest

from scenegems_tool.assurance.campaign.class_catalog import CATALOG_FOLDER, ClassCatalog, UnknownClassId, count_instances, natural_key
from utils.file_system_utils import FUNCTIONAL_MODELS_FOLDER

FOLDER_SIZES = {
    "1vessel_0obstacle_scenarios": 1,
    "1vessel_1obstacle_scenarios": 1,
    "2vessel_0obstacle_scenarios": 7,
    "2vessel_1obstacle_scenarios": 7,
    "3vessel_0obstacle_scenarios": 28,
    "3vessel_1obstacle_scenarios": 28,
    "4vessel_0obstacle_scenarios": 84,
    "5vessel_0obstacle_scenarios": 210,
    "6vessel_0obstacle_scenarios": 462,
}
FOLDER_NAME = re.compile(r"^(\d+)vessel_(\d+)obstacle_scenarios$")
PROBLEM = """class OS extends Vessel.
declare os, ts1, obst1.
OS(os).
vesselType(os, OSPassengerShip).

TS(ts1).
StaticObstacle(obst1).
default !headOn(*, *).
"""


@pytest.fixture(scope="module")
def catalog() -> ClassCatalog:
    return ClassCatalog.default()


def test_the_catalog_has_the_828_functional_scenarios(catalog):
    assert len(catalog) == 828
    assert Counter(scenario_class.folder for scenario_class in catalog) == FOLDER_SIZES
    assert catalog.folders() == tuple(FOLDER_SIZES)


def test_the_catalog_lives_with_the_assets():
    assert CATALOG_FOLDER == Path(FUNCTIONAL_MODELS_FOLDER) / "all"
    assert CATALOG_FOLDER.is_dir()


def test_vessel_and_obstacle_counts_match_the_folders(catalog):
    for scenario_class in catalog:
        vessels, obstacles = (int(group) for group in FOLDER_NAME.match(scenario_class.folder).groups())
        assert (scenario_class.vessel_count, scenario_class.obstacle_count) == (vessels, obstacles), scenario_class.class_id


def test_class_ids_and_content_hashes(catalog):
    scenario_class = catalog.get("3vessel_0obstacle_scenarios/fec5")
    assert scenario_class.path == CATALOG_FOLDER / "3vessel_0obstacle_scenarios" / "fec5.problem"
    content = scenario_class.read_content()
    assert "\r" not in content and "OS(os)." in content
    assert scenario_class.content_hash == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert len({scenario_class.content_hash for scenario_class in catalog}) == 828
    assert "3vessel_0obstacle_scenarios/fec5" in catalog and "3vessel_0obstacle_scenarios/fec999" not in catalog
    with pytest.raises(UnknownClassId):
        catalog.get("3vessel_0obstacle_scenarios/fec999")


def test_every_file_is_named_after_its_fec_and_the_old_names_are_gone(catalog):
    assert all(re.fullmatch(r"fec\d+", scenario_class.path.stem) for scenario_class in catalog)
    assert "3vessel_0obstacle_scenarios/functional_model5" not in catalog
    with pytest.raises(UnknownClassId):
        catalog.get("3vessel_0obstacle_scenarios/functional_model5")


def test_classes_are_in_natural_order(catalog):
    ids = [scenario_class.class_id for scenario_class in catalog.expand("2vessel_0obstacle_scenarios")]
    assert ids == [f"2vessel_0obstacle_scenarios/fec{index}" for index in range(7)]
    six = [scenario_class.class_id for scenario_class in catalog.expand("6vessel_0obstacle_scenarios")]
    assert six.index("6vessel_0obstacle_scenarios/fec2") < six.index("6vessel_0obstacle_scenarios/fec10")
    assert natural_key("b10") > natural_key("b9") and natural_key("a") < natural_key("b") and natural_key("x1") != natural_key("1x")


@pytest.mark.parametrize(
    "pattern, count",
    [
        ("2vessel_*_scenarios", 14),
        ("3vessel_*_scenarios", 56),
        ("[23]vessel_*", 70),
        ("*", 828),
        ("2vessel_0obstacle_scenarios/fec1", 1),
        ("*/fec0", 9),
        ("*_1obstacle_scenarios/*", 36),
        ("7vessel_*", 0),
        ("2VESSEL_*", 0),
    ],
)
def test_patterns_expand_folders_or_class_ids(catalog, pattern, count):
    assert len(catalog.expand(pattern)) == count


def test_content_hashes_ignore_line_endings(tmp_path):
    for folder, ending in (("lf_scenarios", "\n"), ("crlf_scenarios", "\r\n")):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "fec0.problem").write_bytes(PROBLEM.replace("\n", ending).encode("utf-8"))
    catalog = ClassCatalog(tmp_path)
    lf, crlf = catalog.get("lf_scenarios/fec0"), catalog.get("crlf_scenarios/fec0")
    assert lf.content_hash == crlf.content_hash
    assert (lf.vessel_count, lf.obstacle_count) == (crlf.vessel_count, crlf.obstacle_count) == (2, 1)


def test_count_instances():
    assert count_instances(PROBLEM) == (2, 1)
    assert count_instances("// OS(os).\nTS(ts1).\nTS(ts2).\n") == (2, 0)


def test_a_missing_catalog_folder(tmp_path):
    with pytest.raises(FileNotFoundError):
        len(ClassCatalog(tmp_path / "missing"))
