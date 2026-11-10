"""Payloads from the config, the case's input and earlier results, inline and with references, checked by their job type's models."""

import json

import pytest

from scenegems_tool.assurance.campaign import ClassCatalog, campaign_config_from_dict
from scenegems_tool.assurance.pipeline.payload_builder import (
    PayloadBuilder,
    PayloadError,
    required_fingerprints,
    scenario_content_of,
    trajectories_of_trajectory_result,
    validate_payload,
)
from scenegems_tool.assurance.pipeline.stage_graph import SCENE_MONITOR_STEP, SCENE_STEP, TRAJECTORIES_MONITOR_STEP, Step
from scenegems_tool.cluster.fingerprints.components import SCENARIO_EXECUTION_IMAGE, SCENE_GENERATION_IMAGE
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.persistence.schema import PipelineStage
from tests.scenegems_tool.assurance.pipeline.conftest import CLASS_A, config_dict, format2_dict
from tests.scenegems_tool.assurance.pipeline.fake_executor import EXPECTED
from tests.scenegems_tool.cluster.payloads import trajectories_data
from utils.image_names import image_repository

REFERENCE = {"sha256": "ab" * 32, "size_bytes": 2048, "kind": "trajectory_data", "media_type": "application/json", "pointer": None}


def _builder(**overrides) -> PayloadBuilder:
    return PayloadBuilder(campaign_config_from_dict(config_dict(**overrides)))


def test_the_scene_payload_carries_the_class_the_domain_and_the_case_seed():
    builder = _builder()
    content_hash = ClassCatalog.default().get(CLASS_A).content_hash
    payload = builder.scene_generation(CLASS_A, content_hash, 1234)
    assert payload["seed"] == 1234 and payload["timeout_s"] == 60 and payload["enforce_low_tcpa"] is False
    assert payload["functional_scenario_content"] == ClassCatalog.default().get(CLASS_A).read_content()
    assert payload["colregs_constraints_content"] == builder.config.domain.colregs_constants
    validate_payload(JobType.SCENE_GENERATION, payload)
    with pytest.raises(PayloadError, match="has changed in the catalog"):
        builder.scene_generation(CLASS_A, "0" * 64, 1234)


def test_the_trajectory_payload_takes_the_scene_inline_as_text_or_as_its_reference():
    builder = _builder()
    inline = builder.trajectory_generation(5, {"valid": True, "evaluation_data": {"best_scene": {"b": 1, "a": 2}}})
    assert json.loads(inline["scenario_content"]) == {"best_scene": {"b": 1, "a": 2}}
    assert inline["params"] == {"generator": "straight", "timespan": 10.0} and inline["seed"] == 5 and inline["timeout_s"] == 1800.0  # the case seed
    referenced = builder.trajectory_generation(5, {"valid": True, "evaluation_data": dict(REFERENCE, kind="scene")})
    assert referenced["scenario_content"]["sha256"] == REFERENCE["sha256"]
    for payload in (inline, referenced):
        validate_payload(JobType.TRAJECTORY_GENERATION, payload)
    with pytest.raises(PayloadError, match="no evaluation_data"):
        scenario_content_of({"valid": True})


def test_the_search_generator_sends_its_parameters():
    builder = _builder(trajectories={"generator": "monitor_driven_rrt", "params": {"maxIterations": 50}, "timeout_s": 60})
    payload = builder.trajectory_generation(5, {"evaluation_data": {}})
    assert payload["params"] == {"generator": "monitor_driven_rrt", "maxIterations": 50} and payload["timeout_s"] == 60.0
    validate_payload(JobType.TRAJECTORY_GENERATION, payload)


def test_the_simulation_takes_the_trajectories_inline_or_through_a_pointer():
    builder = _builder(runs=[{"monitor": "live", "early_stop": True, "stack": {"mode": "usv_navigation", "dt": 1.0}}])
    inline = builder.simulation(5, 0, {"trajectory_data": {"trajectories": trajectories_data()}})
    assert inline["trajectories"] == trajectories_data()
    assert (inline["mode"], inline["monitor"], inline["early_stop"], inline["dt"]) == ("usv_navigation", "live", True, 1.0)
    assert inline["seed"] == 5  # the case seed
    assert inline["colregs_constraints_content"] == builder.config.domain.colregs_constants
    referenced = builder.simulation(5, 0, {"trajectory_data": REFERENCE})
    assert referenced["trajectories"] == dict(REFERENCE, pointer="/trajectories")
    for payload in (inline, referenced):
        validate_payload(JobType.SIMULATION, payload)
    assert trajectories_of_trajectory_result({"trajectory_data": dict(REFERENCE, pointer="/result")})["pointer"] == "/result/trajectories"


def test_a_run_without_the_live_monitor_runs_none():
    payload = _builder(runs=[{"monitor": "empty"}]).simulation(5, 0, {"trajectory_data": {"trajectories": trajectories_data()}})
    assert "monitor" not in payload and "early_stop" not in payload


def test_monitoring_and_calibration_take_the_state_logs():
    builder = _builder(policy={"keep_frames": True})
    log = dict(REFERENCE, kind="trajectories")
    monitoring = builder.post_hoc_monitoring("case#0#run0", {"trajectories": log})
    assert monitoring["trajectories"] == log and monitoring["include_frames"] is True and monitoring["scenario_id"] == "case#0#run0"
    validate_payload(JobType.MONITORING_POST_HOC, monitoring)
    calibration = builder.calibration("case#0", {"mode": "replay"}, [{"trajectories": log}, {"trajectories": trajectories_data()}])
    assert calibration["trajectories"][0] == log and calibration["reference"] == "case#0"
    validate_payload(JobType.CALIBRATION_DEVIATION, calibration)


def test_a_submission_requires_the_pinned_fingerprints_of_its_images_and_the_labels():
    builder = _builder(resources={"required_labels": {"site": "lab"}, "priority": 5})
    payload = builder.scene_generation(CLASS_A, ClassCatalog.default().get(CLASS_A).content_hash, 3)
    submission = builder.submission(SCENE_STEP, payload, "key", EXPECTED)
    assert submission.requirements.fingerprints == {image_repository(SCENE_GENERATION_IMAGE): EXPECTED[SCENE_GENERATION_IMAGE]}
    assert submission.requirements.labels == {"site": "lab"} and submission.priority == 5 and submission.idempotency_key == "key"
    assert submission.allowed_worker_nodes == []  # any worker node
    assert submission.requirements.components == ["scene_generation"]
    assert required_fingerprints(["calibration"], EXPECTED) == {image_repository(SCENARIO_EXECUTION_IMAGE): "fp-execution"}
    with pytest.raises(PayloadError, match="invalid simulation payload"):
        builder.submission(Step(PipelineStage.SIMULATE, 0, 0), {"trajectories": {"scene_list": []}}, "key", EXPECTED)


def test_a_pin_from_before_release_tags_holds_for_a_release_s_images():
    pinned = {f"{image_repository(SCENE_GENERATION_IMAGE)}:latest": "pinned-under-latest"}
    assert required_fingerprints(["scene_generation"], pinned) == {image_repository(SCENE_GENERATION_IMAGE): "pinned-under-latest"}


def test_a_submission_names_the_campaigns_selected_worker_nodes():
    builder = _builder(resources={"worker_nodes": ["lab-1", "lab-3"]})
    payload = builder.scene_generation(CLASS_A, ClassCatalog.default().get(CLASS_A).content_hash, 3)
    submission = builder.submission(SCENE_STEP, payload, "key", EXPECTED)
    assert submission.allowed_worker_nodes == ["lab-1", "lab-3"] and submission.requirements.labels == {}


def test_every_step_of_a_case_runs_with_the_case_seed_unless_a_run_fixes_its_own():
    builder = _builder(runs=[{"monitor": "post_hoc"}, {"monitor": "post_hoc", "seed": 17}])
    scene = builder.scene_generation(CLASS_A, ClassCatalog.default().get(CLASS_A).content_hash, 42)
    trajectories = builder.trajectory_generation(42, {"valid": True, "evaluation_data": {"best_scene": {}}})
    runs = [builder.simulation(42, run_index, {"trajectory_data": {"trajectories": trajectories_data()}}) for run_index in (0, 1)]
    assert [scene["seed"], trajectories["seed"], runs[0]["seed"], runs[1]["seed"]] == [42, 42, 42, 17]


# Partial campaigns

SCENARIO_REF = {"sha256": "12" * 32, "size_bytes": 40, "kind": "functional_scenario", "media_type": "text/plain; charset=utf-8", "pointer": None}
SCENE_REF = {"sha256": "34" * 32, "size_bytes": 900, "kind": "scene", "media_type": "application/json", "pointer": None}
FILE = {"file": "upload.json"}


def _format2_builder(steps, **sections) -> PayloadBuilder:
    return PayloadBuilder(campaign_config_from_dict(format2_dict(steps, **sections)))


def _item(ref, name="item") -> dict:
    return {"name": name, "ref": ref, "source": FILE}


def test_a_scenario_given_as_content_goes_out_as_its_reference():
    builder = _format2_builder(["scene_generation"], input={"functional_scenarios": [{"name": "mine", "ref": SCENARIO_REF, "quota": 1}]})
    payload = builder.scene_generation("scenario/mine", SCENARIO_REF["sha256"], 9)
    assert payload["functional_scenario_content"] == SCENARIO_REF and payload["seed"] == 9
    validate_payload(JobType.SCENE_GENERATION, payload)  # a reference is checked for its shape only
    with pytest.raises(PayloadError, match="pinned"):
        builder.scene_generation("scenario/mine", "0" * 64, 9)
    catalog = builder.scene_generation(CLASS_A, ClassCatalog.default().get(CLASS_A).content_hash, 9)
    assert isinstance(catalog["functional_scenario_content"], str)  # catalog classes keep their inline text


def test_a_scene_item_feeds_trajectory_generation():
    builder = _format2_builder(["trajectory_generation", "simulation"], input={"items": [_item(SCENE_REF)]})
    item = builder.config.input.items[0]
    payload = builder.trajectory_generation_of_item(5, item)
    assert payload["scenario_content"] == SCENE_REF and payload["seed"] == 5
    validate_payload(JobType.TRAJECTORY_GENERATION, payload)
    with pytest.raises(PayloadError, match="not trajectories"):
        builder.simulation_of_item(5, 0, item)
    with pytest.raises(PayloadError, match="is an item"):
        builder.scene_generation("item/0", SCENE_REF["sha256"], 5)


@pytest.mark.parametrize(
    "kind, pointer, sent",
    [("trajectory_data", None, "/trajectories"), ("trajectory_data", "/trajectories", "/trajectories"), ("trajectories", None, None), ("trajectories", "/runs/0", "/runs/0")],
)
def test_a_trajectories_item_feeds_the_simulation(kind, pointer, sent):
    ref = dict(REFERENCE, kind=kind, pointer=pointer)
    builder = _format2_builder(["simulation"], input={"items": [_item(ref)]})
    item = builder.config.input.items[0]
    payload = builder.simulation_of_item(5, 0, item)
    assert payload["trajectories"] == dict(ref, pointer=sent) and payload["seed"] == 5
    validate_payload(JobType.SIMULATION, payload)
    with pytest.raises(PayloadError, match="not a scene"):
        builder.trajectory_generation_of_item(5, item)


@pytest.mark.parametrize("keep_frames", [True, False])
def test_the_scene_and_trajectory_monitors_judge_the_generated_outputs(keep_frames):
    builder = _format2_builder(["scene_generation", "trajectory_generation"], policy={"keep_frames": keep_frames})
    inline = builder.scene_monitoring("c#0#scene", {"evaluation_data": {"best_scene": {"_data": []}}})
    assert inline["scene"] == {"best_scene": {"_data": []}} and "trajectories" not in inline
    referenced = builder.scene_monitoring("c#0#scene", {"evaluation_data": SCENE_REF})
    assert referenced["scene"] == SCENE_REF and referenced["scenario_id"] == "c#0#scene"
    planned = builder.trajectory_monitoring("c#0#trajectories", {"trajectory_data": REFERENCE})
    assert planned["trajectories"] == dict(REFERENCE, pointer="/trajectories") and "scene" not in planned
    for payload in (inline, referenced, planned):
        assert payload["include_frames"] is keep_frames and payload["colregs_constraints_content"] == builder.config.domain.colregs_constants
        validate_payload(JobType.MONITORING_POST_HOC, payload)
    with pytest.raises(PayloadError, match="no evaluation_data"):
        builder.scene_monitoring("c#0#scene", {"valid": False})


def test_monitor_submissions_take_their_graphs_priorities():
    builder = _format2_builder(
        ["scene_generation", "trajectory_generation", "simulation"],
        scene_generation={"monitor": "post_hoc"},
        trajectories={"generator": "straight", "timespan_s": 10, "monitor": "post_hoc"},
        resources={"priority": 10},
    )
    scene = builder.submission(SCENE_MONITOR_STEP, builder.scene_monitoring("c", {"evaluation_data": SCENE_REF}), "k1", EXPECTED)
    planned = builder.submission(TRAJECTORIES_MONITOR_STEP, builder.trajectory_monitoring("c", {"trajectory_data": REFERENCE}), "k2", EXPECTED)
    simulate = builder.submission(Step(PipelineStage.SIMULATE, 0, 0), builder.simulation(1, 0, {"trajectory_data": REFERENCE}), "k3", EXPECTED)
    assert (scene.priority, planned.priority, simulate.priority) == (11, 13, 14)
    assert scene.job_type == JobType.MONITORING_POST_HOC and set(scene.requirements.fingerprints) == set(required_fingerprints(["monitoring"], EXPECTED))
