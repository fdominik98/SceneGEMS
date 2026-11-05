import json

import pytest

from scenegems_tool.assurance.campaign import ClassCatalog, campaign_config_from_dict
from scenegems_tool.assurance.campaign.campaign_inputs import (
    InputContentError,
    input_of_class,
    input_source_of,
    item_class_id,
    item_class_spec,
    scenario_class_id,
    scenario_class_spec,
    scene_counts,
)
from scenegems_tool.persistence.stores import ClassSpec

CLASS = "3vessel_1obstacle_scenarios/fec5"
SHA = "cd" * 32


def actor(actor_id: int, vessel: bool) -> list:
    return [{"id": actor_id, "type": "MiniUSV" if vessel else "Buoy", "is_vessel": vessel}, {"x": 0.0, "y": 0.0}]


def scene(vessels: int, obstacles: int = 0) -> dict:
    return {"_data": [actor(index, True) for index in range(vessels)] + [actor(vessels + index, False) for index in range(obstacles)], "dcpa": None}


def _config(steps, items=(), scenarios=()):
    return campaign_config_from_dict({"format": 2, "name": "inputs", "steps": steps, "input": {"items": list(items), "functional_scenarios": list(scenarios)}})


def _item(kind="scene", pointer=None, source=None):
    return {"name": "an item", "ref": {"sha256": SHA, "size_bytes": 10, "kind": kind, "pointer": pointer}, "source": source or {"file": "scene.json"}}


def _bytes(document) -> bytes:
    return json.dumps(document).encode("utf-8")


@pytest.mark.parametrize(
    "document",
    [
        scene(2, 1),  # a bare scene
        {"scenario_name": "x", "best_scene": scene(2, 1)},  # EvaluationData
        {"scene": scene(2, 1)},
        {"initial_scene": scene(2, 1)},
        {"scene_list": [scene(2, 1), scene(2, 1)], "time_step": 5},  # Trajectories
        {"config_name": "x", "trajectories": {"scene_list": [scene(2, 1)], "time_step": 5}, "monitor_frames": []},  # TrajectoryData
    ],
)
def test_counts_come_from_the_initial_scene_of_any_document(document):
    assert scene_counts(document) == (2, 1)


@pytest.mark.parametrize("document", [[], {"name": "no scene"}, {"scene_list": []}, {"_data": [["not an actor"]]}, {"_data": [[{"id": 1}, {}]]}])
def test_documents_without_a_scene_are_refused(document):
    with pytest.raises(InputContentError):
        scene_counts(document)


def test_a_scenario_given_as_content_is_a_class_of_its_own():
    content = ClassCatalog.default().get(CLASS).read_content()
    config = _config(["scene_generation"], scenarios=[{"name": "my_head_on", "ref": {"sha256": SHA, "size_bytes": len(content), "kind": "functional_scenario"}, "quota": 3, "failure_budget": 1}])
    (scenario,) = config.input.functional_scenarios
    spec = scenario_class_spec(scenario, content.replace("\n", "\r\n").encode("utf-8"))
    assert spec == ClassSpec(class_id="scenario/my_head_on", content_hash=SHA, vessel_count=3, obstacle_count=1, quota=3, failure_budget=1)
    assert scenario_class_id("my_head_on") == "scenario/my_head_on"
    assert input_of_class(config, "scenario/my_head_on") == scenario and input_of_class(config, "scenario/other") is None


def test_a_scenario_without_vessels_is_refused():
    config = _config(["scene_generation"], scenarios=[{"name": "empty", "ref": {"sha256": SHA, "size_bytes": 1, "kind": "functional_scenario"}, "quota": 1}])
    with pytest.raises(InputContentError, match="declares no vessel"):
        scenario_class_spec(config.input.functional_scenarios[0], b"Nothing declared.\n")
    with pytest.raises(InputContentError, match="not UTF-8"):
        scenario_class_spec(config.input.functional_scenarios[0], b"\xff\xfe")


def test_an_item_is_a_class_of_quota_1_without_a_failure_budget():
    config = _config(["simulation"], items=[_item("trajectories"), _item("trajectory_data", pointer="/trajectories")])
    first, second = config.input.items
    assert item_class_spec(0, first, _bytes({"scene_list": [scene(3)], "time_step": 1})) == ClassSpec("item/0", SHA, 3, 0, 1, 0)
    # the pointer leads into the document
    assert item_class_spec(1, second, _bytes({"trajectories": {"scene_list": [scene(2, 2)], "time_step": 1}})) == ClassSpec("item/1", SHA, 2, 2, 1, 0)
    assert item_class_id(7) == "item/7"
    assert input_of_class(config, "item/1") == second and input_of_class(config, "item/2") is None and input_of_class(config, "item/x") is None
    assert input_of_class(config, CLASS) is None


@pytest.mark.parametrize(
    "content, pointer, message",
    [
        (b"not json", None, "not JSON"),
        (_bytes({"best_scene": scene(2)}), "/missing", "the pointer /missing names nothing"),
        (_bytes({"best_scene": scene(0, 2)}), None, "the scene has no vessel"),
    ],
)
def test_items_with_unusable_content_are_refused(content, pointer, message):
    (item,) = _config(["trajectory_generation"], items=[_item(pointer=pointer)]).input.items
    with pytest.raises(InputContentError, match=message):
        item_class_spec(0, item, content)


def test_an_items_source_as_a_case_stores_it():
    output = _config(["trajectory_generation"], items=[_item(source={"campaign_id": "c-1", "case_id": 12, "step": "scene_generation"})]).input.items[0]
    upload = _config(["trajectory_generation"], items=[_item()]).input.items[0]
    assert input_source_of(output) == {"campaign_id": "c-1", "case_id": 12, "step": "scene_generation"}
    assert input_source_of(upload) == {"file": "scene.json"}
