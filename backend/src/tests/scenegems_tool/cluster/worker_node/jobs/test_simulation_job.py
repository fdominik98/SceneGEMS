"""The simulation job: the payload's runner picks the runner model, the components and the runner's run and in-container part, and the job itself is a relay to the simulation subsystem.

The relay talks to the real simulation service and its real worker in process (in_process_subsystem.py); only
the broker, the worker process and the run's stack are replaced.
"""

import threading

import pytest
from pydantic import ValidationError

from scenegems_tool.cluster.fingerprints.components import RUNNER_STACKS, SimulationRunner
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.messages import LogStream
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.jobs import simulation_job
from scenegems_tool.cluster.worker_node.jobs.simulation_job import RUNNER_MODULES, SimulationPayload, required_components
from scenegems_tool.cluster.worker_node.jobs.simulation_runners.ardupilot_runner import ArduPilotSimulationPayload
from scenegems_tool.cluster.worker_node.jobs.simulation_runners.kinematic_runner import KinematicSimulationPayload
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.messaging.mqtt_simulation_service import MqttSimulationService
from scenegems_tool.subsystems.simulation.simulation_worker import run_task
from tests.scenegems_tool.cluster.payloads import ardupilot_payload, valid_payload
from tests.scenegems_tool.cluster.worker_node.jobs.in_process_subsystem import REQUEST, InProcessSubsystem
from tests.scenegems_tool.subsystems.simulation.simulation_fakes import stand_in_run, task_context

KINEMATIC = ("asv_system/replay", "control_layer/none", "simulation_layer/kinematic")


def test_every_runner_has_a_module_and_the_catalog_names_its_stacks():
    assert set(RUNNER_MODULES) == set(SimulationRunner)
    assert set(RUNNER_STACKS) == set(SimulationRunner) - {SimulationRunner.ATTENDED}, "the attended runner runs whatever its payload's setup names"
    for runner, module in RUNNER_MODULES.items():
        assert callable(module.run) and callable(module.execute)
        assert runner == SimulationRunner.ATTENDED or callable(module.vessel_stacks)
        assert callable(module.PAYLOAD_MODEL.vessel_stacks), "every payload names its vessel stacks"


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
    assert components(valid_payload(JobType.SIMULATION, mode="usv_navigation")) == ("asv_system/replay", "asv_system/usv_navigation", "control_layer/none", "simulation_layer/kinematic")
    assert components(ardupilot_payload("ardupilot_sim")) == ("asv_system/replay", "control_layer/ardupilot", "simulation_layer/ardupilot_sim")
    assert components(ardupilot_payload("gazebo")) == ("asv_system/replay", "control_layer/ardupilot", "simulation_layer/gazebo")


def test_every_payload_stack_is_one_its_runner_declares():
    payloads = [valid_payload(JobType.SIMULATION), valid_payload(JobType.SIMULATION, mode="usv_navigation"), ardupilot_payload("ardupilot_sim"), ardupilot_payload("gazebo")]
    for payload in payloads:
        model = SimulationPayload.model_validate(payload)
        assert set(model.vessel_stacks()) <= set(RUNNER_STACKS[model.runner])


@pytest.mark.parametrize("payload, runner", [(valid_payload(JobType.SIMULATION), SimulationRunner.KINEMATIC), (ardupilot_payload("gazebo"), SimulationRunner.ARDUPILOT)])
def test_the_stack_and_the_in_container_part_go_to_the_runner_with_the_parsed_payload(monkeypatch, make_job, worker_node, payload, runner):
    """run_stack is what a task of the simulation subsystem runs, execute what the run's runner container runs."""
    calls = []
    monkeypatch.setattr(RUNNER_MODULES[runner], "run", lambda job, worker_node, report, parsed, cancel: calls.append(("run", type(parsed).__name__, cancel)) or {"ran": True})
    monkeypatch.setattr(
        RUNNER_MODULES[runner], "execute", lambda job, parsed, status, observation=None, hosting=None: calls.append(("execute", type(parsed).__name__, observation)) or {"executed": True}
    )
    job = make_job(JobType.SIMULATION, payload)
    assert simulation_job.run_stack(job, worker_node, "report") == {"ran": True}
    assert simulation_job.execute(job, lambda message, progress=None: None, observation="observed") == {"executed": True}
    name = type(SimulationPayload.model_validate(payload).root).__name__
    assert calls == [("run", name, None), ("execute", name, "observed")]


# The job as a relay to the simulation subsystem

POOL_NAME = "simulation-subsystem-3"  # the worker node's pool as the control node numbered it


class _Report:
    def __init__(self):
        self.statuses = []
        self.lines = []

    def status(self, message, progress=None, detail=None):
        self.statuses.append((message, progress, detail))

    def log(self, source, text, stream=LogStream.STDOUT):
        self.lines.append((source, text, stream))


@pytest.fixture
def subsystem(monkeypatch, worker_node):
    """The worker node's simulation pool, in process. A run starts no container (run_with); it runs on a thread of its own once its request is in, so the job's signals reach it while it runs."""
    made = InProcessSubsystem(MqttSimulationService, POOL_NAME).serve(monkeypatch, worker_node)
    made.context = task_context()
    made.runs = []

    def run_with(run_stack):
        made.service.pool.worker = lambda task, channel: run_task(task, channel, made.context, run_stack)

    def run_on_a_thread(request_id):
        thread = threading.Thread(target=made.work, args=(request_id,))
        made.runs.append(thread)
        thread.start()

    made.run_with = run_with
    made.hooks[REQUEST] = run_on_a_thread
    run_with(stand_in_run())
    yield made
    for thread in made.runs:
        thread.join(timeout=30)


@pytest.fixture
def simulate(subsystem, worker_node, make_job):
    """Run a simulation job on the subsystem; the job's observation is open, as the daemon opens it for a leased simulation."""

    def run(report=None, cancel=None, **fields):
        job = make_job(JobType.SIMULATION, valid_payload(JobType.SIMULATION, **fields))
        worker_node.observations.open(job)
        try:
            return simulation_job.run(job, worker_node, report or _Report(), cancel)
        finally:
            run.observation = worker_node.observations.close(job)

    return run


def test_the_job_is_one_request_with_its_payload_and_seed_and_its_result_is_the_runs(simulate, subsystem):
    seen = {}
    subsystem.run_with(stand_in_run({"steps": 120, "state_digest": "abc"}, seen=seen))
    assert simulate(seed=9) == {"steps": 120, "state_digest": "abc"}
    assert subsystem.asked == [Subsystem.SIMULATION]
    [(params, seed)] = subsystem.requests()
    assert set(params) == {"job-id", "attempt", "payload"} and (params["job-id"], params["attempt"], seed) == ("job-1", 1, 9), "the run seed of the payload is the request's seed"
    assert params["payload"] == valid_payload(JobType.SIMULATION, seed=9)
    assert (seen["job"].job_id, seen["job"].payload) == ("job-1", params["payload"]) and seen["context"] is subsystem.context
    assert subsystem.states("job-1-1") == ["received", "queued", "running", "finished"] and subsystem.cancels() == []


def test_a_payload_without_a_seed_runs_with_seed_0(simulate, subsystem):
    simulate()
    assert subsystem.requests()[0][1] == 0, "the runners' default: a run repeats exactly"


def test_the_runs_status_with_its_detail_and_its_log_lines_are_the_jobs(simulate):
    report = _Report()
    simulate(report)
    statuses = [status for status in report.statuses if not status[0].startswith("waiting")]
    assert statuses == [("generating the stack", None, {"phase": "preparing"}), ("run finished", 1.0, None)]
    assert report.lines == [("runner", "the stack is up", LogStream.STDOUT), ("runner", "a warning", LogStream.STDERR)]


def test_observe_and_the_operators_start_are_passed_on_and_the_frames_come_back(simulate, subsystem, worker_node, make_job):
    """An attended run: it waits for its Start; somebody observes it at 4 times real time before the task even runs."""
    seen = {}
    subsystem.run_with(stand_in_run(wait_for_start=True, frames=3, seen=seen))
    job = make_job(JobType.SIMULATION, valid_payload(JobType.SIMULATION))
    observation = worker_node.observations.open(job)
    observation.request(True, 4.0)
    observation.start()
    result = simulation_job.run(job, worker_node, _Report())
    assert result["steps"] == 120 and (seen["observed"], seen["speed"]) == (True, 4.0)
    assert subsystem.signals("observe") == [{"active": True, "speed": 4.0}] and subsystem.signals("start") == [None]
    order = [event[:2] for event in subsystem.events if event[0] == "signal" or event[:3] == ("state", "job-1-1", "running")]
    assert order[0] == ("state", "job-1-1"), "nothing is sent before the task runs"
    assert observation.take_batch(force=True) == (1, [{"timestamp": 0}, {"timestamp": 1}, {"timestamp": 2}]), "every frame is with the daemon's observation when the job returns"
    worker_node.observations.close(job)


def test_a_run_that_failed_with_a_reason_fails_the_job_with_it_and_its_retry_rule(simulate, subsystem):
    subsystem.run_with(stand_in_run(failure=JobFailed("Simulation stack rejected: no such layer", retryable=False)))
    with pytest.raises(JobFailed, match="Simulation stack rejected: no such layer") as failure:
        simulate()
    assert not failure.value.retryable and subsystem.cancels() == []
    subsystem.run_with(stand_in_run(failure=JobFailed("timed out after 600 s", retryable=True)))
    with pytest.raises(JobFailed, match="timed out after 600 s") as failure:
        simulate()
    assert failure.value.retryable


def test_a_run_whose_worker_dies_fails_the_attempt_which_may_be_retried(simulate, subsystem):
    subsystem.hooks[REQUEST] = subsystem.die
    with pytest.raises(JobFailed, match="The task of the simulation pool failed: the worker process ended without a result") as failure:
        simulate()
    assert failure.value.retryable


def test_a_cancelled_job_cancels_its_own_run(simulate, subsystem):
    cancel = threading.Event()
    seen = {}
    subsystem.run_with(stand_in_run(seen=seen))
    subsystem.hooks[REQUEST] = lambda request_id: cancel.set()  # the lease is cancelled while the stack runs
    with pytest.raises(JobFailed, match="cancelled") as failure:
        simulate(cancel=cancel)
    assert not failure.value.retryable and subsystem.cancels() == ["job-1-1"]
    subsystem.work("job-1-1")
    assert seen["cancelled"] and subsystem.states("job-1-1")[-1] == "aborted", "the run's stack is told to stop and the task ends without a result"


def test_the_job_has_no_deadline_of_its_own_and_relays_the_detail(make_job, worker_node, monkeypatch):
    calls = {}

    def run_pool_request(job, worker_node_, report, cancel, **request):
        calls.update(request)
        request["is_result"]("simulation_result", {"result": {"steps": 1}, "error": None, "frame-batches": 0, "log-batches": 0})

    monkeypatch.setattr(simulation_job, "run_pool_request", run_pool_request)
    assert simulation_job.run(make_job(JobType.SIMULATION, valid_payload(JobType.SIMULATION)), worker_node, _Report()) == {"steps": 1}
    assert calls["timeout_s"] is None, "the subsystem keeps the run's time rules"
    assert (calls["subsystem"], calls["task_name"], calls["relay_feedback"], calls["relay_detail"]) == (Subsystem.SIMULATION, "run-simulation", True, True)
    assert calls["streams"] == ("simulation_frames", "simulation_log", "simulation_result")


def test_the_result_waits_for_the_batches_it_counts_and_a_batch_delivered_twice_counts_once():
    report = _Report()
    relay = simulation_job.RunRelay(report, None)
    assert not relay.take("simulation_log", {"index": 0, "lines": [{"source": "runner", "text": "one", "stream": "stdout"}]})
    assert not relay.take("simulation_log", {"index": 0, "lines": [{"source": "runner", "text": "one", "stream": "stdout"}]})
    assert not relay.take("simulation_result", {"result": {"steps": 1}, "error": None, "frame-batches": 1, "log-batches": 1}), "a batch of frames is still on its way"
    assert relay.take("simulation_frames", {"index": 0, "frames": [{"timestamp": 0}]}), "nobody observes: the frames are dropped, the batch counts"
    assert report.lines == [("runner", "one", LogStream.STDOUT)] and relay.result() == {"steps": 1}


def test_a_result_that_arrived_stands_when_a_batch_before_it_never_did(make_job, worker_node, monkeypatch):
    def run_pool_request(job, worker_node_, report, cancel, **request):
        request["is_result"]("simulation_result", {"result": {"steps": 1}, "error": None, "frame-batches": 2, "log-batches": 0})
        raise JobFailed("The task of the simulation pool failed: it finished without a result", retryable=True)

    monkeypatch.setattr(simulation_job, "run_pool_request", run_pool_request)
    assert simulation_job.run(make_job(JobType.SIMULATION, valid_payload(JobType.SIMULATION)), worker_node, _Report()) == {"steps": 1}


def test_an_answer_without_a_result_fails_the_attempt():
    relay = simulation_job.RunRelay(_Report(), None)
    relay.take("simulation_result", {"result": None, "error": None})
    with pytest.raises(JobFailed, match="without a result") as failure:
        relay.result()
    assert failure.value.retryable
