import pytest
import yaml

from scenegems_tool.assurance.campaign import CampaignConfigError, parse_campaign_config, validate_campaign_config
from scenegems_tool.assurance.campaign.campaign_config import CampaignStep
from scenegems_tool.assurance.campaign.campaign_presets import NO_INPUT_REASON, builtin_presets, preset_config

MINIMAL = {"format": 2, "name": "lab", "steps": ["simulation"]}


def test_the_shipped_presets_are_named_ordered_and_distinct():
    presets = builtin_presets()
    assert len(presets) >= 10
    ids = [preset.preset_id for preset in presets]
    assert ids == sorted(ids) and ids[0] == "01_smoke_test"
    names = [preset.name for preset in presets]
    assert len(set(names)) == len(names)
    assert all(preset.description and preset.config["name"] == preset.name for preset in presets)


def test_the_shipped_presets_validate_and_hold_no_input():
    """A preset that starts with the design space exploration or with scene generation is a complete campaign; a later start lacks only the input the operator picks."""
    for preset in builtin_presets():
        assert "input" not in preset.config
        config = parse_campaign_config(yaml.safe_dump(preset.config))
        if config.first_step == CampaignStep.DESIGN_SPACE_EXPLORATION:
            assert [spec.class_id for spec in validate_campaign_config(config).classes] == ["exploration"], preset.preset_id
        elif config.first_step == CampaignStep.SCENE_GENERATION:
            assert validate_campaign_config(config).classes, preset.preset_id
        else:
            with pytest.raises(CampaignConfigError) as refused:
                validate_campaign_config(config)
            assert all(reason.startswith("input.items") for reason in refused.value.reasons), preset.preset_id


def test_the_shipped_presets_cover_every_step_start_and_simulator():
    presets = builtin_presets()
    assert {preset.config["steps"][0] for preset in presets} == {"design_space_exploration", "scene_generation", "simulation"}
    assert {tuple(preset.config["steps"]) for preset in presets} >= {("scene_generation",), ("scene_generation", "trajectory_generation")}
    layers = {run["stack"]["simulation_layer"] for preset in presets for run in preset.config.get("execution", {}).get("runs", [])}
    assert layers == {"kinematic", "ardupilot_sim", "gazebo"}


def test_a_preset_config_is_yaml_text_or_a_mapping():
    data, model = preset_config(yaml.safe_dump(MINIMAL))
    assert data == MINIMAL and model.name == "lab"
    assert preset_config(MINIMAL)[0] == MINIMAL


@pytest.mark.parametrize(
    "config, reason",
    [
        ({**MINIMAL, "input": {"items": []}}, NO_INPUT_REASON),
        ({**MINIMAL, "steps": ["planning"]}, "steps.0"),
        ("name: [", "not valid YAML"),
    ],
)
def test_a_preset_is_a_config_that_loads_without_input(config, reason):
    with pytest.raises(CampaignConfigError) as refused:
        preset_config(config)
    assert any(reason in item for item in refused.value.reasons)


def test_presets_are_the_yaml_files_of_the_folder_in_number_order(tmp_path):
    (tmp_path / "10_later.yaml").write_text(yaml.safe_dump({**MINIMAL, "name": "later"}), encoding="utf-8")
    (tmp_path / "2_first.yaml").write_text(yaml.safe_dump({**MINIMAL, "name": "first", "description": "the first"}), encoding="utf-8")
    (tmp_path / "readme.txt").write_text("not a preset", encoding="utf-8")
    assert [(preset.preset_id, preset.name, preset.description) for preset in builtin_presets(tmp_path)] == [("2_first", "first", "the first"), ("10_later", "later", "")]
    assert builtin_presets(tmp_path / "missing") == ()
