from scenegems_tool.assurance.campaign.campaign_config import DEFAULT_COLREGS_CONSTANTS_FILE, DEFAULT_OBSTACLE_TYPES_FILE, DEFAULT_VESSEL_TYPES_FILE, DomainConfig
from scenegems_tool.assurance.campaign.domain_presets import DEFAULT_PRESETS, DOMAIN_KEYS, PRESET_FOLDERS, default_domain, domain_presets


def test_the_shipped_presets_have_one_default_per_key():
    presets = domain_presets()
    assert set(presets) == set(DOMAIN_KEYS)
    for key, found in presets.items():
        assert [preset.name for preset in found if preset.default] == [DEFAULT_PRESETS[key]]
        assert all(preset.key == key and "\r" not in preset.content for preset in found)
    assert {preset.name for preset in presets["colregs_constants"]} >= {"general_maritime_constants", "wara_ps_constants"}


def test_the_default_domain_is_what_a_campaign_config_defaults_to():
    assert default_domain() == {key: getattr(DomainConfig(), key) for key in DOMAIN_KEYS}
    assert (DEFAULT_COLREGS_CONSTANTS_FILE.name, DEFAULT_VESSEL_TYPES_FILE.name, DEFAULT_OBSTACLE_TYPES_FILE.name) == (
        "general_maritime_constants.yaml",
        "vessel_types.yaml",
        "static_obstacle_types.yaml",
    )


def test_presets_are_the_yaml_files_of_each_folder_by_name(tmp_path):
    folders = {key: tmp_path / key for key in DOMAIN_KEYS}
    folders["colregs_constants"].mkdir()
    (folders["colregs_constants"] / "strict.yaml").write_bytes(b"A: 1\r\nB: 2\r\n")
    (folders["colregs_constants"] / "general_maritime_constants.yaml").write_text("A: 3\n", encoding="utf-8")
    (folders["colregs_constants"] / "notes.txt").write_text("not a preset", encoding="utf-8")
    presets = domain_presets(folders)
    assert [(preset.name, preset.default, preset.content) for preset in presets["colregs_constants"]] == [
        ("general_maritime_constants", True, "A: 3\n"),
        ("strict", False, "A: 1\nB: 2\n"),  # LF line endings, as in a Linux checkout
    ]
    assert presets["vessel_types"] == () and presets["obstacle_types"] == ()  # a missing folder offers none


def test_every_shipped_preset_is_a_valid_domain_text():
    for key, presets in domain_presets(PRESET_FOLDERS).items():
        for preset in presets:
            assert getattr(DomainConfig(**{key: preset.content}), key) == preset.content
