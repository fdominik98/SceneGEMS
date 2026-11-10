import json
from pathlib import Path

import pytest

from scenegems_tool.assurance.campaign import CampaignConfigRejected, ClassCatalog, campaign_config_from_dict, load_campaign_config, validate_campaign_config
from scenegems_tool.assurance.campaign.config_validation import OWN_SHIP, TARGET_SHIP, vessel_stacks
from scenegems_tool.cluster.worker_node.jobs.simulation_runners.kinematic_runner import KinematicMode
from scenegems_tool.persistence.stores import AssuranceStores, ClassSpec
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId
from scenegems_tool.vessel_stack.registry.adapter_registry import AdapterRegistry
from scenegems_tool.vessel_stack.registry.resolver import StackResolver

EXIT_CAMPAIGN = Path(__file__).parent / "data" / "exit_campaign.yaml"
CLASS = "2vessel_0obstacle_scenarios/fec0"


def _config(scope=None, **sections):
    return campaign_config_from_dict(dict({"name": "lab", "scope": scope or [{"classes": [CLASS], "quota": 2, "failure_budget": 1}]}, **sections))


def _rejection(config, **arguments) -> str:
    with pytest.raises(CampaignConfigRejected) as rejected:
        validate_campaign_config(config, **arguments)
    return "\n".join(rejected.value.reasons)


def test_the_exit_campaign_has_70_classes_and_1050_cases():
    validated = validate_campaign_config(load_campaign_config(EXIT_CAMPAIGN))
    assert len(validated.classes) == 70 and validated.total_quota == 1050
    assert {(spec.quota, spec.failure_budget) for spec in validated.classes} == {(15, 15)}
    assert {spec.vessel_count for spec in validated.classes} == {2, 3}
    catalog = ClassCatalog.default()
    assert all(spec.content_hash == catalog.get(spec.class_id).content_hash for spec in validated.classes)
    assert [spec.class_id for spec in validated.classes[:2]] == ["2vessel_0obstacle_scenarios/fec0", "2vessel_0obstacle_scenarios/fec1"]
    (run,) = validated.runs
    assert run.vessels[OWN_SHIP].asv_system == AsvSystemId.USV_NAVIGATION and run.vessels[TARGET_SHIP].asv_system == AsvSystemId.REPLAY
    assert (run.repeatability_tier, run.environment, run.warnings) == ("exact", {"wind_vector": None, "waves": None}, ())
    assert validated.config_hash == validated.config.config_hash() and validated.config_json == validated.config.to_json()


def test_classes_come_as_the_store_takes_them():
    (spec,) = validate_campaign_config(_config()).classes
    assert spec == ClassSpec(class_id=CLASS, content_hash=ClassCatalog.default().get(CLASS).content_hash, vessel_count=2, obstacle_count=0, quota=2, failure_budget=1)


def test_an_unlimited_failure_budget_reaches_the_store_as_none():
    (spec,) = validate_campaign_config(_config([{"classes": [CLASS], "quota": 2, "failure_budget": "unlimited"}])).classes
    assert (spec.quota, spec.failure_budget) == (2, None)


def test_a_class_named_twice_in_one_entry_counts_once():
    validated = validate_campaign_config(_config([{"classes": [CLASS], "patterns": ["2vessel_0obstacle_scenarios"], "quota": 1}]))
    assert [spec.class_id for spec in validated.classes] == [f"2vessel_0obstacle_scenarios/fec{index}" for index in range(7)]


def test_unknown_classes_and_empty_patterns_are_rejected_together():
    reasons = _rejection(
        _config(
            [
                {"classes": [CLASS, "2vessel_0obstacle_scenarios/fec99"], "quota": 1},
                {"patterns": ["9vessel_*"], "quota": 1},
                {"patterns": ["2vessel_0obstacle_scenarios"], "quota": 3},
            ]
        )
    )
    assert "scope.0: no FEC '2vessel_0obstacle_scenarios/fec99' in the catalog" in reasons
    assert "scope.1: the pattern '9vessel_*' matches no FEC" in reasons
    assert f"scope.2: FEC '{CLASS}' is in scope.0 already" in reasons


def test_the_resolver_refuses_wind_on_the_kinematic_layer():
    reasons = _rejection(_config(execution={"runs": [{"name": "windy", "environment": {"wind_vector": [3.0, 0.0, 0.0]}}]}))
    assert "execution.runs.0 (windy): wind requested, but simulation_layer/kinematic does not support wind" in reasons


def test_the_resolver_refuses_waves_on_the_kinematic_layer():
    waves = {"amplitude": 0.5, "period": 4.0, "steepness": 0.1, "direction": [1.0, 0.0]}
    assert "waves requested, but simulation_layer/kinematic does not support waves" in _rejection(_config(execution={"runs": [{}, {"environment": {"waves": waves}}]}))


def test_a_stack_the_resolver_does_not_know_is_refused():
    reasons = _rejection(_config(execution={"runs": [{"stack": {"mode": "usv_navigation"}}]}), resolver=StackResolver(AdapterRegistry()))
    assert "execution.runs.0: vessel own_ship (usv_navigation, none, kinematic): asv_system/usv_navigation is not registered" in reasons


def test_vessel_stacks_per_mode():
    replay = _config().execution.runs[0].stack
    assert {stack.asv_system for stack in vessel_stacks(replay).values()} == {AsvSystemId.REPLAY}
    closed_loop = _config(execution={"runs": [{"stack": {"mode": "usv_navigation"}}]}).execution.runs[0].stack
    assert closed_loop.mode == KinematicMode.USV_NAVIGATION
    assert vessel_stacks(closed_loop)[OWN_SHIP].asv_system == AsvSystemId.USV_NAVIGATION


@pytest.mark.postgres
def test_a_validated_campaign_is_stored_and_read_back_to_the_same_hash(session_factory):
    validated = validate_campaign_config(load_campaign_config(EXIT_CAMPAIGN))
    stores = AssuranceStores.create(session_factory)
    campaign = stores.campaigns.create_campaign(validated.config.name, validated.config_json, validated.config_hash, validated.classes)
    stored = stores.campaigns.config_version(campaign.campaign_id)
    assert stored.config_hash == validated.config_hash
    assert campaign_config_from_dict(stored.config).config_hash() == validated.config_hash
    classes = stores.cases.list_classes(campaign.campaign_id)
    assert len(classes) == 70 and sum(item.quota for item in classes) == 1050


# Partial campaigns (format 2)

SCENE_SHA, TRAJECTORIES_SHA, SCENARIO_SHA, MISSING_SHA = "1a" * 32, "2b" * 32, "3c" * 32, "4d" * 32


def _scene(vessels: int, obstacles: int = 0) -> dict:
    actors = [[{"id": index, "is_vessel": True}, {}] for index in range(vessels)] + [[{"id": vessels + index, "is_vessel": False}, {}] for index in range(obstacles)]
    return {"_data": actors}


class FakeArtifacts:
    """The artifact store as validation sees it: whether a hash is there, and its content."""

    def __init__(self, contents):
        self.contents = dict(contents)
        self.read = []

    def exists(self, sha256: str) -> bool:
        return sha256 in self.contents

    def content(self, sha256: str) -> bytes:
        self.read.append(sha256)
        return self.contents[sha256]


def _artifacts() -> FakeArtifacts:
    return FakeArtifacts(
        {
            SCENE_SHA: json.dumps({"best_scene": _scene(2, 1)}).encode(),
            TRAJECTORIES_SHA: json.dumps({"trajectories": {"scene_list": [_scene(3)], "time_step": 1}}).encode(),
            SCENARIO_SHA: ClassCatalog.default().get(CLASS).read_content().encode(),
        }
    )


def _validate(config, artifacts=None, **arguments):
    artifacts = artifacts or _artifacts()
    return validate_campaign_config(config, artifact_exists=artifacts.exists, read_artifact=artifacts.content, **arguments)


def _partial(steps, **sections):
    return campaign_config_from_dict(dict({"format": 2, "name": "partial", "steps": steps}, **sections))


def _item(sha256=SCENE_SHA, kind="scene", name="an item", pointer=None):
    return {"name": name, "ref": {"sha256": sha256, "size_bytes": 10, "kind": kind, "pointer": pointer}, "source": {"campaign_id": "c-1", "case_id": 4, "step": "scene_generation"}}


def _scenario(name="my_head_on", sha256=SCENARIO_SHA):
    return {"name": name, "ref": {"sha256": sha256, "size_bytes": 10, "kind": "functional_scenario"}, "quota": 2, "failure_budget": 1}


def _partial_rejection(config, artifacts=None, **arguments) -> str:
    with pytest.raises(CampaignConfigRejected) as rejected:
        _validate(config, artifacts, **arguments)
    return "\n".join(rejected.value.reasons)


def test_scene_generation_takes_catalog_classes_and_scenarios_given_as_content():
    config = _partial(["scene_generation"], scope=[{"classes": [CLASS], "quota": 2}], input={"functional_scenarios": [_scenario()]})
    validated = _validate(config)
    catalog_class, scenario = validated.classes
    assert catalog_class.class_id == CLASS
    assert scenario == ClassSpec(class_id="scenario/my_head_on", content_hash=SCENARIO_SHA, vessel_count=2, obstacle_count=0, quota=2, failure_budget=1)
    assert validated.runs == ()  # no simulation, no runs resolved
    assert validated.config_json["steps"] == ["scene_generation"] and validated.config_hash == config.config_hash()


def test_a_scenario_given_as_content_takes_an_unlimited_failure_budget():
    scenario = dict(_scenario(), failure_budget="unlimited")
    (spec,) = _validate(_partial(["scene_generation"], input={"functional_scenarios": [scenario]})).classes
    assert (spec.class_id, spec.failure_budget) == ("scenario/my_head_on", None)


def test_scenarios_alone_need_no_scope():
    (scenario,) = _validate(_partial(["scene_generation", "trajectory_generation"], input={"functional_scenarios": [_scenario()]})).classes
    assert scenario.class_id == "scenario/my_head_on"


def test_trajectory_generation_takes_scene_items():
    validated = _validate(_partial(["trajectory_generation"], input={"items": [_item(), _item(name="second")]}))
    assert [(spec.class_id, spec.content_hash, spec.vessel_count, spec.obstacle_count, spec.quota, spec.failure_budget) for spec in validated.classes] == [
        ("item/0", SCENE_SHA, 2, 1, 1, 0),
        ("item/1", SCENE_SHA, 2, 1, 1, 0),
    ]


def test_simulation_takes_trajectory_items_and_resolves_its_runs():
    validated = _validate(_partial(["simulation"], input={"items": [_item(TRAJECTORIES_SHA, "trajectory_data", pointer="/trajectories")]}))
    (spec,) = validated.classes
    assert (spec.class_id, spec.vessel_count) == ("item/0", 3)
    assert len(validated.runs) == 1


@pytest.mark.parametrize(
    "steps, sections, reason",
    [
        (["scene_generation"], {}, "input: a campaign that starts with scene_generation needs scope entries or input.functional_scenarios"),
        (["scene_generation"], {"scope": [{"classes": [CLASS], "quota": 1}], "input": {"items": [_item()]}}, "input.items: a campaign that starts with scene_generation takes catalog FECs"),
        (["trajectory_generation"], {}, "input.items: a campaign that starts with trajectory_generation needs at least one item"),
        (["trajectory_generation"], {"scope": [{"classes": [CLASS], "quota": 1}], "input": {"items": [_item()]}}, "scope: a campaign that starts with trajectory_generation takes input.items"),
        (["simulation"], {"input": {"functional_scenarios": [_scenario()], "items": [_item(TRAJECTORIES_SHA, "trajectories")]}}, "input.functional_scenarios: a campaign that starts with simulation"),
        (
            ["trajectory_generation"],
            {"input": {"items": [_item(TRAJECTORIES_SHA, "trajectories")]}},
            "input.items.0 (an item): a campaign that starts with trajectory_generation takes scene items, not trajectories",
        ),
        (["simulation"], {"input": {"items": [_item()]}}, "input.items.0 (an item): a campaign that starts with simulation takes trajectory_data or trajectories items, not scene"),
        (["trajectory_generation"], {"input": {"items": [_item(MISSING_SHA)]}}, f"input.items.0 (an item): no artifact {MISSING_SHA} in the artifact store"),
        (["scene_generation"], {"input": {"functional_scenarios": [_scenario(sha256=MISSING_SHA)]}}, f"input.functional_scenarios.0 (my_head_on): no artifact {MISSING_SHA}"),
        (["trajectory_generation"], {"input": {"items": [_item(pointer="/nothing")]}}, "input.items.0 (an item): the pointer /nothing names nothing in the document"),
        (["scene_generation"], {"input": {"functional_scenarios": [_scenario(sha256=SCENE_SHA)]}}, "input.functional_scenarios.0 (my_head_on): the functional scenario declares no vessel"),
    ],
)
def test_input_that_does_not_match_the_first_step_is_rejected(steps, sections, reason):
    assert reason in _partial_rejection(_partial(steps, **sections))


def test_every_input_problem_is_reported_together():
    reasons = _partial_rejection(
        _partial(["trajectory_generation"], scope=[{"classes": ["2vessel_0obstacle_scenarios/fec99"], "quota": 1}], input={"items": [_item(MISSING_SHA), _item(pointer="/x")]})
    )
    assert "scope: a campaign that starts with trajectory_generation takes input.items" in reasons
    assert "no FEC '2vessel_0obstacle_scenarios/fec99' in the catalog" in reasons
    assert "input.items.0 (an item): no artifact" in reasons and "input.items.1 (an item): the pointer /x" in reasons


def test_input_needs_an_artifact_store_to_check_against():
    reasons = "\n".join(pytest.raises(CampaignConfigRejected, validate_campaign_config, _partial(["trajectory_generation"], input={"items": [_item()]})).value.reasons)
    assert "input: there is no artifact store to check the input references against" in reasons


def test_sections_of_steps_not_run_are_not_checked():
    # A stack the resolver refuses, and an item store that is never asked: neither matters to a scene generation campaign
    config = _partial(["scene_generation"], scope=[{"classes": [CLASS], "quota": 1}], execution={"runs": [{"stack": {"mode": "usv_navigation"}}]})
    artifacts = _artifacts()
    validated = _validate(config, artifacts, resolver=StackResolver(AdapterRegistry()))
    assert validated.runs == () and artifacts.read == []
    with_simulation = _partial(["scene_generation", "trajectory_generation", "simulation"], scope=[{"classes": [CLASS], "quota": 1}], execution={"runs": [{"stack": {"mode": "usv_navigation"}}]})
    assert "asv_system/usv_navigation is not registered" in _partial_rejection(with_simulation, resolver=StackResolver(AdapterRegistry()))


def test_a_format_1_config_validates_as_before():
    validated = validate_campaign_config(_config())
    assert [spec.class_id for spec in validated.classes] == [CLASS] and len(validated.runs) == 1
    assert "steps" not in validated.config_json
