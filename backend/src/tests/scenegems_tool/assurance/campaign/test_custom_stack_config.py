"""The custom controller on Gazebo as a campaign run's stack: the config model, and the resolver's check of its triples for unattended runs."""

import pytest

from scenegems_tool.assurance.campaign import CampaignConfigError, CampaignConfigRejected, campaign_config_from_dict, validate_campaign_config
from scenegems_tool.assurance.campaign.campaign_config import ArdupilotStackConfig, CustomStackConfig
from scenegems_tool.assurance.campaign.config_validation import OWN_SHIP, TARGET_SHIP, vessel_stacks
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId

CLASS = "2vessel_0obstacle_scenarios/fec0"
WAVES = {"amplitude": 0.5, "period": 5.0, "steepness": 0.0, "direction": [1.0, 0.0]}
CUSTOM = {"simulation_layer": "gazebo", "control_layer": "custom"}


def _config(*runs):
    return campaign_config_from_dict({"name": "lab", "scope": [{"classes": [CLASS], "quota": 1}], "execution": {"runs": list(runs)}})


def _run(**fields):
    return {"stack": {**CUSTOM, **fields.pop("stack", {})}, **fields}


def _reasons(*runs) -> str:
    with pytest.raises(CampaignConfigError) as error:
        _config(*runs)
    return "\n".join(error.value.reasons)


def test_control_layer_custom_picks_the_custom_stack():
    custom, ardupilot = _config(_run(), {"stack": {"simulation_layer": "gazebo"}}).execution.runs
    assert isinstance(custom.stack, CustomStackConfig) and isinstance(ardupilot.stack, ArdupilotStackConfig)
    assert (custom.stack.mode.value, custom.stack.usv_navigation, custom.stack.dt, custom.stack.steps) == ("replay", None, None, None)


def test_the_stack_names_its_control_layer_in_the_json_and_round_trips():
    config = _config(_run(stack={"mode": "usv_navigation", "dt": 2, "steps": 40}, environment={"wind_vector": [0.0, 3.0, 0.0]}))
    (stored,) = config.to_json()["execution"]["runs"]
    assert stored["stack"] == {"simulation_layer": "gazebo", "control_layer": "custom", "mode": "usv_navigation", "usv_navigation": None, "dt": 2.0, "steps": 40}
    assert campaign_config_from_dict(config.to_json()) == config and campaign_config_from_dict(config.to_json()).config_hash() == config.config_hash()
    assert config.config_hash() != _config({"stack": {"simulation_layer": "gazebo", "mode": "usv_navigation", "dt": 2, "steps": 40}}).config_hash()


@pytest.mark.parametrize(
    "run, reason",
    [
        (_run(stack={"speedup": 2}), "execution.runs.0.stack.speedup: Extra inputs are not permitted"),
        (_run(stack={"geofence": {"latitude": 58.0}}), "execution.runs.0.stack.geofence: Extra inputs are not permitted"),
        (_run(stack={"dt": 1.5}), "execution.runs.0.stack.dt: Value error, the observed trajectories and the live monitor need a whole number of seconds as dt"),
        (_run(stack={"usv_navigation": {"goal": [1, 2], "speed": 1, "safety_radius": 1, "control_horizon": 1}}), "usv_navigation parameters apply only to mode usv_navigation"),
        (_run(monitor="live", early_stop=True), "the custom controller on Gazebo does not stop early"),
    ],
)
def test_invalid_custom_stacks_are_rejected_with_the_reason(run, reason):
    assert reason in _reasons(run)


@pytest.mark.parametrize("mode, own_ship", [("replay", AsvSoftwareId.REPLAY), ("usv_navigation", AsvSoftwareId.USV_NAVIGATION)])
def test_the_runs_vessels_are_on_the_custom_controller(mode, own_ship):
    stacks = vessel_stacks(_config(_run(stack={"mode": mode})).execution.runs[0].stack)
    assert (stacks[OWN_SHIP].asv_software, stacks[OWN_SHIP].control_layer, stacks[OWN_SHIP].simulation_layer) == (own_ship, ControlLayerId.CUSTOM, SimulationLayerId.GAZEBO)
    assert (stacks[TARGET_SHIP].asv_software, stacks[TARGET_SHIP].control_layer) == (AsvSoftwareId.REPLAY, ControlLayerId.CUSTOM)


@pytest.mark.parametrize("mode", ["replay", "usv_navigation"])
def test_the_custom_stack_resolves_bounded_with_wind_and_waves(mode):
    (resolved,) = validate_campaign_config(_config(_run(stack={"mode": mode}, environment={"wind_vector": [0.0, 3.0, 0.0], "waves": WAVES}))).runs
    assert resolved.repeatability_tier == "bounded"
    assert resolved.environment == {"wind_vector": [0.0, 3.0, 0.0], "waves": WAVES}


def test_the_custom_stack_is_refused_by_a_resolver_that_lacks_it():
    from scenegems_tool.vessel_stack.registry.adapter_registry import AdapterRegistry
    from scenegems_tool.vessel_stack.registry.resolver import StackResolver

    with pytest.raises(CampaignConfigRejected) as rejected:
        validate_campaign_config(_config(_run()), resolver=StackResolver(AdapterRegistry()))
    assert any(reason.startswith("execution.runs.0: vessel own_ship (replay, custom, gazebo)") for reason in rejected.value.reasons)
