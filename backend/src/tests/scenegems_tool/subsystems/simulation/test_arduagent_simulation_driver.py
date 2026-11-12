"""The ArduAgent driver of an attended run with a real vessel: who it talks to, when the vessels are ready, and the scenario clock it follows."""

import threading

import pytest

from concrete_level.models.actor_state import ActorState
from scenegems_tool.gateway.protocol import simulation_config_from_body
from scenegems_tool.messaging.mqtt_agent_client import ExecutionState, MqttAgentClient
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.subsystems.simulation.arduagent_simulation_driver import ArduAgentSimulationDriver, SimulationSubsystemPresence, VesselsNotReady, agent_unit_name
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.registry.resolver import StackUnavailableError
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, encounter_trajectories, stack_instance

SIMULATED_TOPIC = "scenegems/unit/surface/simulation/os-265ca868"
REAL_TOPIC = "scenegems/unit/surface/real/piraya"
SERVICE = "simulation-subsystem-265ca868"


def instance(real_asv_system: str = "on_board"):
    """The own ship simulated on ArduPilot Sim and replayed, the target ship a real vessel."""
    wave = {"amplitude": 0.0, "period": 0.0, "steepness": 0.0, "direction": [0.0, 0.0]}
    connections = {
        "0": {"context": "simulation", "asvSystem": "replay", "controlLayer": "ardupilot", "agentName": "os", "topic": SIMULATED_TOPIC, "port": 14570},
        "1": {"context": "real", "asvSystem": real_asv_system, "controlLayer": "real_vessel", "agentName": "ts1", "topic": REAL_TOPIC},
    }
    return simulation_config_from_body({"simulatorType": "ArduPilot Sim", "windVector": [0.0, 0.0, 0.0], "wave": wave, "simulationSpeed": 1, "connectionsByAgentId": connections})


class FakeAgent:
    """An ArduAgent client without a broker: the test sets what the agent reports. Its control mode properties are MqttAgentClient's."""

    on_board_control_mode = MqttAgentClient.on_board_control_mode
    external_control_mode = MqttAgentClient.external_control_mode

    def __init__(self, vessel, topic, control_mode, agent_name, initial_state, parent_service_name, mission_waypoints, **_):
        self.actor = vessel
        self.topic = topic
        self.control_mode = control_mode
        self.name = agent_name
        self.parent_service_name = parent_service_name
        self.mission_waypoints = mission_waypoints
        self.current_agent_state = initial_state
        self.is_connected = False
        self.position_received = False
        self.is_armable = False
        self.at_start = False
        self.clock = 0.0
        self.execution_state = ExecutionState.STOPPED
        self.commands = []
        self.drawn = None

    def connect(self):
        self.is_connected = True

    def disconnect(self):
        self.is_connected = False

    def at_start_point(self) -> bool:
        return self.at_start

    def publish_follow_path(self, waypoints, speed):
        self.commands.append("follow_path")
        self.execution_state = ExecutionState.RUNNING

    def publish_go_to(self, waypoint, speed):
        self.commands.append("go_to")
        self.execution_state = ExecutionState.RUNNING

    def publish_trajectory(self, waypoints):
        self.drawn = waypoints

    def report_ready(self):
        self.position_received = self.is_armable = self.at_start = True


class FakePresence:
    def __init__(self, name, mqtt_connection, reference_geofence):
        self.name = name
        self.connected = False
        self.heartbeats = []

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def publish_heartbeat(self, stamp):
        self.heartbeats.append(stamp)


class FakeTime:
    """A clock that only moves when the driver sleeps; on_sleep runs after each sleep (the vessels, for example)."""

    def __init__(self, on_sleep=None):
        self.now = 0.0
        self.on_sleep = on_sleep

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        if self.on_sleep is not None:
            self.on_sleep(self)


def connection(root: str = "scenegems") -> MQttConnectionInfo:
    return MQttConnectionInfo("user", "password", "broker", "broker", 1883, False, False, topic_root=root)


def driver_of(clock: FakeTime, timespan: int = 10, real_asv_system: str = "on_board") -> ArduAgentSimulationDriver:
    driver = ArduAgentSimulationDriver(
        instance(real_asv_system),
        encounter_trajectories("head_on", timespan),
        GEOFENCE,
        connection(),
        SERVICE,
        client_factory=FakeAgent,
        presence_factory=FakePresence,
        sleep=clock.sleep,
        clock=clock,
        wall_time=lambda: 1000.0 + clock.now,
    )
    driver.connect()
    return driver


def ready(driver: ArduAgentSimulationDriver) -> ArduAgentSimulationDriver:
    for client in driver.clients.values():
        client.report_ready()
    return driver


def test_every_vessel_has_a_client_at_its_topic_under_the_name_it_has_on_the_broker():
    driver = driver_of(FakeTime())
    simulated, real = driver.clients["0"], driver.clients["1"]
    assert (simulated.topic, simulated.name, simulated.control_mode) == (SIMULATED_TOPIC, "os-265ca868", "autonomous")
    assert (real.topic, real.name, real.control_mode) == (REAL_TOPIC, "piraya", "on_board"), "the agent on board, where the operator said it is"
    assert {client.parent_service_name for client in driver.clients.values()} == {SERVICE}, "the sender of every command"
    assert driver.presence.name == SERVICE and driver.presence.connected
    assert simulated.drawn, "the planned path is handed to the client, which draws it on a WARA-PS broker only"
    driver.close()
    assert not simulated.is_connected and not driver.presence.connected


def test_an_agent_outside_the_unit_layout_keeps_the_vessels_name():
    assert agent_unit_name("waraps/unit/surface/real/piraya", "ts1") == "piraya"
    assert agent_unit_name("lab/boat", "ts1") == "ts1"


def test_the_run_is_ready_when_every_vessel_reports_what_it_needs():
    driver = driver_of(FakeTime())
    assert driver.vessel_states() == {
        "0": {"connected": True, "position": False, "armable": False, "at_start": False},
        "1": {"connected": True, "position": False, "at_start": False},
    }, "a vessel its own software steers is not armed from here, so it is not asked"
    assert not driver.is_ready
    simulated, real = driver.clients["0"], driver.clients["1"]
    simulated.report_ready()
    real.position_received = real.at_start = True
    assert driver.is_ready, "the on-board vessel need not be armable"
    simulated.is_armable = False
    assert not driver.is_ready and driver.vessel_states()["0"]["armable"] is False


def test_a_run_started_before_the_vessels_are_ready_is_refused():
    driver = driver_of(FakeTime())
    with pytest.raises(VesselsNotReady):
        driver.run(lambda time_s, scene: None, threading.Event())
    assert driver.clients["0"].commands == [], "nothing was sent to a vessel"


def test_the_run_commands_the_vessels_and_follows_their_clocks_to_the_time_span():
    def the_vessels(clock: FakeTime) -> None:
        simulated.clock = 500.0 + clock.now  # SITL's own time, at the pace of the wall clock here
        simulated.current_agent_state = ActorState(clock.now, 0.0, 1.0, 0.0)

    clock = FakeTime(on_sleep=the_vessels)
    driver = ready(driver_of(clock))
    simulated, real = driver.clients["0"], driver.clients["1"]
    simulated.clock = 500.0
    seen = []
    run = driver.run(lambda time_s, scene: seen.append((time_s, clock.now)), threading.Event())

    assert simulated.commands == ["follow_path"] and real.commands == [], "the on-board vessel is only observed"
    assert [time_s for time_s, _ in seen] == [float(t) for t in range(11)], "one scene per time step, the start included"
    assert all(abs(wall - time_s) < 0.1 for time_s, wall in seen), "a step is shown when every vessel has reached it"
    assert run.steps == 10 and len(run.states) == 11 and run.vessel_ids == [0, 1]
    assert run.states[-1][0].x == pytest.approx(10.0, abs=0.1), "where the agent reported the vessel"
    record = run.run_record
    assert record["steps"] == 10 and record["state_digest"] == run.state_digest() and record["repeatability_tier"] == "none", "a real vessel is run once"
    assert record["vessel_topics"] == {"0": SIMULATED_TOPIC, "1": REAL_TOPIC} and record["real_vessels"] == ["1"] and record["broker"] == "broker:1883"
    assert record["wall_clock_vessels"] == ["1"], "the real vessel reported no clock, so the wall clock is its clock"
    assert "ended_early" not in record and "password" not in str(record)


def test_the_scenario_clock_slows_down_with_the_slowest_simulator():
    def a_slow_simulator(clock: FakeTime) -> None:
        simulated.clock = 500.0 + clock.now / 2

    clock = FakeTime(on_sleep=a_slow_simulator)
    driver = ready(driver_of(clock, timespan=4))
    simulated = driver.clients["0"]
    simulated.clock = 500.0
    seen = []
    driver.run(lambda time_s, scene: seen.append((time_s, clock.now)), threading.Event())
    assert [round(wall / time_s) for time_s, wall in seen[1:]] == [2, 2, 2, 2], "half the pace of the wall clock, which the real vessel is on"


def test_mission_planner_on_a_real_vessel_is_sent_toward_its_last_waypoint():
    clock = FakeTime(on_sleep=lambda clock: None)
    driver = ready(driver_of(clock, timespan=2, real_asv_system="mission_planner"))
    driver.run(lambda time_s, scene: None, threading.Event())
    assert driver.clients["1"].commands == ["go_to"] and driver.clients["0"].commands == ["follow_path"]


def test_the_run_ends_early_when_a_commanded_vessel_stops():
    def the_task_ends(clock: FakeTime) -> None:
        if clock.now >= 3.5:
            driver.clients["0"].execution_state = ExecutionState.STOPPED

    clock = FakeTime(on_sleep=the_task_ends)
    driver = ready(driver_of(clock))
    run = driver.run(lambda time_s, scene: None, threading.Event())
    assert run.steps == 3 and run.run_record["ended_early"] is True


def test_a_stopped_run_returns_nothing():
    stop = threading.Event()

    def stop_it(clock: FakeTime) -> None:
        if clock.now >= 2.0:
            stop.set()

    driver = ready(driver_of(FakeTime(on_sleep=stop_it)))
    assert driver.run(lambda time_s, scene: None, stop) is None


def test_the_subsystem_heartbeat_goes_out_once_a_second_however_often_it_is_asked():
    clock = FakeTime()
    driver = driver_of(clock)
    for _ in range(250):
        driver.heartbeat()
        clock.sleep(0.01)
    assert driver.presence.heartbeats == [1000.0, pytest.approx(1001.0, abs=0.02), pytest.approx(1002.0, abs=0.03)]


def test_before_the_run_the_scene_is_where_the_agents_report_the_vessels():
    driver = driver_of(FakeTime())
    initial = driver.trajectories.initial_scene
    assert driver.current_scene == initial, "until an agent reports a position"
    simulated = driver.clients["0"]
    simulated.position_received = True
    simulated.current_agent_state = ActorState(42.0, 7.0, 0.0, 0.0)
    scene = driver.current_scene
    assert scene[simulated.actor].x == 42.0 and scene[driver.clients["1"].actor] == initial[driver.clients["1"].actor]


def test_an_instance_of_lockstep_vessels_is_not_this_drivers():
    lockstep = stack_instance(SimulationLayerId.KINEMATIC, [0, 1], control_layer=ControlLayerId.NONE)
    with pytest.raises(StackUnavailableError, match="only through ArduAgent"):
        ArduAgentSimulationDriver(lockstep, encounter_trajectories("head_on", 10), GEOFENCE, connection(), SERVICE)


def test_the_presence_is_a_service_agent_under_the_brokers_root():
    presence = SimulationSubsystemPresence(SERVICE, connection("waraps"), GEOFENCE)
    assert presence.heartbeat_topic == f"waraps/service/virtual/real/{SERVICE}/heartbeat" and presence.listen_topics == []
