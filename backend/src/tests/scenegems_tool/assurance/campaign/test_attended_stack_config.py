"""The attended stack of a workbench entry: the config model, who may have one, and the payload the engine builds for the attended runner."""

import pytest

from scenegems_tool.assurance.campaign import CampaignConfigError, CampaignConfigRejected, campaign_config_from_dict, validate_campaign_config
from scenegems_tool.assurance.campaign.campaign_config import AttendedStackConfig, KinematicStackConfig
from scenegems_tool.assurance.campaign.config_validation import vessel_stacks
from scenegems_tool.assurance.pipeline.payload_builder import PayloadBuilder, validate_payload
from scenegems_tool.assurance.pipeline.stage_graph import run_stack_components
from scenegems_tool.cluster.protocol.jobs import JobType
from tests.scenegems_tool.cluster.payloads import trajectories_data

CLASS = "2vessel_0obstacle_scenarios/fec0"


def setup(simulator: str = "Kinematic", **vessels) -> dict:
    """The workbench's setup of two vessels; a keyword per agent id changes that vessel (agent_0=dict(asvSystem=...))."""
    control_layer = "none" if simulator == "Kinematic" else "ardupilot"
    connections = {}
    for agent_id in ("0", "1"):
        connection = {
            "context": "simulation",
            "asvSystem": "replay",
            "controlLayer": control_layer,
            "agentName": f"typed_{agent_id}",
            "topic": "",
            "port": 14570 + int(agent_id),
            "gazeboVesselModel": None,
        }
        connection.update(vessels.get(f"agent_{agent_id}", {}))
        connections[agent_id] = connection
    wave = {"amplitude": 0.0, "period": 0.0, "steepness": 0.0, "direction": [0.0, 0.0]}
    return {"simulatorType": simulator, "windVector": [0.0, 0.0, 0.0], "wave": wave, "simulationSpeed": 1, "connectionsByAgentId": connections}


MISSION_PLANNER = setup("ArduPilot Sim", agent_0={"asvSystem": "mission_planner"})


def _config(stack: dict, **run):
    return campaign_config_from_dict({"name": "lab", "scope": [{"classes": [CLASS], "quota": 1}], "execution": {"runs": [{"stack": stack, **run}]}})


def attended(simulation: dict, **fields) -> dict:
    return {"attended": True, "simulation": simulation, **fields}


def test_a_stack_that_says_attended_is_the_workbenchs_setup():
    (run,) = _config(attended(MISSION_PLANNER)).execution.runs
    assert isinstance(run.stack, AttendedStackConfig) and run.stack.simulation_layer == "ardupilot_sim"
    assert run.stack.simulation == MISSION_PLANNER and (run.stack.start_timeout_s, run.stack.timeout_s) == (None, None)
    stacks = vessel_stacks(run.stack)
    assert {agent_id: str(stack) for agent_id, stack in stacks.items()} == {"0": "mission_planner, ardupilot, ardupilot_sim", "1": "replay, ardupilot, ardupilot_sim"}, "each vessel's own, by agent id"
    assert run_stack_components(run.stack) == ("asv_system/replay", "asv_system/mission_planner", "control_layer/ardupilot", "simulation_layer/ardupilot_sim")
    assert isinstance(_config({"simulation_layer": "kinematic"}).execution.runs[0].stack, KinematicStackConfig), "a stack that does not say so is what it was"


@pytest.mark.parametrize(
    "stack, reason",
    [
        (attended(setup(agent_1={"context": "real", "port": None})), "real vessel"),
        (attended({"simulatorType": "Kinematic"}), "incomplete"),
        ({"attended": True}, "simulation"),
        (attended(setup(), mode="replay"), "mode"),
    ],
)
def test_a_setup_the_attended_runner_cannot_run_is_no_config(stack, reason):
    with pytest.raises(CampaignConfigError) as error:
        _config(stack)
    assert reason in "\n".join(error.value.reasons)


def test_an_attended_run_does_not_stop_early():
    with pytest.raises(CampaignConfigError) as error:
        _config(attended(setup()), monitor="live", early_stop=True)
    assert "does not stop early" in "\n".join(error.value.reasons)


def test_only_a_workbench_entry_may_have_an_attended_run():
    config = _config(attended(MISSION_PLANNER))
    with pytest.raises(CampaignConfigRejected) as rejected:
        validate_campaign_config(config)
    assert "only a workbench entry may have one" in "\n".join(rejected.value.reasons), "a campaign has no operator to start it"
    validated = validate_campaign_config(config, attended=True)
    (run,) = validated.runs
    assert set(run.vessels) == {"0", "1"} and str(run.vessels["0"]) == "mission_planner, ardupilot, ardupilot_sim"


def test_a_setup_the_resolver_refuses_is_rejected_for_a_workbench_entry_too():
    too_fast = {**setup("ArduPilot Sim"), "simulationSpeed": 5000}
    with pytest.raises(CampaignConfigRejected) as rejected:
        validate_campaign_config(_config(attended(too_fast)), attended=True)
    assert "speedup 5000" in "\n".join(rejected.value.reasons)


def test_the_engine_builds_the_attended_runners_payload_from_the_setup():
    config = _config(attended(MISSION_PLANNER, start_timeout_s=600.0), monitor="live")
    payload = PayloadBuilder(config)._simulation(1234, 0, trajectories_data())
    assert (payload["runner"], payload["simulation"], payload["seed"]) == ("attended", MISSION_PLANNER, 1234)
    assert payload["start_timeout_s"] == 600.0 and "timeout_s" not in payload, "the runner's defaults unless the entry names them"
    assert payload["monitor"] == "live" and payload["colregs_constraints_content"] == config.domain.colregs_constants
    assert payload["geofence"] == config.execution.runs[0].stack.geofence.model_dump(mode="json")
    validate_payload(JobType.SIMULATION, payload)
