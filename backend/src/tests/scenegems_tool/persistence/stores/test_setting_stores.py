"""The cluster's domain configuration and its saved campaign presets on a real Postgres (-m postgres)."""

import pytest

from scenegems_tool.persistence.stores import CampaignPresetStore, DomainStore, PresetNameTaken, UnknownPreset

pytestmark = pytest.mark.postgres

CONFIG = {"format": 2, "name": "lab", "steps": ["simulation"]}


@pytest.fixture
def domain(session_factory, clock) -> DomainStore:
    return DomainStore(session_factory, clock)


@pytest.fixture
def presets(session_factory, clock) -> CampaignPresetStore:
    return CampaignPresetStore(session_factory, clock)


def test_a_cluster_has_no_domain_configuration_until_it_is_saved(domain, clock):
    assert domain.current() is None
    saved = domain.save("A: 1\n", "Ferry: {}\n", "Buoy: {}\n")
    assert saved.contents() == {"colregs_constants": "A: 1\n", "vessel_types": "Ferry: {}\n", "obstacle_types": "Buoy: {}\n"}
    assert saved.updated_at == clock() and domain.current() == saved


def test_saving_the_domain_configuration_again_replaces_it(domain, clock):
    domain.save("A: 1\n", "Ferry: {}\n", "Buoy: {}\n")
    clock.advance(300)
    domain.save("A: 2\n", "Tug: {}\n", "Rock: {}\n")
    current = domain.current()
    assert current.contents() == {"colregs_constants": "A: 2\n", "vessel_types": "Tug: {}\n", "obstacle_types": "Rock: {}\n"}
    assert current.updated_at == clock()


def test_presets_are_listed_by_name(presets):
    second, replaced = presets.save("sitl nightly", "every night", CONFIG)
    first, _ = presets.save("kinematic quick", "", {**CONFIG, "name": "quick"})
    assert not replaced
    assert [preset.name for preset in presets.list_presets()] == ["kinematic quick", "sitl nightly"]
    assert presets.get(second.preset_id) == second and presets.get(first.preset_id).config["name"] == "quick"
    assert presets.get("no-such-preset") is None


def test_a_taken_name_is_refused_unless_the_preset_is_replaced(presets, clock):
    original, _ = presets.save("nightly", "first", CONFIG)
    with pytest.raises(PresetNameTaken):
        presets.save("nightly", "second", CONFIG)
    clock.advance(3600)
    replacement, replaced = presets.save("nightly", "second", {**CONFIG, "name": "changed"}, replace=True)
    assert replaced and replacement.preset_id == original.preset_id  # it keeps its id
    assert (replacement.description, replacement.config["name"]) == ("second", "changed")
    assert replacement.created_at == original.created_at and replacement.updated_at == clock()
    assert len(presets.list_presets()) == 1


def test_a_deleted_preset_is_gone(presets):
    saved, _ = presets.save("nightly", "", CONFIG)
    presets.delete(saved.preset_id)
    assert presets.list_presets() == []
    with pytest.raises(UnknownPreset):
        presets.delete(saved.preset_id)
