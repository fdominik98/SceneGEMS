"""The scene generation document names what the worker runs: its literals are checked against the code."""

from pathlib import Path

from logical_level.constraint_satisfaction.aggregates import AggregateAll
from logical_level.constraint_satisfaction.rejection_sampling.rejection_sampling_pipeline import TwoStepCDRejectionSampling
from logical_level.mapping.instance_initializer import RandomInstanceInitializer
from scenegems_tool.subsystems.scene_generation import scene_generation_specs as specs
from scenegems_tool.subsystems.scene_generation.scene_generation_specs import scene_generation_document
from scenegems_tool.subsystems.scene_generation.scene_generation_worker import _MSR_CDRS_PS
from utils.file_system_utils import BACKEND_ROOT

SOURCE_ROOT = Path(BACKEND_ROOT) / "src"


def test_the_literals_match_the_classes_and_constants_the_worker_uses():
    assert specs.INITIALIZER_NAME == RandomInstanceInitializer.name
    assert specs.AGGREGATE_NAME == AggregateAll.name
    assert specs.SOLVER_ALGORITHM == TwoStepCDRejectionSampling.algorithm_desc()
    assert specs.CONFIG_GROUP == _MSR_CDRS_PS


def test_the_pipeline_runs_from_the_request_through_the_parser_to_the_scene_builder():
    document = scene_generation_document()
    assert [lane.id for lane in document.lanes] == ["entry", "model", "problem", "solver", "output"]
    edges = {(edge.source.split("/")[1], edge.target.split("/")[1]) for edge in document.edges}
    assert {("request", "parser"), ("parser", "builder"), ("uniform_initializer", "two_step_cd_rejection_sampling"), ("two_step_cd_rejection_sampling", "scene_builder")} <= edges


def test_every_interface_of_the_metamodel_is_implemented_by_the_live_pipeline():
    document = scene_generation_document()
    implemented = {node.implements for node in document.nodes}
    assert {node.id for node in document.metamodel_nodes} <= implemented


def test_every_code_location_exists():
    for node in scene_generation_document().nodes:
        for fact in node.facts:
            if fact.key == "code":
                assert (SOURCE_ROOT / str(fact.value)).exists(), fact.value
    for meta in scene_generation_document().metamodel_nodes:
        assert meta.code is None or (SOURCE_ROOT / meta.code).exists(), meta.code


def test_the_request_says_how_the_pool_runs_it():
    document = scene_generation_document()
    [request] = [node for node in document.nodes if node.lane == "entry"]
    facts = {fact.key: fact.value for fact in request.facts}
    assert (request.id, facts["request"], facts["tasks"]) == ("scene_generation/request", "generate-scene", "one per request: the search for one scene")
    assert "slots" in facts["pool"] and "seed" in facts["seed"] and "sensor/generated_scene" in facts["publishes"] and "queued" in facts["task_states"]
