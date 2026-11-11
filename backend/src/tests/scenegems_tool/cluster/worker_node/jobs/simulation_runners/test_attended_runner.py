"""The attended runner of the simulation job: its payload, its stack with a published ground control port, the wait for the operator's Start and the run."""

import io

import pytest
from pydantic import ValidationError

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.jobs import simulation_job
from scenegems_tool.cluster.worker_node.jobs.in_container.run_observation import ContainerObservation
from scenegems_tool.cluster.worker_node.jobs.simulation_runners.attended_runner import AttendedSimulationPayload, simulation_instance
from scenegems_tool.cluster.worker_node.jobs.simulation_runners.vessel_job_stack import build_vessel_job_stack, ground_control_ports
from scenegems_tool.cluster.worker_node.launchers.per_job.job_container_io import OBSERVE_DOCUMENT, ObservationControl, parse_frame_line
from scenegems_tool.cluster.worker_node.launchers.per_job.job_stack import RUNNER_SERVICE, project_compose
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import run_kinematic_replay

GEOFENCE = {"latitude": 57.7, "longitude": 11.9, "radius_meters": 2000.0}


def setup(simulator: str = "Kinematic", **vessels) -> dict:
    """A workbench setup of the two vessels of the head-on scenario; a keyword per agent id changes that vessel (agent_0=dict(asvSystem=...))."""
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
    # A kinematic run follows the wall clock at its speed-up: fast here, so the 120 s of the scenario take a fraction of a second
    return {"simulatorType": simulator, "windVector": [0.0, 0.0, 0.0], "wave": wave, "simulationSpeed": 2000 if simulator == "Kinematic" else 1, "connectionsByAgentId": connections}


def payload_of(head_on_trajectories, simulation=None, **fields) -> dict:
    return {"runner": "attended", "simulation": simulation or setup(), "trajectories": head_on_trajectories.to_dict(), "geofence": GEOFENCE, **fields}


class Statuses:
    def __init__(self):
        self.seen = []

    def __call__(self, message, progress=None, detail=None):
        self.seen.append((message, detail))

    @property
    def phases(self):
        return [detail["phase"] for _, detail in self.seen if detail]


class FakeTime:
    """A clock that only moves when the run sleeps; on_sleep runs after each sleep (the operator, for example)."""

    def __init__(self, on_sleep=None):
        self.now = 0.0
        self.sleeps = 0
        self.on_sleep = on_sleep

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.sleeps += 1
        if self.on_sleep is not None:
            self.on_sleep(self)


# The payload


def test_the_payload_is_the_workbenchs_setup_with_every_vessel_named_as_the_vessel(head_on_trajectories):
    payload = AttendedSimulationPayload.model_validate(payload_of(head_on_trajectories))
    instance = simulation_instance(payload.simulation, payload.seed)
    assert {agent_id: vessel.connection.agent_name for agent_id, vessel in instance.vessels.items()} == {"0": "os", "1": "ts1"}, "not the names typed on the workbench"
    assert [tuple(layer.value for layer in stack) for stack in payload.vessel_stacks()] == [("replay", "none", "kinematic")]
    assert (payload.start_timeout_s, payload.timeout_s) == (3600.0, 3600.0)


def test_a_mission_planner_vessel_needs_the_mission_planner_component(head_on_trajectories):
    simulation = setup("ArduPilot Sim", agent_0={"asvSystem": "mission_planner"})
    payload = simulation_job.SimulationPayload.model_validate(payload_of(head_on_trajectories, simulation))
    components = simulation_job.required_components(payload)
    assert components == ("asv_system/replay", "asv_system/mission_planner", "control_layer/ardupilot", "simulation_layer/ardupilot_sim")


@pytest.mark.parametrize(
    "simulation, reason",
    [
        (setup(agent_1={"context": "real", "port": None}), "real vessel"),
        ({**setup(), "connectionsByAgentId": {}}, "no vessel"),
        ({**setup(), "simulatorType": "Webots"}, "Webots"),
        ({"simulatorType": "Kinematic"}, "incomplete"),
    ],
)
def test_a_setup_the_runner_cannot_run_is_refused_with_the_payload(head_on_trajectories, simulation, reason):
    with pytest.raises(ValidationError, match=reason):
        AttendedSimulationPayload.model_validate(payload_of(head_on_trajectories, simulation))


def test_the_monitors_constants_need_the_live_monitor(head_on_trajectories):
    with pytest.raises(ValidationError, match="monitor live"):
        AttendedSimulationPayload.model_validate(payload_of(head_on_trajectories, colregs_constraints_content="rules: []"))


# The stack


def stack_of(worker_node, make_job, head_on_trajectories, simulation):
    data = payload_of(head_on_trajectories, simulation)
    payload = AttendedSimulationPayload.model_validate(data)
    job = make_job(JobType.SIMULATION, data)
    instance = simulation_instance(payload.simulation)
    return instance, build_vessel_job_stack(job, worker_node, instance, head_on_trajectories, payload.geofence.to_geofence(), attended=True)


def test_a_kinematic_attended_stack_is_the_stack_of_the_kinematic_job(instances_folder, worker_node, make_job, head_on_trajectories):
    instance, stack = stack_of(worker_node, make_job, head_on_trajectories, setup())
    assert set(stack.compose["services"]) == {"kinematic_sim", "os_asv_system", "ts1_asv_system", RUNNER_SERVICE}
    assert ground_control_ports(instance) == {} and not any("ports" in service for service in stack.compose["services"].values())


def test_mission_planners_port_stays_published_and_is_what_the_job_reports(instances_folder, worker_node, make_job, head_on_trajectories):
    instance, stack = stack_of(worker_node, make_job, head_on_trajectories, setup("ArduPilot Sim", agent_0={"asvSystem": "mission_planner"}))
    assert ground_control_ports(instance) == {"0": ("os_mavproxy", 5770)}, "by agent id: the service and the container port a ground control station reaches"
    services = stack.compose["services"]
    assert services["os_mavproxy"]["ports"] == ["5770"], "Docker assigns the host port"
    assert [key for key, service in services.items() if "ports" in service] == ["os_mavproxy"], "no other port of the stack is published"
    document = project_compose(stack.scope, stack.compose)
    assert "ports" in document["services"][stack.scope.service_key("os_mavproxy")]


def test_an_unattended_job_still_refuses_mission_planner(instances_folder, worker_node, make_job, head_on_trajectories):
    data = payload_of(head_on_trajectories, setup("ArduPilot Sim", agent_0={"asvSystem": "mission_planner"}))
    instance = simulation_instance(data["simulation"])
    with pytest.raises(JobFailed, match="Simulation stack rejected"):
        build_vessel_job_stack(make_job(JobType.SIMULATION, data), worker_node, instance, head_on_trajectories, worker_node.reference_geofence)


# The run, with the layers hosted in process


def test_a_run_nobody_can_start_runs_at_once_and_is_the_kinematic_replay(make_job, head_on_trajectories):
    statuses = Statuses()
    result = simulation_job.execute(make_job(JobType.SIMULATION, payload_of(head_on_trajectories)), statuses)
    replay = run_kinematic_replay(head_on_trajectories)
    assert result["state_digest"] == replay.state_digest() and result["steps"] == replay.steps
    assert statuses.phases == ["ready_to_start", "running", "running"], "the job says where it is"
    assert "monitor" not in result and result["trajectories"]["time_step"] == head_on_trajectories.time_step


def test_the_live_monitor_judges_the_attended_run(make_job, head_on_trajectories):
    result = simulation_job.execute(make_job(JobType.SIMULATION, payload_of(head_on_trajectories, monitor="live")), Statuses())
    assert result["monitor"]["scenes"] == result["steps"] + 1 and "passed" in result["monitor"]


def observed(tmp_path, clock: FakeTime) -> tuple:
    out = io.StringIO()
    return ContainerObservation(str(tmp_path), out=out, clock=clock, sleep=clock.sleep), out


def write_request(tmp_path, **fields) -> None:
    (tmp_path / OBSERVE_DOCUMENT).write_text(ObservationControl(**fields).to_document(), encoding="utf-8")


def test_the_run_waits_for_the_operators_start_and_shows_where_it_starts(make_job, head_on_trajectories, tmp_path):
    write_request(tmp_path, active=True, speed=10.0, revision=1)

    def the_operator(clock: FakeTime) -> None:
        if clock.now >= 5.0:
            write_request(tmp_path, active=True, speed=10.0, revision=2, started=True)

    clock = FakeTime(on_sleep=the_operator)
    observation, out = observed(tmp_path, clock)
    statuses = Statuses()
    result = simulation_job.execute(make_job(JobType.SIMULATION, payload_of(head_on_trajectories)), statuses, observation=observation)
    frames = [parse_frame_line(line) for line in out.getvalue().splitlines()]
    waiting = [frame for frame in frames[:3] if frame["timestamp"] == 0]
    assert len(waiting) == 3, "while it waited: the scene the run starts from, every two seconds, then the run's own first step"
    assert frames[-1]["timestamp"] == 120 and result["state_digest"] == run_kinematic_replay(head_on_trajectories).state_digest()
    assert statuses.seen[0] == ("ready to start", {"phase": "ready_to_start"}) and statuses.phases[1] == "running"


def test_a_run_nobody_starts_ends_as_a_failure_that_is_not_retried(make_job, head_on_trajectories, tmp_path):
    write_request(tmp_path, active=False, speed=1.0, revision=1)
    observation, out = observed(tmp_path, FakeTime())
    job = make_job(JobType.SIMULATION, payload_of(head_on_trajectories, start_timeout_s=30.0))
    with pytest.raises(JobFailed, match="nobody started the run within 30 s") as failure:
        simulation_job.execute(job, Statuses(), observation=observation)
    assert not failure.value.retryable and out.getvalue() == "", "nobody observed, so nothing was shown either"
