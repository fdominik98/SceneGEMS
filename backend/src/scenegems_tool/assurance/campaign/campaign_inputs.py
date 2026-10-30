"""The classes of a campaign's input: functional scenarios given as content, and items.

A functional scenario given as content is a class of its own with id scenario/<name>, its
content pinned by its reference's hash, its quota and failure budget from the config. An
item (a scene for trajectory generation, trajectories for simulation) is a class with id
item/<index>, the index of the item in input.items, its content hash the item's sha256,
quota 1 and failure budget 0. The vessel and obstacle counts are read from the content:
from the instances a functional scenario declares, or from the actors of the item's
(initial) scene.

The content comes from the artifact store; these functions take it as bytes.
"""

import json
from typing import Any, Dict, Mapping, Optional, Tuple, Union

from scenegems_tool.assurance.campaign.campaign_config import ITEM_CLASS_PREFIX, CampaignConfig, FunctionalScenarioInput, InputItem, budget_limit
from scenegems_tool.assurance.campaign.class_catalog import count_instances
from scenegems_tool.cluster.protocol.artifacts import json_pointer
from scenegems_tool.persistence.stores import ClassSpec

SCENARIO_CLASS_PREFIX = "scenario/"
SCENE_KEYS = ("best_scene", "scene", "initial_scene")  # where a document keeps its scene (EvaluationData uses best_scene)


class InputContentError(ValueError):
    """An input's content is not what its kind promises."""


def scenario_class_id(name: str) -> str:
    return f"{SCENARIO_CLASS_PREFIX}{name}"


def item_class_id(index: int) -> str:
    return f"{ITEM_CLASS_PREFIX}{index}"


def input_of_class(config: CampaignConfig, class_id: str) -> Optional[Union[FunctionalScenarioInput, InputItem]]:
    """The functional scenario or item a class of the config stands for; None for a catalog class."""
    if class_id.startswith(SCENARIO_CLASS_PREFIX):
        name = class_id[len(SCENARIO_CLASS_PREFIX) :]
        return next((scenario for scenario in config.input.functional_scenarios if scenario.name == name), None)
    if class_id.startswith(ITEM_CLASS_PREFIX):
        index = class_id[len(ITEM_CLASS_PREFIX) :]
        if index.isdigit() and int(index) < len(config.input.items):
            return config.input.items[int(index)]
    return None


def input_source_of(item: InputItem) -> Dict[str, Any]:
    """An item's source as a case stores it (scenario_case.input_source): {campaign_id, case_id, step} or {file}."""
    return item.source.model_dump(mode="json", exclude_none=True)


def _text(content: bytes) -> str:
    try:
        return content.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError as error:
        raise InputContentError(f"not UTF-8 text ({error})") from error


def _document(content: bytes, pointer: Optional[str]) -> Any:
    try:
        document = json.loads(_text(content))
    except json.JSONDecodeError as error:
        raise InputContentError(f"not JSON ({error.msg})") from error
    try:
        return json_pointer(document, pointer)
    except (KeyError, IndexError, ValueError) as error:
        raise InputContentError(f"the pointer {pointer} names nothing in the document") from error


def _scene_of(document: Any) -> Mapping[str, Any]:
    """The (initial) scene of a scene, EvaluationData, Trajectories or TrajectoryData document."""
    if isinstance(document, Mapping):
        if isinstance(document.get("_data"), list):
            return document
        for key in SCENE_KEYS:
            if isinstance(document.get(key), Mapping):
                return _scene_of(document[key])
        if isinstance(document.get("trajectories"), Mapping):
            return _scene_of(document["trajectories"])
        scenes = document.get("scene_list")
        if isinstance(scenes, list) and scenes:
            return _scene_of(scenes[0])
    raise InputContentError("no scene in the document (expected a scene, EvaluationData, trajectories or trajectory data)")


def scene_counts(document: Any) -> Tuple[int, int]:
    """(vessels, static obstacles) among the actors of the document's (initial) scene."""
    vessels = obstacles = 0
    for entry in _scene_of(document)["_data"]:
        actor = entry[0] if isinstance(entry, (list, tuple)) and entry else None
        if not isinstance(actor, Mapping) or "is_vessel" not in actor:
            raise InputContentError("a scene actor without is_vessel")
        if actor["is_vessel"]:
            vessels += 1
        else:
            obstacles += 1
    return vessels, obstacles


def scenario_class_spec(scenario: FunctionalScenarioInput, content: bytes) -> ClassSpec:
    """The class of a functional scenario given as content."""
    vessels, obstacles = count_instances(_text(content))
    if vessels < 1:
        raise InputContentError("the functional scenario declares no vessel (OS or TS)")
    return ClassSpec(
        class_id=scenario_class_id(scenario.name),
        content_hash=scenario.ref.sha256,
        vessel_count=vessels,
        obstacle_count=obstacles,
        quota=scenario.quota,
        failure_budget=budget_limit(scenario.failure_budget),
    )


def item_class_spec(index: int, item: InputItem, content: bytes) -> ClassSpec:
    """The class of the item at index in input.items: quota 1, no failure budget."""
    vessels, obstacles = scene_counts(_document(content, item.ref.pointer))
    if vessels < 1:
        raise InputContentError("the scene has no vessel")
    return ClassSpec(class_id=item_class_id(index), content_hash=item.ref.sha256, vessel_count=vessels, obstacle_count=obstacles, quota=1, failure_budget=0)
