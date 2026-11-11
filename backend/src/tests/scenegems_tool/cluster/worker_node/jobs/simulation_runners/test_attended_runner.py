"""The attended runner of the simulation job: its payload, its stack with a published ground control port, the wait for the operator's Start and the run.

With a real vessel: the topics of the vessels, the broker, the stack's ArduAgents and the readiness the job reports before the Start.
"""

import io

import pytest
from pydantic import ValidationError

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.jobs import simulation_job
from scenegems_tool.cluster.worker_node.jobs.in_container.run_observation import ContainerObservation
from scenegems_tool.cluster.worker_node.jobs.simulation_runners import attended_runner
from scenegems_tool.cluster.worker_node.jobs.simulation_runners.attended_runner import AttendedSimulationPayload, simulation_instance
from scenegems_tool.cluster.worker_node.jobs.simulation_runners.vessel_job_stack import build_vessel_job_stack, ground_control_ports
from scenegems_tool.cluster.worker_node.launchers.per_job.job_container_io import OBSERVE_DOCUMENT, ObservationControl, parse_frame_line
from scenegems_tool.cluster.worker_node.launchers.per_job.job_stack import RUNNER_SERVICE, project_compose
from scenegems_tool.subsystems.simulation.arduagent_simulation_driver import ArduAgentRun, VesselsNotReady
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
        (setup("ArduPilot Sim", agent_1={"context": "real", "controlLayer": "real_vessel", "port": None}), "needs the topic of its agent"),
        (setup("ArduPilot Sim", agent_1={"context": "real", "controlLayer": "real_vessel", "port": None, "topic": "waraps/unit/+/real/piraya"}), "without wildcards"),
        (setup("ArduPilot Sim", agent_1={"context": "real", "port": None, "topic": "waraps/unit/surface/real/piraya"}), "its own autopilot"),
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


# A real vessel

REAL_TOPIC = "waraps/unit/surface/real/piraya"
BROKER = {"host": "broker.waraps.org", "port": 8883, "tls": True, "user": "lab", "password": "secret"}


def real_setup(asv_system: str = "on_board", **own_ship) -> dict:
    """The own ship simulated on ArduPilot Sim, the target ship a real vessel whose agent is at REAL_TOPIC."""
    real = {"context": "real", "asvSystem": asv_system, "controlLayer": "real_vessel", "port": None, "topic": f"{REAL_TOPIC}/"}
    return setup("ArduPilot Sim", agent_0=own_ship, agent_1=real)


def test_a_real_vessel_keeps_its_topic_and_a_simulated_one_gets_the_jobs(head_on_trajectories):
    payload = AttendedSimulationPayload.model_validate(payload_of(head_on_trajectories, real_setup()))
    vessels = payload.instance("265ca868-1f2e-4a7b").vessels
    assert payload.topic_root == "scenegems", "the cluster's broker unless the payload names another"
    assert (vessels["0"].connection.agent_name, vessels["0"].connection.topic) == ("os", "scenegems/unit/surface/simulation/os-265ca868")
    assert (vessels["1"].connection.agent_name, vessels["1"].connection.topic) == ("ts1", REAL_TOPIC), "where the agent on board publishes, without the trailing slash"
    assert payload.instance().vessels["0"].connection.topic == "scenegems/unit/surface/simulation/os", "a payload that is only validated has no job yet"
    assert vessels["0"].adapter_ids == ("replay_arduagent_follower",), "beside a real vessel every vessel runs through ArduAgent"


def test_an_external_broker_puts_the_simulated_vessels_under_waraps(head_on_trajectories):
    payload = AttendedSimulationPayload.model_validate(payload_of(head_on_trajectories, real_setup(), broker=BROKER))
    assert payload.topic_root == "waraps" and payload.instance("265ca868").vessels["0"].connection.topic == "waraps/unit/surface/simulation/os-265ca868"
    connection = payload.broker.connection()
    assert (connection.agent_broker, connection.client_broker, connection.port, connection.tls_connection) == ("broker.waraps.org", "broker.waraps.org", 8883, True)
    assert (connection.user, connection.password, connection.topic_root) == ("lab", "secret", "waraps")


def test_a_broker_without_a_real_vessel_and_two_vessels_at_one_topic_are_refused(head_on_trajectories):
    with pytest.raises(ValidationError, match="only to a setup with a real vessel"):
        AttendedSimulationPayload.model_validate(payload_of(head_on_trajectories, setup("ArduPilot Sim"), broker=BROKER))
    both_real = real_setup()
    both_real["connectionsByAgentId"]["0"] = dict(both_real["connectionsByAgentId"]["1"])
    with pytest.raises(ValidationError, match="have the same topic"):
        AttendedSimulationPayload.model_validate(payload_of(head_on_trajectories, both_real))


def test_a_real_vessel_needs_its_components(head_on_trajectories):
    payload = simulation_job.SimulationPayload.model_validate(payload_of(head_on_trajectories, real_setup()))
    assert simulation_job.required_components(payload) == (
        "asv_system/replay",
        "asv_system/on_board",
        "control_layer/ardupilot",
        "control_layer/real_vessel",
        "simulation_layer/ardupilot_sim",
        "simulation_layer/real_vessel",
    )


def real_stack(worker_node, make_job, head_on_trajectories, simulation, **fields):
    data = payload_of(head_on_trajectories, simulation, **fields)
    payload = AttendedSimulationPayload.model_validate(data)
    job = make_job(JobType.SIMULATION, data)
    instance = payload.instance(job.job_id)
    connection = None if payload.broker is None else payload.broker.connection()
    stack = build_vessel_job_stack(
        job, worker_node, instance, head_on_trajectories, payload.geofence.to_geofence(), attended=True, mqtt_connection=connection, service_name=worker_node.job_scope(job).instance_id
    )
    return instance, stack


def environment_of(service: dict) -> dict:
    environment = service["environment"]
    return dict(item.split("=", 1) for item in environment) if isinstance(environment, list) else dict(environment)


def test_beside_a_real_vessel_a_simulated_one_has_an_arduagent_on_the_cluster_broker(instances_folder, worker_node, make_job, head_on_trajectories):
    instance, stack = real_stack(worker_node, make_job, head_on_trajectories, real_setup())
    services = stack.compose["services"]
    assert set(services) == {"os", "os_mavproxy", "os_arduagent", RUNNER_SERVICE}, "the real vessel has no container"
    agent = environment_of(services["os_arduagent"])
    assert (agent["NAME"], agent["REAL_SIM"], agent["MQTT_TOPIC_ROOT"]) == ("os-job-1", "simulation", "scenegems"), "the vessel and the job, under the cluster's first level"
    assert agent["OTHER_POSITIONS_TOPICS"] == f"{REAL_TOPIC}/sensor/position", "it takes the positions of its own run's vessels only"
    assert (agent["BROKER"], agent["PORT"]) == ("broker", "1883")
    runner = environment_of(services[RUNNER_SERVICE])
    assert (runner["MQTT_BROKER"], runner["MQTT_PORT"], runner["MQTT_SERVICE_NAME"]) == ("broker", "1883", "simulation-subsystem-job-1")
    on_the_broker_network = sorted(name for name, service in services.items() if "scenegems_broker" in service.get("networks", []))
    assert on_the_broker_network == ["os_arduagent", "os_mavproxy", RUNNER_SERVICE], "what talks to the broker joins its network; SITL does not"
    assert stack.compose["networks"]["scenegems_broker"]["external"] is True
    assert ground_control_ports(instance) == {} and not any("ports" in service for service in services.values()), "no Mission Planner, no published port"


def test_an_external_broker_is_dialled_from_the_stacks_own_network(instances_folder, worker_node, make_job, head_on_trajectories):
    _, stack = real_stack(worker_node, make_job, head_on_trajectories, real_setup(), broker=BROKER)
    services = stack.compose["services"]
    agent = environment_of(services["os_arduagent"])
    assert (agent["BROKER"], agent["PORT"], agent["TLS_CERTIFICE"], agent["MQTT_USER"], agent["MQTT_PASSWORD"]) == ("broker.waraps.org", "8883", "1", "lab", "secret")
    assert agent["NAME"] == "os-job-1" and "MQTT_TOPIC_ROOT" not in agent, "waraps is the agent's own default"
    runner = environment_of(services[RUNNER_SERVICE])
    assert (runner["MQTT_BROKER"], runner["MQTT_TLS"], runner["MQTT_USER"]) == ("broker.waraps.org", "1", "lab") and "MQTT_TOPIC_ROOT" not in runner
    assert "scenegems_broker" not in stack.compose["networks"] and all("scenegems_broker" not in service.get("networks", []) for service in services.values())


def test_mission_planner_beside_a_real_vessel_reaches_its_vessel_through_the_arduagent_mavproxy(instances_folder, worker_node, make_job, head_on_trajectories):
    instance, stack = real_stack(worker_node, make_job, head_on_trajectories, real_setup(asvSystem="mission_planner"))
    assert ground_control_ports(instance) == {"0": ("os_mavproxy", 5770)}
    services = stack.compose["services"]
    assert services["os_mavproxy"]["ports"] == ["5770"] and "--out=tcpin:0.0.0.0:5770" in services["os_mavproxy"]["command"][-1]
    assert [key for key, service in services.items() if "ports" in service] == ["os_mavproxy"]


def test_a_stack_of_simulated_vessels_talks_to_no_broker(instances_folder, worker_node, make_job, head_on_trajectories):
    _, stack = real_stack(worker_node, make_job, head_on_trajectories, setup("ArduPilot Sim"))
    assert environment_of(stack.compose["services"][RUNNER_SERVICE]) == {"PYTHONUNBUFFERED": "1"} and "scenegems_broker" not in stack.compose["networks"]


class FakeArduAgentDriver:
    """The ArduAgent driver without a broker: the real vessel reports its position after ready_at seconds of the observation's clock."""

    kind = "arduagent"

    def __init__(self, trajectories, clock, ready_at: float = 4.0, connects: bool = True):
        self.trajectories = trajectories
        self.clock = clock
        self.ready_at = ready_at
        self.connects = connects
        self.heartbeats = 0
        self.closed = False

    def connect(self) -> None:
        if not self.connects:
            raise RuntimeError("simulation-subsystem-job-1 could not reach broker mqtt://broker:1883: connection refused")

    def close(self) -> None:
        self.closed = True

    def heartbeat(self) -> None:
        self.heartbeats += 1

    def vessel_states(self) -> dict:
        there = self.clock.now >= self.ready_at
        return {"0": {"connected": True, "position": True, "armable": True, "at_start": True}, "1": {"connected": True, "position": there, "at_start": there}}

    @property
    def current_scene(self):
        return self.trajectories.initial_scene

    def run(self, on_scene, stop):
        if not all(all(state.values()) for state in self.vessel_states().values()):
            raise VesselsNotReady("the vessels are not ready to start")
        run = ArduAgentRun(vessel_ids=[0, 1], run_record={"repeatability_tier": "none", "real_vessels": ["1"]})
        scene = self.trajectories.initial_scene
        for index in range(4):
            run.states.append([scene[actor] for actor in scene.actors])
            on_scene(float(index), scene)
        return run


def with_driver(monkeypatch, head_on_trajectories, clock, **options) -> FakeArduAgentDriver:
    driver = FakeArduAgentDriver(head_on_trajectories, clock, **options)
    monkeypatch.setattr(attended_runner, "arduagent_driver", lambda payload, instance, trajectories: driver)
    return driver


def test_a_run_with_a_real_vessel_is_ready_when_its_vessels_are_and_starts_with_the_operator(monkeypatch, make_job, head_on_trajectories, tmp_path):
    write_request(tmp_path, active=True, speed=1.0, revision=1)

    def the_operator(clock: FakeTime) -> None:
        if clock.now >= 8.0:
            write_request(tmp_path, active=True, speed=1.0, revision=2, started=True)

    clock = FakeTime(on_sleep=the_operator)
    driver = with_driver(monkeypatch, head_on_trajectories, clock)
    observation, out = observed(tmp_path, clock)
    statuses = Statuses()
    result = simulation_job.execute(make_job(JobType.SIMULATION, payload_of(head_on_trajectories, real_setup(), monitor="live")), statuses, observation=observation)

    assert statuses.phases == ["preparing", "ready_to_start", "running", "running"], "one status per change, not one per look"
    message, detail = statuses.seen[0]
    assert message == "waiting for the vessels (ts1: position, at_start)" and detail["vessels"]["1"] == {"connected": True, "position": False, "at_start": False}
    assert statuses.seen[1][1]["vessels"]["1"] == {"connected": True, "position": True, "at_start": True}
    assert statuses.seen[2][0] == "running the attended arduagent run with the live monitor"
    assert result["steps"] == 3 and result["run_record"]["real_vessels"] == ["1"] and result["monitor"]["scenes"] == 4 and "trajectories" in result
    frames = [parse_frame_line(line) for line in out.getvalue().splitlines()]
    assert len([frame for frame in frames if frame["timestamp"] == 0]) > 2, "while it waits an observer sees where the vessels are"
    assert driver.heartbeats > 2 and driver.closed, "the subsystem's heartbeat goes on while it waits, and the clients are closed after the run"


def test_vessels_that_never_get_ready_fail_the_job_with_what_they_lack(monkeypatch, make_job, head_on_trajectories, tmp_path):
    write_request(tmp_path, active=False, speed=1.0, revision=1)
    clock = FakeTime()
    driver = with_driver(monkeypatch, head_on_trajectories, clock, ready_at=1e9)
    observation, _ = observed(tmp_path, clock)
    job = make_job(JobType.SIMULATION, payload_of(head_on_trajectories, real_setup(), start_timeout_s=30.0))
    with pytest.raises(JobFailed, match=r"the vessels were not ready to start within 30 s \(ts1: position, at_start\)") as failure:
        simulation_job.execute(job, Statuses(), observation=observation)
    assert not failure.value.retryable and driver.closed


def test_a_run_nobody_can_start_fails_when_its_vessels_are_not_ready(monkeypatch, make_job, head_on_trajectories):
    with_driver(monkeypatch, head_on_trajectories, FakeTime(), ready_at=1e9)
    with pytest.raises(JobFailed, match=r"the vessels are not ready to start \(ts1: position, at_start\)") as failure:
        simulation_job.execute(make_job(JobType.SIMULATION, payload_of(head_on_trajectories, real_setup())), Statuses())
    assert not failure.value.retryable


def test_a_broker_that_cannot_be_reached_fails_the_job(monkeypatch, make_job, head_on_trajectories):
    driver = with_driver(monkeypatch, head_on_trajectories, FakeTime(), connects=False)
    with pytest.raises(JobFailed, match="the run's broker cannot be reached: .*connection refused") as failure:
        simulation_job.execute(make_job(JobType.SIMULATION, payload_of(head_on_trajectories, real_setup())), Statuses())
    assert not failure.value.retryable and driver.closed


def test_the_drivers_broker_and_name_come_from_the_runners_environment(monkeypatch, head_on_trajectories):
    for name, value in {"MQTT_BROKER": "broker", "MQTT_PORT": "1883", "MQTT_TOPIC_ROOT": "scenegems", "MQTT_SERVICE_NAME": "simulation-subsystem-265ca868"}.items():
        monkeypatch.setenv(name, value)
    payload = AttendedSimulationPayload.model_validate(payload_of(head_on_trajectories, real_setup()))
    driver = attended_runner.arduagent_driver(payload, payload.instance("265ca868"), head_on_trajectories)
    assert (driver.service_name, driver.mqtt_connection.client_broker, driver.mqtt_connection.topic_root) == ("simulation-subsystem-265ca868", "broker", "scenegems")
