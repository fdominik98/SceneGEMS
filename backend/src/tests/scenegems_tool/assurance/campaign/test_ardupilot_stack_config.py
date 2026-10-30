"""The ArduPilot stacks of a campaign run: the config model, and the resolver's check of their triples for unattended runs."""

import pytest

from scenegems_tool.assurance.campaign import CampaignConfigError, CampaignConfigRejected, campaign_config_from_dict, validate_campaign_config
from scenegems_tool.assurance.campaign.campaign_config import (
    ARDUPILOT_LAYERS,
    DEFAULT_GEOFENCE_LATITUDE,
    DEFAULT_GEOFENCE_LONGITUDE,
    DEFAULT_GEOFENCE_RADIUS_M,
    ArdupilotStackConfig,
    KinematicStackConfig,
)
from scenegems_tool.assurance.campaign.config_validation import OWN_SHIP, TARGET_SHIP, vessel_stacks
from scenegems_tool.cluster.node.daemon.configuration.node_configuration import DEFAULT_REFERENCE_GEOFENCE
from scenegems_tool.cluster.node.jobs.simulation_runners.ardupilot_runner import ArduPilotSimulationLayer
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.registry.adapter_registry import AdapterRegistry
from scenegems_tool.vessel_stack.registry.resolver import StackResolver

CLASS = "2vessel_0obstacle_scenarios/functional_model0"
WAVES = {"amplitude": 0.5, "period": 4.0, "steepness": 0.1, "direction": [1.0, 0.0]}


def _config(*runs, **sections):
    return campaign_config_from_dict({"name": "lab", "scope": [{"classes": [CLASS], "quota": 1}], "execution": {"runs": list(runs)}, **sections})


def _run(layer="ardupilot_sim", **fields):
    return {"stack": {"simulation_layer": layer, **fields.pop("stack", {})}, **fields}


def _rejection(config) -> str:
    with pytest.raises(CampaignConfigRejected) as rejected:
        validate_campaign_config(config)
    return "\n".join(rejected.value.reasons)


def _reasons(*runs) -> str:
    with pytest.raises(CampaignConfigError) as error:
        _config(*runs)
    return "\n".join(error.value.reasons)


# The model


def test_the_layers_are_the_jobs_layers():
    assert set(ARDUPILOT_LAYERS) == {layer.value for layer in ArduPilotSimulationLayer}


def test_an_ardupilot_stack_has_its_defaults_and_the_workbench_geofence():
    (run,) = _config(_run("gazebo")).execution.runs
    assert isinstance(run.stack, ArdupilotStackConfig)
    assert (run.stack.simulation_layer, run.stack.mode, run.stack.speedup, run.stack.dt, run.stack.steps) == ("gazebo", "replay", 1, None, None)
    assert (run.stack.geofence.latitude, run.stack.geofence.longitude, run.stack.geofence.radius_meters) == (DEFAULT_GEOFENCE_LATITUDE, DEFAULT_GEOFENCE_LONGITUDE, DEFAULT_GEOFENCE_RADIUS_M)
    assert (DEFAULT_GEOFENCE_LATITUDE, DEFAULT_GEOFENCE_LONGITUDE, DEFAULT_GEOFENCE_RADIUS_M) == DEFAULT_REFERENCE_GEOFENCE


def test_the_stack_is_chosen_by_its_simulation_layer():
    kinematic, absent, sim, gazebo = _config({"stack": {"simulation_layer": "kinematic"}}, {"stack": {"mode": "usv_navigation"}}, _run("ardupilot_sim"), _run("gazebo")).execution.runs
    assert [type(run.stack) for run in (kinematic, absent, sim, gazebo)] == [KinematicStackConfig, KinematicStackConfig, ArdupilotStackConfig, ArdupilotStackConfig]
    assert [run.stack.simulation_layer for run in (kinematic, absent, sim, gazebo)] == ["kinematic", "kinematic", "ardupilot_sim", "gazebo"]


def test_the_stack_values_and_a_geofence_are_kept_and_round_trip_through_the_stored_json():
    run = _run(stack={"speedup": 4, "dt": 2, "steps": 30, "geofence": {"latitude": 58.0, "radius_meters": 50}})
    config = _config(run)
    (stored,) = config.to_json()["execution"]["runs"]
    assert stored["stack"] == {
        "simulation_layer": "ardupilot_sim",
        "mode": "replay",
        "speedup": 4,
        "dt": 2.0,
        "steps": 30,
        "geofence": {"latitude": 58.0, "longitude": DEFAULT_GEOFENCE_LONGITUDE, "radius_meters": 50.0},
    }
    assert campaign_config_from_dict(config.to_json()) == config and campaign_config_from_dict(config.to_json()).config_hash() == config.config_hash()


def test_the_geofence_is_pinned_in_the_hash():
    base, moved = _config(_run()), _config(_run(stack={"geofence": {"latitude": 58.0}}))
    assert base.config_hash() != moved.config_hash() and base.config_hash() != _config(_run("gazebo")).config_hash()


def test_a_format_1_config_without_ardupilot_keeps_its_hash():
    kinematic = campaign_config_from_dict({"name": "lab", "scope": [{"classes": [CLASS], "quota": 1}]})
    assert kinematic.to_json()["execution"]["runs"][0]["stack"] == {"simulation_layer": "kinematic", "mode": "replay", "usv_navigation": None, "dt": None, "steps": None}


@pytest.mark.parametrize(
    "run, reason",
    [
        ({"stack": {"simulation_layer": "mars"}}, "execution.runs.0.stack: Value error, unknown simulation_layer 'mars'; a stack runs on kinematic, ardupilot_sim, gazebo"),
        (_run(stack={"mode": "usv_navigation"}), "execution.runs.0.stack.mode: Input should be 'replay'"),
        (_run(stack={"speedup": 0}), "execution.runs.0.stack.speedup: Input should be greater than or equal to 1"),
        (_run(stack={"dt": 1.5}), "execution.runs.0.stack.dt: Value error, the observed trajectories and the live monitor need a whole number of seconds as dt"),
        (_run(stack={"dt": 0}), "execution.runs.0.stack.dt: Input should be greater than 0"),
        (_run(stack={"steps": 0}), "execution.runs.0.stack.steps: Input should be greater than or equal to 1"),
        (_run(stack={"geofence": {"latitude": 91}}), "execution.runs.0.stack.geofence.latitude: Input should be less than or equal to 90"),
        (_run(stack={"geofence": {"radius_meters": 0}}), "execution.runs.0.stack.geofence.radius_meters: Input should be greater than 0"),
        (_run(stack={"usv_navigation": {"goal": [1, 2]}}), "execution.runs.0.stack.usv_navigation: Extra inputs are not permitted"),
        (_run(monitor="live", early_stop=True), "the ArduPilot stacks do not stop early"),
    ],
)
def test_invalid_ardupilot_stacks_are_rejected_with_the_reason(run, reason):
    assert reason in _reasons(run)


def test_kinematic_stacks_keep_their_error_paths():
    assert "execution.runs.0.stack.usv_navigation.speed: Field required" in _reasons({"stack": {"mode": "usv_navigation", "usv_navigation": {"goal": [1, 2]}}})
    assert "execution.runs.0.stack.speedup: Extra inputs are not permitted" in _reasons({"stack": {"speedup": 2}})


def test_the_live_monitor_and_repeats_are_allowed_on_ardupilot():
    (run,) = _config(_run(monitor="live", repeats=3)).execution.runs
    assert (run.monitor.value, run.repeats) == ("live", 3)


# The resolver's check of the triples


@pytest.mark.parametrize("layer", ARDUPILOT_LAYERS)
def test_both_layers_resolve_as_replay_on_ardupilot_in_the_bounded_tier(layer):
    stack = _config(_run(layer)).execution.runs[0].stack
    for vessel in vessel_stacks(stack).values():
        assert (vessel.asv_software, vessel.control_layer, vessel.simulation_layer) == (AsvSoftwareId.REPLAY, ControlLayerId.ARDUPILOT, SimulationLayerId(layer))
    assert set(vessel_stacks(stack)) == {OWN_SHIP, TARGET_SHIP}
    validated = validate_campaign_config(_config(_run(layer)))
    (resolved,) = validated.runs
    assert resolved.repeatability_tier == "bounded" and resolved.environment == {"wind_vector": None, "waves": None}
    assert resolved.vessels[OWN_SHIP].simulation_layer.value == layer


def test_a_run_may_mix_ardupilot_and_kinematic_runs():
    validated = validate_campaign_config(_config({"name": "kinematic"}, _run("ardupilot_sim", name="sitl"), _run("gazebo", name="world")))
    assert [run.repeatability_tier for run in validated.runs] == ["exact", "bounded", "bounded"]


def test_a_stack_the_resolver_does_not_know_is_refused():
    config = _config(_run("gazebo"))
    with pytest.raises(CampaignConfigRejected) as rejected:
        validate_campaign_config(config, resolver=StackResolver(AdapterRegistry()))
    assert any(reason.startswith("execution.runs.0: vessel own_ship (replay, ardupilot, gazebo)") for reason in rejected.value.reasons)


def test_the_speedup_goes_to_the_resolver():
    assert validate_campaign_config(_config(_run(stack={"speedup": 8}))).runs[0].warnings == ()
    unverified = validate_campaign_config(_config(_run("gazebo", stack={"speedup": 8}))).runs[0].warnings
    assert len(unverified) == 1 and "speedup 8 is unverified" in unverified[0]
    reasons = _rejection(_config(_run(stack={"speedup": 1000})))
    assert "execution.runs.0: speedup 1000 exceeds the measured max_speedup 50 of replay_mavlink_lockstep" in reasons


@pytest.mark.parametrize("layer", ARDUPILOT_LAYERS)
def test_wind_and_waves_are_refused_because_the_job_runs_calm_water(layer):
    windy = _rejection(_config(_run(layer, name="windy", environment={"wind_vector": [3.0, 0.0, 0.0]})))
    assert "execution.runs.0 (windy): the ArduPilot stacks run without wind" in windy
    wavy = _rejection(_config(_run(layer, environment={"waves": WAVES})))
    assert "execution.runs.0: the ArduPilot stacks run without waves" in wavy
    assert validate_campaign_config(_config(_run(layer, environment={"wind_vector": [0.0, 0.0, 0.0]}))).runs


def test_every_problem_of_several_runs_is_reported():
    reasons = _rejection(_config({"environment": {"wind_vector": [1.0, 0.0, 0.0]}}, _run(environment={"waves": WAVES}), _run("gazebo", environment={"wind_vector": [0.0, 2.0, 0.0]})))
    assert "execution.runs.0:" in reasons and "execution.runs.1: the ArduPilot stacks run without waves" in reasons and "execution.runs.2: the ArduPilot stacks run without wind" in reasons
