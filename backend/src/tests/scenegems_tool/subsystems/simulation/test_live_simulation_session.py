"""LiveSimulationSession: status reporting, scene streaming and teardown, with the container and MQTT client faked.

Ported from the old test_mqtt_session_task_lifecycle.py, which tested OldWARAPSSession of
scenegems_tool.subsystems_integration.mqtt_session (start, abort and reset of the agents, and the
runtime tasks that stayed alive). That class no longer exists: the session now relays the simulation
worker's state over MQTT, so the checks are on the commands it publishes and on the state
it forwards to the monitor and the browser.
"""

from types import SimpleNamespace
from typing import List

import pytest

from scenegems_tool.gateway.protocol import SimulationStatus
from scenegems_tool.subsystems.simulation import live_simulation_session
from scenegems_tool.subsystems.simulation.live_simulation_session import LiveSimulationSession
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId, SimulationLayerId
from tests.scenegems_tool.gateway.conftest import settle
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, encounter_trajectories, mqtt_connection, stack_instance

pytestmark = pytest.mark.anyio


class FakeClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.on_simulation_state = kwargs["on_simulation_state"]
        self.connected = False
        self.disconnected = False
        self.is_connected = True
        self.is_heartbeat_valid = True
        self.is_service_ready = True
        self.latest_status = SimulationStatus.READY_TO_START
        self.start_commands = 0
        self.start_error: Exception | None = None

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.disconnected = True

    def publish_start_simulation_command(self):
        if self.start_error is not None:
            raise self.start_error
        self.start_commands += 1


class FakeContainer:
    service_topic = "waraps/service/virtual/real/simulation_service"

    def __init__(self, *args, on_ground_control_ports=None, scope=None):
        self.args = args
        self.on_ground_control_ports = on_ground_control_ports
        self.scope = scope
        self.cancelled = False
        self.destroyed = False

    def cancel(self):
        self.cancelled = True

    def destroy(self):
        self.destroyed = True


class RecordingMonitor:
    def __init__(self):
        self.steps: List[tuple] = []
        self.batches: List[tuple] = []

    def step_simulation_monitor(self, scenario_id, scene, timestamp, time_step):
        self.steps.append((scenario_id, timestamp, time_step))

    def step_simulation_monitor_batch(self, scenario_id, scenes, timestamps, time_step):
        self.batches.append((scenario_id, list(timestamps), time_step))


@pytest.fixture
async def setup(monkeypatch):
    monkeypatch.setattr(live_simulation_session, "MqttSimulationClient", FakeClient)
    monkeypatch.setattr(live_simulation_session, "SimulationSessionStack", type("Container", (FakeContainer,), {"service_topic": FakeContainer.service_topic}))
    sent: List[dict] = []
    monitor = RecordingMonitor()
    trajectories = encounter_trajectories("head_on", 30)
    config = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=["replay_arduagent_follower"])
    session = LiveSimulationSession(
        simulation_config=config,
        trajectories=trajectories,
        scenario_session=SimpleNamespace(scenario_id="scenario-1"),
        mqtt_connection=mqtt_connection(),
        reference_geofence=GEOFENCE,
        monitor_session=monitor,
        send_payload=sent.append,
    )
    yield SimpleNamespace(session=session, sent=sent, monitor=monitor, trajectories=trajectories, config=config)
    session.status_update_worker.cancel()


def state_message(setup, status: SimulationStatus, clock: float = 0.0, with_scene: bool = True, step: int = 0) -> dict:
    scene = setup.trajectories.scene_list[step]
    return {"status": status.value, "clock": clock, "scene": scene.to_dict() if with_scene else None}


def statuses(setup) -> List[str]:
    return [payload["status"] for payload in setup.sent if payload["type"] == "simulation_status"]


class TestConstruction:
    async def test_starts_initializing_and_says_so(self, setup):
        assert setup.session.status == SimulationStatus.INITIALIZING
        assert statuses(setup) == ["initializing"]

    async def test_generates_the_vessel_models_for_the_configuration(self, setup):
        assert all(vessel.gazebo_vessel_model for vessel in setup.config.vessels.values())
        assert any(payload["type"] == "simulation_models" for payload in setup.sent)

    async def test_kinematic_vessels_get_no_gazebo_model(self, setup):
        config = stack_instance(SimulationLayerId.KINEMATIC, [0, 1], control_layer=ControlLayerId.NONE)
        setup.session.generate_vessel_models(setup.trajectories.initial_scene, config)
        assert all(vessel.gazebo_vessel_model is None for vessel in config.vessels.values())
        assert setup.sent[-1]["type"] == "simulation_models" and setup.sent[-1]["simulatorType"] == "Kinematic"

    async def test_connects_a_client_that_reports_to_the_state_handler(self, setup):
        client = setup.session._client
        assert client.connected
        assert client.on_simulation_state == setup.session._handle_simulation_state

    async def test_is_connected_needs_a_live_heartbeat(self, setup):
        assert setup.session.is_connected
        setup.session._client.is_heartbeat_valid = False
        assert not setup.session.is_connected


class TestStartCommand:
    async def test_start_publishes_the_start_command(self, setup):
        setup.session.start_simulation_runtime()
        assert setup.session._client.start_commands == 1
        assert not [payload for payload in setup.sent if payload["type"] == "error"]

    async def test_a_failed_publish_is_reported_to_the_browser(self, setup):
        setup.session._client.start_error = RuntimeError("broker gone")
        setup.session.start_simulation_runtime()
        assert {"type": "error", "message": "Failed to start simulation: broker gone"} in setup.sent


class TestStatus:
    async def test_before_the_service_is_ready_the_status_is_initializing(self, setup):
        setup.session._client.is_service_ready = False
        assert setup.session._status_update() == SimulationStatus.INITIALIZING
        assert setup.session._resolve_simulation_status(SimulationStatus.RUNNING) == SimulationStatus.INITIALIZING

    async def test_once_ready_the_workers_status_is_used(self, setup):
        assert setup.session._status_update() == SimulationStatus.READY_TO_START
        assert setup.session._resolve_simulation_status(SimulationStatus.RUNNING) == SimulationStatus.RUNNING

    async def test_a_new_status_is_sent_once(self, setup):
        setup.session._handle_simulation_state(state_message(setup, SimulationStatus.AGENTS_ARE_PREPARING))
        setup.session._handle_simulation_state(state_message(setup, SimulationStatus.AGENTS_ARE_PREPARING))
        assert statuses(setup) == ["initializing", "agents are preparing"]

    async def test_the_ground_station_ports_the_stack_reports_go_out_with_the_next_status(self, setup):
        setup.session._container.on_ground_control_ports({"1": 49153})
        setup.session._refresh_status()
        with_ports = [payload for payload in setup.sent if payload["type"] == "simulation_status" and payload.get("groundControlPortsByAgentId")]
        assert with_ports and with_ports[0]["groundControlPortsByAgentId"] == {"1": 49153}
        setup.session._handle_simulation_state(state_message(setup, SimulationStatus.RUNNING, clock=1.0, step=1))
        assert setup.sent[-1]["groundControlPortsByAgentId"] == {"1": 49153}, "every later status carries them too"

    async def test_unknown_status_values_are_ignored(self, setup):
        setup.session._handle_simulation_state({"status": "levitating", "clock": 0.0, "scene": None})
        assert statuses(setup) == ["initializing"]


class TestSceneStreaming:
    async def test_preparing_scenes_are_shown_once_per_distinct_scene(self, setup):
        message = state_message(setup, SimulationStatus.AGENTS_ARE_PREPARING)
        setup.session._handle_simulation_state(message)
        setup.session._handle_simulation_state(message)
        assert setup.monitor.steps == [("scenario-1", 0, 1)]

    async def test_a_moved_scene_is_shown_again(self, setup):
        setup.session._handle_simulation_state(state_message(setup, SimulationStatus.AGENTS_ARE_PREPARING, step=0))
        setup.session._handle_simulation_state(state_message(setup, SimulationStatus.AGENTS_ARE_PREPARING, step=5))
        assert len(setup.monitor.steps) == 2

    async def test_running_scenes_are_monitored_at_the_simulator_clock(self, setup):
        for clock, step in ((1.0, 1), (2.0, 2), (3.0, 3)):
            setup.session._handle_simulation_state(state_message(setup, SimulationStatus.RUNNING, clock=clock, step=step))
        assert [timestamp for _, timestamp, _ in setup.monitor.steps] == [1, 2, 3]
        assert len(setup.session.live_trajectory_builder.scene_list) == 3

    async def test_a_repeated_or_older_clock_is_not_monitored_twice(self, setup):
        setup.session._handle_simulation_state(state_message(setup, SimulationStatus.RUNNING, clock=5.0, step=5))
        setup.session._handle_simulation_state(state_message(setup, SimulationStatus.RUNNING, clock=5.0, step=5))
        setup.session._handle_simulation_state(state_message(setup, SimulationStatus.RUNNING, clock=4.0, step=4))
        assert [timestamp for _, timestamp, _ in setup.monitor.steps] == [5]

    async def test_starting_a_run_resets_the_trajectory_of_the_preparation(self, setup):
        setup.session._handle_simulation_state(state_message(setup, SimulationStatus.AGENTS_ARE_PREPARING))
        assert len(setup.session.live_trajectory_builder.scene_list) == 1
        setup.session._handle_simulation_state(state_message(setup, SimulationStatus.RUNNING, clock=1.0, step=1))
        assert len(setup.session.live_trajectory_builder.scene_list) == 1
        assert setup.session._running_confirmed

    async def test_leaving_the_stream_states_clears_the_running_marker(self, setup):
        setup.session._handle_simulation_state(state_message(setup, SimulationStatus.RUNNING, clock=1.0, step=1))
        setup.session._handle_simulation_state(state_message(setup, SimulationStatus.INITIALIZING, with_scene=False))
        assert not setup.session._running_confirmed
        assert setup.session._last_processed_clock is None

    async def test_states_without_a_scene_are_not_streamed(self, setup):
        setup.session._handle_simulation_state(state_message(setup, SimulationStatus.RUNNING, clock=1.0, with_scene=False))
        assert setup.monitor.steps == []

    async def test_initializing_scenes_are_not_streamed(self, setup):
        setup.session._handle_simulation_state(state_message(setup, SimulationStatus.INITIALIZING))
        assert setup.monitor.steps == []

    async def test_a_new_monitor_session_gets_the_scenes_collected_so_far(self, setup):
        for clock, step in ((1.0, 1), (2.0, 2)):
            setup.session._handle_simulation_state(state_message(setup, SimulationStatus.RUNNING, clock=clock, step=step))
        replacement = RecordingMonitor()
        setup.session.set_monitor_session(replacement)
        assert setup.session.monitor_session is replacement
        assert replacement.batches == [("scenario-1", [0], 1), ("scenario-1", [1], 1)]


class TestTeardown:
    async def test_state_after_destroy_is_ignored(self, setup):
        setup.session._destroyed = True
        setup.session._handle_simulation_state(state_message(setup, SimulationStatus.RUNNING, clock=1.0, step=1))
        assert setup.monitor.steps == []

    async def test_destroy_disconnects_the_client_and_destroys_the_stack(self, setup):
        setup.session._destroy()
        assert setup.session._client.disconnected
        assert setup.session._container.destroyed
        assert setup.session.live_trajectory_builder.scene_list == []

    async def test_teardown_without_stack_cancels_the_container_instead_of_destroying_it(self, setup):
        setup.session._handle_simulation_state(state_message(setup, SimulationStatus.RUNNING, clock=1.0, step=1))
        setup.session._teardown_without_stack()
        assert setup.session._client.disconnected
        assert setup.session._container.cancelled
        assert not setup.session._container.destroyed
        assert setup.session._last_processed_clock is None and not setup.session._running_confirmed

    async def test_a_second_teardown_does_nothing(self, setup):
        setup.session._destroyed = True
        setup.session.teardown()
        assert not setup.session._client.disconnected

    async def test_teardown_stops_the_status_worker(self, setup):
        setup.session.teardown()
        await settle()
        assert setup.session.status_update_worker.done()  # the loop swallows the cancellation and returns
        assert setup.session._destroyed


class RunListener:
    """Records what the session tells the listener of its runs, in order."""

    def __init__(self, failing: bool = False):
        self.calls: List[tuple] = []
        self.failing = failing

    def _call(self, *call):
        self.calls.append(call)
        if self.failing:
            raise RuntimeError("listener broke")

    def run_started(self):
        self._call("started")

    def state_simulated(self, clock, scene):
        self._call("state", clock, len(scene.actors))

    def run_ended(self):
        self._call("ended")

    def session_ended(self, reason):
        self._call("session_ended", reason)


class TestRunListener:
    @pytest.fixture
    def listener(self, setup):
        listener = RunListener()
        setup.session.set_run_listener(listener)
        return listener

    def run(self, setup, clocks):
        for clock in clocks:
            setup.session._handle_simulation_state(state_message(setup, SimulationStatus.RUNNING, clock=clock, step=int(clock)))

    async def test_the_start_command_starts_a_run(self, setup, listener):
        setup.session.start_simulation_runtime()
        assert listener.calls == [("started",)]

    async def test_a_failed_start_command_starts_no_run(self, setup, listener):
        setup.session._client.start_error = RuntimeError("broker gone")
        setup.session.start_simulation_runtime()
        assert listener.calls == []

    async def test_running_states_reach_the_listener_once_each_until_the_worker_leaves_running(self, setup, listener):
        setup.session._handle_simulation_state(state_message(setup, SimulationStatus.READY_TO_START))
        self.run(setup, (0.0, 1.0, 1.0, 2.0))
        setup.session._handle_simulation_state(state_message(setup, SimulationStatus.READY_TO_START))
        setup.session._handle_simulation_state(state_message(setup, SimulationStatus.READY_TO_START))
        assert listener.calls == [("started",), ("state", 0.0, 2), ("state", 1.0, 2), ("state", 2.0, 2), ("ended",)]

    async def test_a_worker_that_loses_its_agents_ends_the_run(self, setup, listener):
        self.run(setup, (0.0,))
        setup.session._handle_simulation_state(state_message(setup, SimulationStatus.INITIALIZING, with_scene=False))
        assert listener.calls[-1] == ("ended",)

    async def test_a_second_run_of_the_session_starts_again(self, setup, listener):
        self.run(setup, (0.0, 1.0))
        setup.session._handle_simulation_state(state_message(setup, SimulationStatus.READY_TO_START))
        self.run(setup, (0.0,))
        assert [call[0] for call in listener.calls] == ["started", "state", "state", "ended", "started", "state"]

    async def test_teardown_ends_the_session_as_stopped_once(self, setup, listener):
        setup.session.teardown()
        setup.session.teardown()
        assert listener.calls == [("session_ended", "stopped")]

    async def test_destroy_ends_the_session_as_disconnected(self, setup, listener):
        self.run(setup, (0.0,))
        setup.session.destroy()
        assert listener.calls[-1] == ("session_ended", "disconnected")
        self.run(setup, (1.0,))
        assert listener.calls[-1] == ("session_ended", "disconnected")  # states after it are not passed on

    async def test_a_failing_listener_changes_nothing_for_the_session(self, setup):
        setup.session.set_run_listener(RunListener(failing=True))
        self.run(setup, (0.0, 1.0))
        assert [timestamp for _, timestamp, _ in setup.monitor.steps] == [0, 1]
        assert len(setup.session.live_trajectory_builder.scene_list) == 2

    async def test_without_a_listener_the_session_behaves_as_before(self, setup):
        self.run(setup, (0.0, 1.0))
        setup.session._handle_simulation_state(state_message(setup, SimulationStatus.READY_TO_START))
        setup.session.start_simulation_runtime()
        assert [timestamp for _, timestamp, _ in setup.monitor.steps][:2] == [0, 1]
