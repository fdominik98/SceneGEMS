"""MOOS-IvP on the own ship as a campaign run's stack: the mode moos_ivp of the three stack sections, its parameters, and the payloads the runs get."""

import pytest
import yaml

from scenegems_tool.assurance.campaign import CampaignConfigError, campaign_config_from_dict, parse_campaign_config, validate_campaign_config
from scenegems_tool.assurance.campaign.campaign_config import ArdupilotStackConfig, CustomStackConfig, KinematicStackConfig
from scenegems_tool.assurance.campaign.campaign_presets import builtin_presets
from scenegems_tool.assurance.campaign.config_validation import ARDUPILOT_ADAPTERS, OWN_SHIP, TARGET_SHIP, vessel_stacks
from scenegems_tool.assurance.pipeline.payload_builder import PayloadBuilder, validate_payload
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.jobs.simulation_runners.kinematic_runner import MoosIvpPayload
from scenegems_tool.vessel_stack.asv_system.moos_ivp.moos_ivp_parameters import MoosIvpParameters
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId
from tests.scenegems_tool.cluster.payloads import trajectories_data

CLASS = "2vessel_0obstacle_scenarios/fec0"
# The stack section of each layer a campaign runs MOOS-IvP on, with the layers its vessels resolve to
SECTIONS = {
    "kinematic": ({"simulation_layer": "kinematic"}, KinematicStackConfig, ControlLayerId.NONE, SimulationLayerId.KINEMATIC, "exact"),
    "ardupilot_sim": ({"simulation_layer": "ardupilot_sim"}, ArdupilotStackConfig, ControlLayerId.ARDUPILOT, SimulationLayerId.ARDUPILOT_SIM, "bounded"),
    "gazebo": ({"simulation_layer": "gazebo"}, ArdupilotStackConfig, ControlLayerId.ARDUPILOT, SimulationLayerId.GAZEBO, "bounded"),
    "gazebo_custom": ({"simulation_layer": "gazebo", "control_layer": "custom"}, CustomStackConfig, ControlLayerId.CUSTOM, SimulationLayerId.GAZEBO, "bounded"),
}
DEFAULTS = MoosIvpParameters(
    goal=(4000.0, 0.0), speed=8.0, max_speed=20.0, min_util_cpa_dist=120.0, max_util_cpa_dist=240.0, pwt_outer_dist=9000.0, pwt_inner_dist=4500.0, completed_dist=9900.0, capture_radius=60.0
)


def _config(*stacks):
    return campaign_config_from_dict({"name": "lab", "scope": [{"classes": [CLASS], "quota": 1}], "execution": {"runs": [{"stack": stack} for stack in stacks]}})


def _reasons(stack) -> str:
    with pytest.raises(CampaignConfigError) as error:
        _config(stack)
    return "\n".join(error.value.reasons)


class TestThePayloadOfParameters:
    def test_a_value_that_is_given_replaces_the_scenes_and_the_rest_stays(self):
        applied = MoosIvpPayload(avoidance="cpa", goal=(1.0, 2.0), pwt_inner_dist=3000.0, behaviour_options={"pwt_grade": "quasi", "bearing_lines": "false"}).apply(DEFAULTS)
        assert (applied.avoidance, applied.goal, applied.pwt_inner_dist) == ("cpa", (1.0, 2.0), 3000.0)
        assert applied.behaviour_options == (("bearing_lines", "false"), ("pwt_grade", "quasi")), "in name order, so the helm's behaviour file does not depend on the order they were written in"
        assert (applied.speed, applied.max_speed, applied.pwt_outer_dist, applied.completed_dist, applied.capture_radius) == (8.0, 20.0, 9000.0, 9900.0, 60.0)
        assert MoosIvpPayload().apply(DEFAULTS) == DEFAULTS

    def test_values_that_contradict_the_scenes_are_refused_when_they_are_applied(self):
        with pytest.raises(ValueError, match="the distances must be ordered"):
            MoosIvpPayload(pwt_outer_dist=100.0).apply(DEFAULTS)
        with pytest.raises(ValueError, match="at most max_speed"):
            MoosIvpPayload(speed=25.0).apply(DEFAULTS)

    @pytest.mark.parametrize(
        "fields, message",
        [
            ({"speed": 9.0, "max_speed": 5.0}, "speed must not exceed max_speed"),
            ({"min_util_cpa_dist": 300.0, "max_util_cpa_dist": 200.0}, "min_util_cpa_dist must not exceed max_util_cpa_dist"),
            ({"pwt_outer_dist": 500.0, "completed_dist": 400.0}, "pwt_outer_dist must not exceed completed_dist"),
            ({"pwt_inner_dist": 500.0, "completed_dist": 400.0}, "pwt_inner_dist must not exceed completed_dist"),
            ({"speed": 0.0}, "greater than 0"),
            ({"avoidance": "v26"}, "Input should be 'colregs' or 'cpa'"),
        ],
    )
    def test_given_values_that_contradict_each_other_are_refused_at_once(self, fields, message):
        with pytest.raises(ValueError, match=message):
            MoosIvpPayload(**fields)

    def test_only_the_given_values_are_written(self):
        assert MoosIvpPayload().model_dump(mode="json") == {}
        assert MoosIvpPayload(avoidance="cpa", goal=(1.0, 2.0)).model_dump(mode="json") == {"goal": [1.0, 2.0], "avoidance": "cpa"}
        assert set(MoosIvpPayload.model_fields) == set(DEFAULTS.as_dict()), "one field per parameter of the helm"


class TestTheStackSections:
    @pytest.mark.parametrize("name", SECTIONS)
    def test_the_mode_puts_moos_ivp_on_the_own_ship_and_replay_on_the_targets(self, name):
        section, model, control_layer, simulation_layer, _ = SECTIONS[name]
        stack = _config({**section, "mode": "moos_ivp"}).execution.runs[0].stack
        assert isinstance(stack, model) and stack.mode.value == "moos_ivp" and stack.moos_ivp is None
        stacks = vessel_stacks(stack)
        assert (stacks[OWN_SHIP].asv_system, stacks[OWN_SHIP].control_layer, stacks[OWN_SHIP].simulation_layer) == (AsvSystemId.MOOS_IVP, control_layer, simulation_layer)
        assert (stacks[TARGET_SHIP].asv_system, stacks[TARGET_SHIP].control_layer, stacks[TARGET_SHIP].simulation_layer) == (AsvSystemId.REPLAY, control_layer, simulation_layer)

    @pytest.mark.parametrize("name", SECTIONS)
    def test_the_resolver_takes_the_run_as_an_unattended_one(self, name):
        section, _, _, _, tier = SECTIONS[name]
        (resolved,) = validate_campaign_config(_config({**section, "mode": "moos_ivp"})).runs
        assert resolved.repeatability_tier == tier
        assert resolved.vessels[OWN_SHIP].asv_system == AsvSystemId.MOOS_IVP

    def test_on_ardupilot_the_own_ship_goes_over_its_lockstep_adapter(self):
        assert ARDUPILOT_ADAPTERS[AsvSystemId.MOOS_IVP] == "moos_ivp_mavlink_lockstep"

    @pytest.mark.parametrize("name", SECTIONS)
    def test_the_parameters_are_part_of_the_config_and_round_trip(self, name):
        section = SECTIONS[name][0]
        config = _config({**section, "mode": "moos_ivp", "moos_ivp": {"avoidance": "cpa", "max_util_cpa_dist": 500.0}})
        stored = config.to_json()["execution"]["runs"][0]["stack"]
        assert stored["mode"] == "moos_ivp" and stored["moos_ivp"] == {"avoidance": "cpa", "max_util_cpa_dist": 500.0}
        assert campaign_config_from_dict(config.to_json()) == config and campaign_config_from_dict(config.to_json()).config_hash() == config.config_hash()
        assert config.config_hash() != _config({**section, "mode": "moos_ivp"}).config_hash(), "the parameters are part of what the campaign runs"

    @pytest.mark.parametrize("name", SECTIONS)
    def test_a_config_without_them_keeps_the_json_and_the_hash_it_had_before_the_mode(self, name):
        section = SECTIONS[name][0]
        for mode in ("replay", "usv_navigation", "moos_ivp"):
            assert "moos_ivp" not in _config({**section, "mode": mode}).to_json()["execution"]["runs"][0]["stack"]

    @pytest.mark.parametrize("name", SECTIONS)
    @pytest.mark.parametrize("mode", ["replay", "usv_navigation"])
    def test_the_parameters_apply_only_to_their_mode(self, name, mode):
        assert "moos_ivp parameters apply only to mode moos_ivp" in _reasons({**SECTIONS[name][0], "mode": mode, "moos_ivp": {"avoidance": "cpa"}})

    def test_usv_navigations_parameters_are_refused_in_mode_moos_ivp(self):
        usv_navigation = {"goal": [1, 2], "speed": 1, "safety_radius": 1, "control_horizon": 1}
        assert "usv_navigation parameters apply only to mode usv_navigation" in _reasons({"mode": "moos_ivp", "usv_navigation": usv_navigation})

    def test_a_wrong_parameter_is_named_under_the_stack(self):
        assert "execution.runs.0.stack.moos_ivp.avoidance: Input should be 'colregs' or 'cpa'" in _reasons({"mode": "moos_ivp", "moos_ivp": {"avoidance": "v26"}})
        assert "execution.runs.0.stack.moos_ivp.helm: Extra inputs are not permitted" in _reasons({"mode": "moos_ivp", "moos_ivp": {"helm": "fast"}})


class TestThePayloadsOfTheRuns:
    @pytest.mark.parametrize("name, runner", [("kinematic", "kinematic"), ("ardupilot_sim", "ardupilot"), ("gazebo", "ardupilot"), ("gazebo_custom", "gazebo_custom")])
    def test_a_run_gets_the_mode_and_the_parameters_the_section_gives(self, name, runner):
        section = SECTIONS[name][0]
        builder = PayloadBuilder(_config({**section, "mode": "moos_ivp", "moos_ivp": {"avoidance": "cpa", "goal": [5.0, 6.0]}}, {**section, "mode": "moos_ivp"}))
        given = builder.simulation(7, 0, {"trajectory_data": {"trajectories": trajectories_data()}})
        assert (given["runner"], given["mode"], given["moos_ivp"]) == (runner, "moos_ivp", {"goal": [5.0, 6.0], "avoidance": "cpa"})
        derived = builder.simulation(7, 1, {"trajectory_data": {"trajectories": trajectories_data()}})
        assert derived["mode"] == "moos_ivp" and "moos_ivp" not in derived and "usv_navigation" not in derived
        for payload in (given, derived):
            validate_payload(JobType.SIMULATION, payload)

    def test_the_job_needs_the_moos_ivp_layer(self):
        from scenegems_tool.assurance.pipeline.stage_graph import run_stack_components

        config = _config({"simulation_layer": "gazebo", "control_layer": "custom", "mode": "moos_ivp"})
        assert run_stack_components(config.execution.runs[0].stack) == ("asv_system/replay", "asv_system/moos_ivp", "control_layer/custom", "simulation_layer/gazebo")


def test_the_shipped_preset_compares_the_helm_with_the_planned_trajectories():
    (preset,) = [preset for preset in builtin_presets() if preset.preset_id == "14_moos_ivp_comparison"]
    config = parse_campaign_config(yaml.safe_dump(preset.config))
    assert [run.stack.mode.value for run in config.execution.runs] == ["replay", "moos_ivp"]
    validated = validate_campaign_config(config)
    assert [run.vessels[OWN_SHIP].asv_system for run in validated.runs] == [AsvSystemId.REPLAY, AsvSystemId.MOOS_IVP]
    assert all(run.repeatability_tier == "exact" for run in validated.runs)
