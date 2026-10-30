import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scenegems_tool.assurance.campaign.campaign_config import (
    CHAIN,
    DEFAULT_COLREGS_CONSTANTS_FILE,
    DEFAULT_OBSTACLE_TYPES_FILE,
    DEFAULT_VESSEL_TYPES_FILE,
    MAX_SEED,
    CampaignConfig,
    CampaignConfigError,
    CampaignStep,
    InputArtifactKind,
    InputConfig,
    QueueDepthCaps,
    RetentionPolicy,
    RunConfig,
    SceneGenerationConfig,
    budget_limit,
    campaign_config_from_dict,
    case_seed,
    load_campaign_config,
    parse_campaign_config,
    with_domain_defaults,
)
from scenegems_tool.cluster.node.jobs.simulation_kinematic_job import KinematicMode
from scenegems_tool.persistence.canonical_json import canonical_json
from scenegems_tool.persistence.schema import MonitorImplementation, PipelineStage, StepKind, TrajectoryGeneratorImplementation

DATA = Path(__file__).parent / "data"
EXIT_CAMPAIGN = DATA / "exit_campaign.yaml"
MINIMAL = {"name": "lab", "scope": [{"classes": ["2vessel_0obstacle_scenarios/functional_model0"], "quota": 2}]}


def _with(**sections) -> dict:
    return dict(MINIMAL, **sections)


def _reasons(data) -> str:
    with pytest.raises(CampaignConfigError) as error:
        campaign_config_from_dict(data) if isinstance(data, dict) else parse_campaign_config(data)
    return "\n".join(error.value.reasons)


# Defaults


def test_a_minimal_config_gets_the_defaults():
    config = campaign_config_from_dict(MINIMAL)
    assert config.format == 1 and config.scope[0].failure_budget == 0
    assert config.domain.colregs_constants == DEFAULT_COLREGS_CONSTANTS_FILE.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert "\r" not in config.domain.vessel_types and "MiniUSV" in config.domain.vessel_types
    assert config.domain.obstacle_types == DEFAULT_OBSTACLE_TYPES_FILE.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert (config.domain.scene_generation_timeout_s, config.domain.enforce_low_tcpa) == (60, False)
    assert (config.trajectories.generator, config.trajectories.params, config.trajectories.timeout_s) == (TrajectoryGeneratorImplementation.MONITOR_DRIVEN_RRT, {}, 1800.0)
    (run,) = config.execution.runs
    assert (run.stack.simulation_layer, run.stack.mode, run.monitor, run.repeats, run.seed, run.early_stop) == ("kinematic", KinematicMode.REPLAY, MonitorImplementation.POST_HOC, 1, None, False)
    assert (config.policy.retention, config.policy.keep_frames, config.policy.seed) == (RetentionPolicy.ALL, False, 0)
    assert config.resources.queue_depth.cap(PipelineStage.SIMULATE) == 32 and config.resources.required_labels == {}
    assert config.resources.nodes == ()  # every node
    assert DEFAULT_VESSEL_TYPES_FILE.name == "vessel_types.yaml"


def test_the_exit_campaign_sample():
    config = load_campaign_config(EXIT_CAMPAIGN)
    assert config.name == "phase 4 exit campaign"
    (entry,) = config.scope
    assert (entry.patterns, entry.quota, entry.failure_budget) == (("2vessel_*_scenarios", "3vessel_*_scenarios"), 15, 15)
    (run,) = config.execution.runs
    assert (run.name, run.stack.mode, run.monitor, run.repeats) == ("usv_navigation", KinematicMode.USV_NAVIGATION, MonitorImplementation.POST_HOC, 1)
    assert config.policy.seed == 20261025


def test_the_queue_depth_caps_cover_every_job_stage():
    caps = QueueDepthCaps(simulate=4)
    # generate_scene, monitor_scene, generate_trajectories, monitor_trajectories, simulate, monitor, calibrate; the monitors share one cap
    assert [caps.cap(stage) for stage in PipelineStage if stage != PipelineStage.VERDICT] == [16, 32, 16, 32, 4, 32, 8]
    with pytest.raises(ValueError):
        caps.cap(PipelineStage.VERDICT)


def test_the_straight_generator_and_search_parameters():
    straight = campaign_config_from_dict(_with(trajectories={"generator": "straight", "timespan_s": 600}))
    assert (straight.trajectories.generator, straight.trajectories.timespan_s) == (TrajectoryGeneratorImplementation.STRAIGHT, 600.0)
    tuned = campaign_config_from_dict(_with(trajectories={"params": {"maxIterations": 5000, "directionThreshold": 0.5, "includeMonitorResults": False}}))
    assert tuned.trajectories.params == {"maxIterations": 5000, "directionThreshold": 0.5, "includeMonitorResults": False}


def test_live_monitor_with_early_stop_and_usv_navigation_parameters():
    usv_navigation = {"goal": [100.0, 0.0], "speed": 5.0, "safety_radius": 120.0, "control_horizon": 60.0}
    config = campaign_config_from_dict(
        _with(execution={"runs": [{"stack": {"mode": "usv_navigation", "usv_navigation": usv_navigation}, "monitor": "live", "early_stop": True, "seed": 9, "repeats": 3}]})
    )
    (run,) = config.execution.runs
    assert (run.monitor, run.early_stop, run.repeats, run.stack.usv_navigation.safety_radius) == (MonitorImplementation.LIVE, True, 3, 120.0)


# Rejections


@pytest.mark.parametrize(
    "data, reason",
    [
        (dict(MINIMAL, colour="blue"), "colour: Extra inputs are not permitted"),
        (_with(scope=[{"classes": ["a/b"], "quota": 1, "weight": 2}]), "scope.0.weight: Extra inputs are not permitted"),
        (_with(scope=[]), "a format 1 config needs at least one scope entry"),
        (_with(scope=[{"quota": 1}]), "a scope entry needs fecs (classes before format 3) or patterns"),
        (_with(scope=[{"classes": ["a/b"], "quota": 0}]), "scope.0.quota: Input should be greater than or equal to 1"),
        (_with(scope=[{"classes": ["a/b"], "quota": 1, "failure_budget": -1}]), "scope.0.failure_budget: Value error, a failure budget is a number of cases from 0 up or 'unlimited', not -1"),
        (_with(scope=[{"classes": ["a/b"], "quota": 1, "failure_budget": "forever"}]), "a failure budget is a number of cases from 0 up or 'unlimited', not 'forever'"),
        (_with(scope=[{"classes": ["a/b"], "quota": 1, "failure_budget": 2.5}]), "scope.0.failure_budget: Value error"),
        ({"scope": MINIMAL["scope"]}, "name: Field required"),
        (_with(format=4), "format: Input should be 1, 2 or 3"),
        (_with(trajectories={"generator": "straight"}), "the straight generator needs timespan_s"),
        (_with(trajectories={"generator": "straight", "timespan_s": 60, "params": {"maxIterations": 5}}), "the straight generator takes no search parameters"),
        (_with(trajectories={"timespan_s": 60}), "timespan_s applies to the straight generator only"),
        (_with(trajectories={"params": {"maxIteration": 5}}), "unknown search parameters ['maxIteration']"),
        (_with(trajectories={"params": {"timespan": 60}}), "unknown search parameters ['timespan']"),
        (_with(trajectories={"generator": "astar"}), "trajectories.generator: Input should be 'monitor_driven_rrt' or 'straight'"),
        (_with(execution={"runs": []}), "execution.runs: Tuple should have at least 1 item"),
        (_with(execution={"runs": [{"early_stop": True}]}), "early_stop needs the live monitor"),
        (_with(execution={"runs": [{"monitor": "eventually"}]}), "execution.runs.0.monitor"),
        (_with(execution={"runs": [{"stack": {"simulation_layer": "mars"}}]}), "execution.runs.0.stack: Value error, unknown simulation_layer 'mars'"),
        (
            _with(execution={"runs": [{"stack": {"usv_navigation": {"goal": [1, 2], "speed": 1, "safety_radius": 1, "control_horizon": 1}}}]}),
            "usv_navigation parameters apply only to mode usv_navigation",
        ),
        (_with(execution={"runs": [{"stack": {"mode": "usv_navigation", "usv_navigation": {"goal": [1, 2]}}}]}), "execution.runs.0.stack.usv_navigation.speed: Field required"),
        (_with(execution={"runs": [{"seed": 2**31}]}), "execution.runs.0.seed: Input should be less than or equal to 2147483647"),
        (_with(policy={"seed": -1}), "policy.seed"),
        (_with(policy={"retention": "some"}), "policy.retention: Input should be 'all', 'failures' or 'verdicts_only'"),
        (_with(resources={"queue_depth": {"simulate": 0}}), "resources.queue_depth.simulate"),
        (_with(resources={"nodes": ["node-a", "node-a"]}), "resources.nodes: Value error, node ids must be distinct"),
        (_with(resources={"nodes": ["node-a", " "]}), "resources.nodes: Value error, a node id must not be empty"),
        (_with(domain={"vessel_types": "- just\n- a list\n"}), "domain.vessel_types: Value error, expected a YAML mapping"),
        (_with(domain={"colregs_constants": "a: [unclosed"}), "domain.colregs_constants: Value error, not valid YAML"),
        (_with(domain={"scene_generation_timeout_s": 0}), "domain.scene_generation_timeout_s"),
    ],
)
def test_invalid_configs_are_rejected_with_the_reason(data, reason):
    assert reason in _reasons(data)


def test_an_unlimited_failure_budget():
    config = parse_campaign_config("name: lab\nscope:\n  - patterns: [2vessel_*_scenarios]\n    quota: 3\n    failure_budget: unlimited\n")
    (entry,) = config.scope
    assert entry.failure_budget == "unlimited" and budget_limit(entry.failure_budget) is None
    assert config.to_json()["scope"][0]["failure_budget"] == "unlimited"
    assert campaign_config_from_dict(config.to_json()) == config
    numbered = campaign_config_from_dict(_with(scope=[{"patterns": ["2vessel_*_scenarios"], "quota": 3, "failure_budget": 0}]))
    assert config.config_hash() != numbered.config_hash()
    assert budget_limit(numbered.scope[0].failure_budget) == 0 and numbered.to_json()["scope"][0]["failure_budget"] == 0


def test_every_problem_is_reported():
    reasons = _reasons(_with(scope=[{"classes": ["a/b"], "quota": 0}], policy={"seed": -1}, colour="blue"))
    assert "scope.0.quota" in reasons and "policy.seed" in reasons and "colour" in reasons


@pytest.mark.parametrize(
    "text, reason",
    [
        ("name: a\nname: b\nscope: []\n", "found the key 'name' twice"),
        ("- a\n- b\n", "a campaign config is a mapping of its sections"),
        ("name: [unclosed\n", "not valid YAML"),
        ("name: !!python/object:os.system x\n", "not valid YAML"),
    ],
)
def test_yaml_is_loaded_safely_and_strictly(text, reason):
    assert reason in _reasons(text)


# Hash


def test_the_hash_is_the_sha256_of_canonical_json():
    config = campaign_config_from_dict(MINIMAL)
    assert config.config_hash() == hashlib.sha256(canonical_json(config.to_json()).encode("utf-8")).hexdigest()


def test_the_hash_does_not_depend_on_key_order_or_source():
    from_yaml = load_campaign_config(EXIT_CAMPAIGN)
    reordered = {key: value for key, value in reversed(list(from_yaml.to_json().items()))}
    assert campaign_config_from_dict(reordered).config_hash() == from_yaml.config_hash()
    assert campaign_config_from_dict(from_yaml.to_json()) == from_yaml


def test_the_hash_does_not_depend_on_line_endings():
    lf = campaign_config_from_dict(_with(domain={"colregs_constants": "A: 1\nB: 2\n"}))
    crlf = campaign_config_from_dict(_with(domain={"colregs_constants": "A: 1\r\nB: 2\r\n"}))
    assert crlf.domain.colregs_constants == "A: 1\nB: 2\n"
    assert crlf.config_hash() == lf.config_hash()


def test_the_hash_follows_every_value():
    base = campaign_config_from_dict(MINIMAL)
    changed = [
        _with(scope=[{"classes": ["2vessel_0obstacle_scenarios/functional_model0"], "quota": 3}]),
        _with(policy={"seed": 1}),
        _with(domain={"enforce_low_tcpa": True}),
        _with(execution={"runs": [{"monitor": "empty"}]}),
        _with(description="another"),
    ]
    hashes = {campaign_config_from_dict(data).config_hash() for data in changed}
    assert len(hashes) == len(changed) and base.config_hash() not in hashes


def test_the_hash_is_the_same_in_another_process():
    """No set or dict order of one interpreter leaks into the hash."""
    script = "from scenegems_tool.assurance.campaign import load_campaign_config; import sys; print(load_campaign_config(sys.argv[1]).config_hash())"
    environment = dict(os.environ, PYTHONHASHSEED="12345", PYTHONPATH=str(Path(__file__).resolve().parents[4]))
    other = subprocess.run([sys.executable, "-c", script, str(EXIT_CAMPAIGN)], capture_output=True, text=True, env=environment, check=True).stdout.strip()
    assert other == load_campaign_config(EXIT_CAMPAIGN).config_hash()


# Seeds


def test_case_seeds_count_up_from_the_campaign_seed():
    assert [case_seed(20261025, "3vessel_0obstacle_scenarios/functional_model5", index) for index in range(3)] == [20261025, 20261026, 20261027]
    assert case_seed(20261025, "2vessel_0obstacle_scenarios/functional_model1", 0) == 20261025  # every class starts at the campaign seed
    assert case_seed(MAX_SEED, "a/b", 2) == 1  # 31 bits, wrapping around


def test_an_item_counts_from_its_item_number():
    assert [case_seed(100, f"item/{index}", 0) for index in range(3)] == [100, 101, 102]
    assert case_seed(100, "scenario/item/5", 1) == 101  # only an item class id counts its number


def test_seeds_are_deterministic():
    config = load_campaign_config(EXIT_CAMPAIGN)
    assert config.case_seed("2vessel_0obstacle_scenarios/functional_model1", 3) == case_seed(20261025, "2vessel_0obstacle_scenarios/functional_model1", 3) == 20261028


def test_a_run_takes_the_case_seed_unless_it_fixes_one():
    assert RunConfig().seed_for(555) == 555
    assert RunConfig(seed=17).seed_for(555) == 17


def test_indexes_start_at_zero():
    with pytest.raises(ValueError):
        case_seed(0, "a/b", -1)


def test_the_model_is_immutable():
    config = campaign_config_from_dict(MINIMAL)
    with pytest.raises(Exception):
        config.name = "other"
    assert isinstance(config, CampaignConfig)


# Format 2: steps, input, step monitors

EXIT_CAMPAIGN_HASH = "663cec9bbe4fd64ec99d6c57dff036d8538c038c6ebb6be20dd2a0786a8822c5"  # as stored by campaigns created before format 2
MINIMAL_HASH = "a56ef19560d6b58abe2cee6ab125e276f315e76dd3677e742da62967a5a6d7df"
SHA = "ab" * 32
SCENARIO_REF = {"sha256": SHA, "size_bytes": 120, "kind": "functional_scenario", "media_type": "text/plain; charset=utf-8"}
SCENE_ITEM = {"name": "case 12 scene", "ref": {"sha256": SHA, "size_bytes": 900, "kind": "scene"}, "source": {"campaign_id": "c-1", "case_id": 12, "step": "scene_generation"}}


def _format2(**sections) -> dict:
    return dict({"format": 2, "name": "partial"}, **sections)


def test_format_1_hashes_stay_what_they_were():
    """Existing campaigns keep their stored hashes: a format 1 config hashes without the format 2 fields."""
    exit_campaign = load_campaign_config(EXIT_CAMPAIGN)
    assert exit_campaign.config_hash() == EXIT_CAMPAIGN_HASH
    assert campaign_config_from_dict(MINIMAL).config_hash() == MINIMAL_HASH
    stored = exit_campaign.to_json()
    assert not {"steps", "input", "scene_generation"} & set(stored) and "monitor" not in stored["trajectories"]
    assert campaign_config_from_dict(stored).config_hash() == EXIT_CAMPAIGN_HASH


def test_a_format_1_config_is_the_full_chain():
    config = load_campaign_config(EXIT_CAMPAIGN)
    assert config.format == 1 and config.steps == CHAIN and config.first_step == CampaignStep.SCENE_GENERATION
    assert config.input == InputConfig() and config.scene_generation.monitor == MonitorImplementation.EMPTY and config.trajectories.monitor == MonitorImplementation.EMPTY
    assert all(config.runs_step(step) for step in CampaignStep)


@pytest.mark.parametrize(
    "sections, reason",
    [
        ({"steps": ["scene_generation"]}, "steps need format 2"),
        ({"input": {}}, "input need format 2"),
        ({"scene_generation": {"monitor": "post_hoc"}}, "scene_generation need format 2"),
        ({"trajectories": {"monitor": "empty"}}, "trajectories.monitor need format 2"),
    ],
)
def test_format_1_takes_no_format_2_fields(sections, reason):
    assert reason in _reasons(_with(**sections))


def test_a_format_2_config_with_steps_and_monitors():
    config = campaign_config_from_dict(
        _format2(
            steps=["scene_generation", "trajectory_generation"],
            scope=MINIMAL["scope"],
            scene_generation={"monitor": "post_hoc"},
            trajectories={"generator": "straight", "timespan_s": 600, "monitor": "post_hoc"},
        )
    )
    assert config.steps == (CampaignStep.SCENE_GENERATION, CampaignStep.TRAJECTORY_GENERATION) and not config.runs_step(CampaignStep.SIMULATION)
    assert (config.scene_generation.monitor, config.trajectories.monitor) == (MonitorImplementation.POST_HOC, MonitorImplementation.POST_HOC)
    stored = config.to_json()
    assert stored["steps"] == ["scene_generation", "trajectory_generation"] and stored["trajectories"]["monitor"] == "post_hoc"
    assert campaign_config_from_dict(stored) == config and campaign_config_from_dict(stored).config_hash() == config.config_hash()


def test_format_2_defaults():
    config = campaign_config_from_dict(_format2(scope=MINIMAL["scope"]))
    assert config.steps == CHAIN and config.input == InputConfig() and config.scene_generation == SceneGenerationConfig()
    assert config.config_hash() != campaign_config_from_dict(MINIMAL).config_hash()  # the format and the new fields are hashed


def test_format_3_lists_a_scope_entry_s_fecs_under_fecs():
    entry = {"fecs": ["2vessel_0obstacle_scenarios/functional_model0"], "patterns": ["3vessel_*"], "quota": 2}
    config = campaign_config_from_dict(_format2(format=3, scope=[entry]))
    assert config.scope[0].fecs == ("2vessel_0obstacle_scenarios/functional_model0",)
    stored = config.to_json()
    assert stored["format"] == 3 and stored["scope"][0]["fecs"] == ["2vessel_0obstacle_scenarios/functional_model0"] and "classes" not in stored["scope"][0]
    assert campaign_config_from_dict(stored) == config and campaign_config_from_dict(stored).config_hash() == config.config_hash()
    yaml_text = "format: 3\nname: lab\nscope:\n  - fecs: [2vessel_0obstacle_scenarios/functional_model0]\n    quota: 1\n"
    assert parse_campaign_config(yaml_text).scope[0].fecs == ("2vessel_0obstacle_scenarios/functional_model0",)


def test_formats_1_and_2_keep_the_name_classes():
    for config_format in (1, 2):
        config = campaign_config_from_dict(dict(MINIMAL, format=config_format))
        assert config.scope[0].fecs == ("2vessel_0obstacle_scenarios/functional_model0",)
        stored = config.to_json()
        assert stored["scope"][0]["classes"] == ["2vessel_0obstacle_scenarios/functional_model0"] and "fecs" not in stored["scope"][0]
        assert campaign_config_from_dict(stored).config_hash() == config.config_hash()


@pytest.mark.parametrize(
    "data, reason",
    [
        (_format2(format=3, scope=[{"classes": ["a/b"], "quota": 1}]), "scope.0: format 3 calls them fecs, not classes"),
        (_format2(scope=[{"fecs": ["a/b"], "quota": 1}, {"fecs": ["a/c"], "quota": 1}]), "scope.0, scope.1: fecs need format 3; formats 1 and 2 call them classes"),
        (_with(scope=[{"fecs": ["a/b"], "quota": 1}]), "fecs need format 3"),
    ],
)
def test_a_scope_entry_takes_the_name_of_its_format(data, reason):
    assert reason in _reasons(data)


def test_the_step_kinds():
    assert [step.step_kind for step in CHAIN] == [StepKind.SCENE, StepKind.TRAJECTORIES, StepKind.SIMULATION]


def test_input_with_scenarios_and_items():
    upload = {"name": "upload", "ref": {"sha256": SHA, "size_bytes": 5, "kind": "scene", "pointer": "/best_scene"}, "source": {"file": "head_on.json"}}
    config = campaign_config_from_dict(_format2(steps=["trajectory_generation"], input={"items": [SCENE_ITEM, upload]}))
    first, second = config.input.items
    assert (first.ref.kind, first.ref.media_type, first.ref.pointer, first.source.case_id, first.source.step) == (InputArtifactKind.SCENE, "application/json", None, 12, CampaignStep.SCENE_GENERATION)
    assert (second.source.file, second.source.campaign_id, second.ref.pointer) == ("head_on.json", None, "/best_scene")
    scenarios = campaign_config_from_dict(_format2(input={"functional_scenarios": [{"name": "my_head_on", "ref": SCENARIO_REF, "quota": 3, "failure_budget": 1}]}))
    (scenario,) = scenarios.input.functional_scenarios
    assert (scenario.name, scenario.quota, scenario.failure_budget, scenario.ref.sha256) == ("my_head_on", 3, 1, SHA)
    unlimited = campaign_config_from_dict(_format2(input={"functional_scenarios": [{"name": "my_head_on", "ref": SCENARIO_REF, "quota": 3, "failure_budget": "unlimited"}]}))
    assert budget_limit(unlimited.input.functional_scenarios[0].failure_budget) is None


@pytest.mark.parametrize(
    "data, reason",
    [
        (_format2(steps=[]), "a campaign runs at least one step"),
        (_format2(steps=["scene_generation", "simulation"]), "steps must be consecutive and in chain order"),
        (_format2(steps=["trajectory_generation", "scene_generation"]), "steps must be consecutive and in chain order"),
        (_format2(steps=["simulation", "simulation"]), "steps must be consecutive and in chain order"),
        (_format2(steps=["planning"]), "steps.0: Input should be 'scene_generation', 'trajectory_generation' or 'simulation'"),
        (_format2(scene_generation={"monitor": "live"}), "monitored post_hoc or not at all"),
        (_format2(trajectories={"monitor": "live"}), "monitored post_hoc or not at all"),
        (_format2(input={"functional_scenarios": [{"name": "a/b", "ref": SCENARIO_REF, "quota": 1}]}), "input.functional_scenarios.0.name: String should match pattern"),
        (_format2(input={"functional_scenarios": [{"name": "a", "ref": dict(SCENARIO_REF, kind="scene"), "quota": 1}]}), "has kind functional_scenario, not scene"),
        (
            _format2(input={"functional_scenarios": [{"name": "a", "ref": SCENARIO_REF, "quota": 1}, {"name": "a", "ref": SCENARIO_REF, "quota": 2}]}),
            "functional scenario names must be distinct: ['a']",
        ),
        (_format2(input={"functional_scenarios": [{"name": "a", "ref": SCENARIO_REF, "quota": 0}]}), "input.functional_scenarios.0.quota"),
        (_format2(input={"functional_scenarios": [{"name": "a", "ref": SCENARIO_REF, "quota": 1, "failure_budget": "none"}]}), "input.functional_scenarios.0.failure_budget: Value error"),
        (_format2(input={"items": [dict(SCENE_ITEM, ref={"sha256": "AB" * 32, "size_bytes": 1, "kind": "scene"})]}), "input.items.0.ref.sha256: String should match pattern"),
        (_format2(input={"items": [dict(SCENE_ITEM, ref={"sha256": SHA, "kind": "scene"})]}), "input.items.0.ref.size_bytes: Field required"),
        (_format2(input={"items": [dict(SCENE_ITEM, ref={"sha256": SHA, "size_bytes": 1, "kind": "frames"})]}), "input.items.0.ref.kind"),
        (_format2(input={"items": [dict(SCENE_ITEM, ref={"sha256": SHA, "size_bytes": 1, "kind": "scene", "pointer": "best_scene"})]}), "a JSON pointer starts with '/'"),
        (_format2(input={"items": [dict(SCENE_ITEM, source={"campaign_id": "c-1", "step": "scene_generation"})]}), "an item's source is {campaign_id, case_id, step} or {file}"),
        (_format2(input={"items": [dict(SCENE_ITEM, source={"file": "a.json", "case_id": 3})]}), "an item comes from a file or from a campaign's output, not both"),
        (_format2(input={"items": [dict(SCENE_ITEM, source={})]}), "an item's source is {campaign_id, case_id, step} or {file}"),
        (_format2(input={"items": [dict(SCENE_ITEM, colour="blue")]}), "input.items.0.colour: Extra inputs are not permitted"),
    ],
)
def test_invalid_format_2_configs_are_rejected_with_the_reason(data, reason):
    assert reason in _reasons(data)


CLUSTER_DOMAIN = {"colregs_constants": "SAFE_DISTANCE: 400\n", "vessel_types": "Ferry:\n  max_speed: 12\n", "obstacle_types": "Buoy:\n  radius: 2\n"}


def test_domain_defaults_fill_only_the_contents_a_config_leaves_out():
    config = parse_campaign_config("format: 2\nname: lab\ndomain:\n  vessel_types: 'Tug: {max_speed: 6}'\n  scene_generation_timeout_s: 90\n", CLUSTER_DOMAIN)
    assert config.domain.colregs_constants == CLUSTER_DOMAIN["colregs_constants"]
    assert config.domain.obstacle_types == CLUSTER_DOMAIN["obstacle_types"]
    assert config.domain.vessel_types == "Tug: {max_speed: 6}"  # the config's own content wins
    assert config.domain.scene_generation_timeout_s == 90
    assert parse_campaign_config("format: 2\nname: lab\n", CLUSTER_DOMAIN).domain.vessel_types == CLUSTER_DOMAIN["vessel_types"]


def test_without_domain_defaults_the_default_presets_apply():
    assert parse_campaign_config("format: 2\nname: lab\n").domain.colregs_constants == DEFAULT_COLREGS_CONSTANTS_FILE.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert with_domain_defaults({"name": "lab"}, None) == {"name": "lab"}


def test_a_domain_section_that_is_no_mapping_is_left_for_validation_to_report():
    assert with_domain_defaults({"domain": "colregs"}, CLUSTER_DOMAIN) == {"domain": "colregs"}
    with pytest.raises(CampaignConfigError):
        parse_campaign_config("format: 2\nname: lab\ndomain: colregs\n", CLUSTER_DOMAIN)
