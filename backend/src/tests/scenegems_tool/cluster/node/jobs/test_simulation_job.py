"""The simulation job: the payload's runner picks the runner model, the components and the runner's run and in-container part."""

import pytest
from pydantic import ValidationError

from scenegems_tool.cluster.fingerprints.components import RUNNER_STACKS, SimulationRunner
from scenegems_tool.cluster.node.jobs import simulation_job
from scenegems_tool.cluster.node.jobs.simulation_job import RUNNER_MODULES, SimulationPayload, required_components
from scenegems_tool.cluster.node.jobs.simulation_runners.ardupilot_runner import ArduPilotSimulationPayload
from scenegems_tool.cluster.node.jobs.simulation_runners.kinematic_runner import KinematicSimulationPayload
from scenegems_tool.cluster.protocol.jobs import JobType
from tests.scenegems_tool.cluster.payloads import ardupilot_payload, valid_payload

KINEMATIC = ("asv_software/replay", "control_layer/none", "simulation_layer/kinematic")


def test_every_runner_has_a_module_and_the_catalog_names_its_stacks():
    assert set(RUNNER_MODULES) == set(SimulationRunner) == set(RUNNER_STACKS)
    for module in RUNNER_MODULES.values():
        assert callable(module.run) and callable(module.execute) and callable(module.vessel_stacks)


def test_the_runner_picks_the_payload_model():
    kinematic = SimulationPayload.model_validate(valid_payload(JobType.SIMULATION))
    ardupilot = SimulationPayload.model_validate(ardupilot_payload("ardupilot_sim", speedup=4))
    assert isinstance(kinematic.root, KinematicSimulationPayload) and kinematic.runner == SimulationRunner.KINEMATIC
    assert isinstance(ardupilot.root, ArduPilotSimulationPayload) and ardupilot.root.speedup == 4
    dumped = kinematic.model_dump(mode="json")
    assert dumped["runner"] == "kinematic" and SimulationPayload.model_validate(dumped).model_dump(mode="json") == dumped, "the payload round trips with its runner"


@pytest.mark.parametrize(
    "payload, problem",
    [
        ({"trajectories": {}}, "runner"),
        ({"runner": "gazebo_custom"}, "gazebo_custom"),
        ({**valid_payload(JobType.SIMULATION), "simulation_layer": "gazebo"}, "simulation_layer"),
    ],
)
def test_a_payload_without_a_known_runner_or_with_another_runners_fields_is_refused(payload, problem):
    with pytest.raises(ValidationError, match=problem):
        SimulationPayload.model_validate(payload)


def test_the_components_are_every_layer_of_every_vessels_stack():
    def components(payload):
        return required_components(SimulationPayload.model_validate(payload))

    assert components(valid_payload(JobType.SIMULATION)) == KINEMATIC
    assert components(valid_payload(JobType.SIMULATION, mode="usv_navigation")) == ("asv_software/replay", "asv_software/usv_navigation", "control_layer/none", "simulation_layer/kinematic")
    assert components(ardupilot_payload("ardupilot_sim")) == ("asv_software/replay", "control_layer/ardupilot", "simulation_layer/ardupilot_sim")
    assert components(ardupilot_payload("gazebo")) == ("asv_software/replay", "control_layer/ardupilot", "simulation_layer/gazebo")


def test_every_payload_stack_is_one_its_runner_declares():
    payloads = [valid_payload(JobType.SIMULATION), valid_payload(JobType.SIMULATION, mode="usv_navigation"), ardupilot_payload("ardupilot_sim"), ardupilot_payload("gazebo")]
    for payload in payloads:
        model = SimulationPayload.model_validate(payload)
        assert set(model.vessel_stacks()) <= set(RUNNER_STACKS[model.runner])


@pytest.mark.parametrize("payload, runner", [(valid_payload(JobType.SIMULATION), SimulationRunner.KINEMATIC), (ardupilot_payload("gazebo"), SimulationRunner.ARDUPILOT)])
def test_run_and_execute_go_to_the_runner_with_the_parsed_payload(monkeypatch, make_job, node, payload, runner):
    calls = []
    monkeypatch.setattr(RUNNER_MODULES[runner], "run", lambda job, node, report, parsed, cancel: calls.append(("run", type(parsed).__name__, cancel)) or {"ran": True})
    monkeypatch.setattr(
        RUNNER_MODULES[runner], "execute", lambda job, parsed, status, observation=None, hosting=None: calls.append(("execute", type(parsed).__name__, observation)) or {"executed": True}
    )
    job = make_job(JobType.SIMULATION, payload)
    assert simulation_job.run(job, node, "report") == {"ran": True}
    assert simulation_job.execute(job, lambda message, progress=None: None, observation="observed") == {"executed": True}
    name = type(SimulationPayload.model_validate(payload).root).__name__
    assert calls == [("run", name, None), ("execute", name, "observed")]
