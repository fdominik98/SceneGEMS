"""The design space exploration in a campaign config: the step, its section, what the config may name beside it, and the classes it starts with."""

import pytest

from scenegems_tool.assurance.campaign import CampaignConfigError, CampaignConfigRejected, parse_campaign_config, validate_campaign_config
from scenegems_tool.assurance.campaign.campaign_config import CHAIN, DEFAULT_STEPS, CampaignStep, QueueDepthCaps, campaign_config_from_dict
from scenegems_tool.assurance.campaign.campaign_inputs import exploration_class_spec, explored_class_id, explored_class_spec, is_explored_class
from scenegems_tool.persistence.schema import PipelineStage
from scenegems_tool.persistence.stores import EXPLORATION_CLASS_ID
from scenegems_tool.subsystems.design_space_exploration.design_space import exploration_hash

SPECIFICATION = "class A.\nclass B.\n"
SECTION = {"specification": SPECIFICATION, "scope": "A = 1, B = 0..2"}
CATALOG_SCOPE = [{"fecs": ["2vessel_0obstacle_scenarios/fec0"], "quota": 1}]


def exploring(steps=("design_space_exploration", "scene_generation"), section=SECTION, **sections):
    return {"format": 3, "name": "explore", "steps": list(steps), "design_space_exploration": dict(section), **sections}


def test_the_exploration_is_the_first_step_of_the_chain_but_not_of_a_config_that_names_no_steps():
    assert CHAIN[0] == CampaignStep.DESIGN_SPACE_EXPLORATION and CHAIN[1:] == DEFAULT_STEPS
    assert campaign_config_from_dict({"name": "old", "scope": [{"classes": ["2vessel_0obstacle_scenarios/fec0"], "quota": 1}]}).steps == DEFAULT_STEPS
    assert campaign_config_from_dict({"format": 3, "name": "new", "scope": CATALOG_SCOPE}).steps == DEFAULT_STEPS


def test_the_section_has_defaults_and_keeps_the_text_with_lf_line_endings():
    config = campaign_config_from_dict(exploring(section={"specification": "class A.\r\nclass B.\r\n", "scope": "  A = 1, B = 0..2 "}))
    section = config.design_space_exploration
    assert (section.specification, section.scope) == (SPECIFICATION, "A = 1, B = 0..2")
    assert (section.max_fecs, section.timeout_s, section.quota, section.failure_budget) == (1000, 600.0, 1, 0)
    every = campaign_config_from_dict(exploring(section={**SECTION, "max_fecs": None, "failure_budget": "unlimited", "quota": 3, "timeout_s": 30})).design_space_exploration
    assert (every.max_fecs, every.failure_budget, every.quota, every.timeout_s) == (None, "unlimited", 3, 30.0)


@pytest.mark.parametrize(
    "section, reason",
    [
        ({"specification": SPECIFICATION}, "design_space_exploration.scope: Field required"),
        ({"specification": " \n", "scope": "A = 1"}, "the specification is empty"),
        ({"specification": SPECIFICATION, "scope": "A"}, "'A' is not a scope entry"),
        ({"specification": SPECIFICATION, "scope": "A = 2..1"}, "the upper bound 1 is below the lower bound 2"),
        ({**SECTION, "max_fecs": 0}, "design_space_exploration.max_fecs"),
        ({**SECTION, "timeout_s": 0}, "design_space_exploration.timeout_s"),
        ({**SECTION, "quota": 0}, "design_space_exploration.quota"),
        ({**SECTION, "failure_budget": -1}, "a failure budget is a number of cases from 0 up or 'unlimited'"),
        ({**SECTION, "seed": 1}, "design_space_exploration.seed: Extra inputs are not permitted"),
    ],
)
def test_a_section_that_cannot_be_explored_is_refused_with_the_reason(section, reason):
    with pytest.raises(CampaignConfigError) as refused:
        campaign_config_from_dict(exploring(section=section))
    assert any(reason in found for found in refused.value.reasons), refused.value.reasons


def test_a_section_without_a_specification_explores_the_one_the_control_node_ships():
    from scenegems_tool.subsystems.design_space_exploration.design_space import default_specification

    config = campaign_config_from_dict(exploring(section={"scope": "TS = 2"}))
    assert config.design_space_exploration.specification == default_specification()
    assert config.to_json()["design_space_exploration"]["specification"] == default_specification()  # pinned by the config hash


def test_the_exploration_preset_explores_the_default_specification():
    from scenegems_tool.assurance.campaign.campaign_presets import builtin_presets
    from scenegems_tool.subsystems.design_space_exploration.design_space import default_specification

    preset = next(preset for preset in builtin_presets() if preset.preset_id == "13_design_space_exploration")
    assert "specification" not in preset.config["design_space_exploration"]
    config = campaign_config_from_dict(preset.config)
    assert config.steps == CHAIN and config.design_space_exploration.specification == default_specification()
    assert config.design_space_exploration.scope == "TS = 2, StaticObstacle = 0"


def test_the_step_needs_its_section_and_format_2_or_later():
    with pytest.raises(CampaignConfigError, match="steps name design_space_exploration, which needs the design_space_exploration section"):
        campaign_config_from_dict({"format": 3, "name": "explore", "steps": ["design_space_exploration"]})
    with pytest.raises(CampaignConfigError, match="need format 2"):
        campaign_config_from_dict({"name": "old", "scope": [{"classes": ["2vessel_0obstacle_scenarios/fec0"], "quota": 1}], "design_space_exploration": SECTION})
    with pytest.raises(CampaignConfigError, match="steps must be consecutive and in chain order"):
        campaign_config_from_dict(exploring(steps=("design_space_exploration", "trajectory_generation")))


def test_a_config_without_the_section_keeps_the_json_and_the_hash_it_had():
    config = campaign_config_from_dict({"format": 3, "name": "plain", "scope": CATALOG_SCOPE})
    assert "design_space_exploration" not in config.to_json()
    old = campaign_config_from_dict({"name": "old", "scope": [{"classes": ["2vessel_0obstacle_scenarios/fec0"], "quota": 1}]})
    assert "design_space_exploration" not in old.to_json() and "steps" not in old.to_json()
    # the section is unused but kept when a config that does not explore carries it
    kept = campaign_config_from_dict({"format": 3, "name": "plain", "scope": CATALOG_SCOPE, "design_space_exploration": SECTION})
    assert kept.to_json()["design_space_exploration"]["scope"] == "A = 1, B = 0..2" and kept.config_hash() != config.config_hash()


def test_an_exploring_config_writes_its_section_and_reads_back_equal():
    config = campaign_config_from_dict(exploring())
    stored = config.to_json()
    assert stored["steps"] == ["design_space_exploration", "scene_generation"]
    assert stored["design_space_exploration"] == {"specification": SPECIFICATION, "scope": "A = 1, B = 0..2", "max_fecs": 1000, "timeout_s": 600.0, "quota": 1, "failure_budget": 0}
    assert campaign_config_from_dict(stored) == config and campaign_config_from_dict(stored).config_hash() == config.config_hash()


def test_yaml_with_a_block_specification_loads():
    config = parse_campaign_config(
        "format: 3\nname: explore\nsteps: [design_space_exploration]\ndesign_space_exploration:\n  scope: TS = 2, StaticObstacle = 0\n  specification: |\n    class OS.\n    class TS.\n"
    )
    assert config.design_space_exploration.specification == "class OS.\nclass TS.\n"
    assert config.first_step == CampaignStep.DESIGN_SPACE_EXPLORATION


def test_an_exploring_campaign_starts_with_the_exploration_class_alone():
    validated = validate_campaign_config(campaign_config_from_dict(exploring()))
    (spec,) = validated.classes
    assert spec == exploration_class_spec(validated.config.design_space_exploration)
    assert (spec.class_id, spec.quota, spec.failure_budget, spec.vessel_count, spec.obstacle_count) == (EXPLORATION_CLASS_ID, 1, 0, 0, 0)
    assert spec.content_hash == exploration_hash(SPECIFICATION, "A = 1, B = 0..2")
    assert validated.runs == ()  # no simulation step, so no run is resolved


def test_an_exploring_campaign_names_no_fecs_and_no_input():
    with pytest.raises(CampaignConfigRejected) as refused:
        validate_campaign_config(campaign_config_from_dict(exploring(scope=CATALOG_SCOPE)))
    assert refused.value.reasons == ("scope: a campaign that starts with design_space_exploration takes its FECs from the exploration, not from the catalog",)
    scenario = {"name": "mine", "ref": {"sha256": "a" * 64, "size_bytes": 1, "kind": "functional_scenario"}, "quota": 1}
    with pytest.raises(CampaignConfigRejected) as refused:
        validate_campaign_config(campaign_config_from_dict(exploring(input={"functional_scenarios": [scenario]})))
    assert "input: a campaign that starts with design_space_exploration takes its FECs from the exploration, not functional scenarios or items" in refused.value.reasons


def test_the_runs_of_an_exploring_campaign_that_simulates_are_resolved_at_creation():
    config = exploring(steps=("design_space_exploration", "scene_generation", "trajectory_generation", "simulation"), trajectories={"generator": "straight", "timespan_s": 10})
    assert len(validate_campaign_config(campaign_config_from_dict(config)).runs) == 1


def test_explored_classes_are_numbered_and_take_the_sections_quota_and_budget():
    section = campaign_config_from_dict(exploring(section={**SECTION, "quota": 4, "failure_budget": "unlimited"})).design_space_exploration
    spec = explored_class_spec(12, "b" * 64, 3, 1, section)
    assert (spec.class_id, spec.content_hash, spec.vessel_count, spec.obstacle_count, spec.quota, spec.failure_budget) == ("explored/00012", "b" * 64, 3, 1, 4, None)
    assert explored_class_id(0) == "explored/00000" and explored_class_id(123456) == "explored/123456"
    assert is_explored_class("explored/00000") and not is_explored_class(EXPLORATION_CLASS_ID) and not is_explored_class("2vessel_0obstacle_scenarios/fec0")


def test_a_campaign_explores_once_whatever_the_queue_caps():
    caps = QueueDepthCaps(generate_scene=64)
    assert caps.cap(PipelineStage.EXPLORE_DESIGN_SPACE) == 1 and caps.cap(PipelineStage.GENERATE_SCENE) == 64
    assert "explore_design_space" not in caps.model_dump()
