import logging
import threading
from typing import Any, Callable, Dict, Optional, Protocol

from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.cluster.node.instance_scope import InstanceScope
from scenegems_tool.cluster.node.launchers.per_job.simulation_session_stack import SimulationSessionStack
from scenegems_tool.gateway.protocol import ServerMessage, SimulationStatus, make_error_message
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.messaging.mqtt_scenario_execution_client import MqttScenarioExecutionClient
from scenegems_tool.messaging.mqtt_scenario_execution_service import SCENARIO_EXECUTION_SERVICE_NAME
from scenegems_tool.subsystems.monitoring.monitor_session import MonitorSession, iter_scene_batches
from scenegems_tool.subsystems.scenario_execution.simulation_session import SimulationSession
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig
from scenegems_tool.workbench.scenario_session import ScenarioSession
from utils.global_constants import ONE_SECOND

_logger = logging.getLogger(__name__)

_SCENE_STREAM_STATUSES = (
    SimulationStatus.AGENTS_ARE_PREPARING,
    SimulationStatus.READY_TO_START,
    SimulationStatus.STARTING,
    SimulationStatus.RUNNING,
)


class LiveRunListener(Protocol):
    """Follows the runs of a live session (the gateway records them, gateway/live_run_recorder.py).

    Called from the event loop and from the MQTT client's thread, so an implementation is
    thread-safe and never blocks.
    """

    def run_started(self) -> None:
        """The start command went out, or the worker reports running first."""

    def state_simulated(self, clock: float, scene: ConcreteScene) -> None:
        """A simulated state of the running run, in clock order."""

    def run_ended(self) -> None:
        """The worker left running: the run completed or was stopped there."""

    def session_ended(self, reason: str) -> None:
        """The session was torn down (stopped, replaced) or destroyed (disconnected); no run follows."""


class LiveSimulationSession(SimulationSession):

    def __init__(
        self,
        simulation_config: SimulationInstanceConfig,
        trajectories: Trajectories,
        scenario_session: ScenarioSession,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        monitor_session: MonitorSession,
        send_payload: Callable[[ServerMessage], None],
        time_step: int = ONE_SECOND,
        session_scope: Optional[InstanceScope] = None,
    ):
        super().__init__(send_payload, SimulationStatus.INITIALIZING)
        self._destroyed = False
        self._run_listener: Optional[LiveRunListener] = None
        self.trajectories = trajectories
        self.generate_vessel_models(trajectories.initial_scene, simulation_config)
        self.scenario_session = scenario_session
        self.monitor_session = monitor_session
        self.time_step = time_step
        self.live_trajectory_builder = TrajectoryBuilder(time_step=time_step)
        self._simulation_state_lock = threading.Lock()
        self._running_confirmed = False
        self._container = SimulationSessionStack(
            mqtt_connection,
            reference_geofence,
            simulation_config,
            trajectories,
            time_step,
            on_ground_control_ports=self._set_ground_control_ports,
            scope=session_scope,
        )
        self._client = MqttScenarioExecutionClient(
            mqtt_connection=mqtt_connection,
            topic=SimulationSessionStack.service_topic,
            reference_geofence=reference_geofence,
            parent_service_name=SCENARIO_EXECUTION_SERVICE_NAME,
            on_simulation_state=self._handle_simulation_state,
        )
        self._client.connect()
        self._last_processed_clock: Optional[float] = None
        self._last_prep_scene_hash: Optional[int] = None

    def set_run_listener(self, listener: Optional[LiveRunListener]) -> None:
        """Who follows the runs of this session; nothing changes without one."""
        self._run_listener = listener

    def _notify_run_listener(self, notify: Callable[[LiveRunListener], None]) -> None:
        listener = self._run_listener
        if listener is None:
            return
        try:
            notify(listener)
        except Exception:
            _logger.exception("The live run listener failed")

    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        self._notify_run_listener(lambda listener: listener.session_ended("disconnected"))
        super().destroy()

    def teardown(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        self._notify_run_listener(lambda listener: listener.session_ended("stopped"))
        self.status_update_worker.cancel()
        if self._chunk_send_task is not None and not self._chunk_send_task.done():
            self._chunk_send_task.cancel()
        threading.Thread(
            target=self._teardown_without_stack,
            name="live_simulation_session_teardown",
            daemon=True,
        ).start()

    def _teardown_without_stack(self) -> None:
        try:
            self._client.disconnect()
        except Exception:
            _logger.exception("Failed to disconnect scenario execution MQTT client")
        self._container.cancel()
        self.live_trajectory_builder = TrajectoryBuilder(time_step=self.time_step)
        self._last_processed_clock = None
        self._running_confirmed = False
        self._last_prep_scene_hash = None

    def _destroy(self) -> None:
        try:
            self._client.disconnect()
        except Exception:
            _logger.exception("Failed to disconnect scenario execution MQTT client")
        self._container.destroy()
        self.live_trajectory_builder = TrajectoryBuilder(time_step=self.time_step)
        self._last_processed_clock = None
        self._running_confirmed = False
        self._last_prep_scene_hash = None

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected and self._client.is_heartbeat_valid

    def _resolve_simulation_status(self, worker_status: Optional[SimulationStatus] = None) -> SimulationStatus:
        if not self._client.is_service_ready:
            return SimulationStatus.INITIALIZING
        if worker_status is not None:
            return worker_status
        return self._client.latest_status

    def _status_update(self) -> SimulationStatus:
        return self._resolve_simulation_status()

    def _set_ground_control_ports(self, ports: Dict[str, int]) -> None:
        """From the stack's spawn thread; the status loop sends them with the next status."""
        self.ground_control_ports = dict(ports)

    def _emit_status_if_changed(self, worker_status: SimulationStatus) -> None:
        resolved = self._resolve_simulation_status(worker_status)
        if resolved == self.status:
            return
        self.status = resolved
        self._send_status()

    def _send_scenario_chunks(self) -> None:
        time_step = self.live_trajectory_builder.time_step
        for scenes, timestamps in iter_scene_batches(self.live_trajectory_builder.scene_list, time_step):
            self.monitor_session.step_simulation_monitor_batch(
                scenario_id=self.scenario_session.scenario_id,
                scenes=scenes,
                timestamps=timestamps,
                time_step=time_step,
            )

    def set_monitor_session(self, monitor_session: MonitorSession) -> None:
        self.monitor_session = monitor_session
        time_step = self.live_trajectory_builder.time_step
        for scenes, timestamps in iter_scene_batches(self.live_trajectory_builder.scene_list, time_step):
            monitor_session.step_simulation_monitor_batch(
                scenario_id=self.scenario_session.scenario_id,
                scenes=scenes,
                timestamps=timestamps,
                time_step=time_step,
            )

    def start_simulation_runtime(self) -> None:
        try:
            self._client.publish_start_simulation_command()
        except Exception as exc:
            self.send_payload(make_error_message(message=f"Failed to start simulation: {str(exc)}"))
            return
        self._notify_run_listener(lambda listener: listener.run_started())

    def _step_prep_scene(self, scene: ConcreteScene) -> None:
        scene_hash = hash(scene)
        if scene_hash == self._last_prep_scene_hash:
            return
        self._last_prep_scene_hash = scene_hash
        self.live_trajectory_builder = TrajectoryBuilder(time_step=self.time_step)
        self.live_trajectory_builder.add_scene(scene)
        self.monitor_session.step_simulation_monitor(
            self.scenario_session.scenario_id,
            scene,
            0,
            self.time_step,
        )

    def _reset_running_trajectory(self) -> None:
        self._running_confirmed = True
        self._last_processed_clock = None
        self._last_prep_scene_hash = None
        self.live_trajectory_builder = TrajectoryBuilder(time_step=self.time_step)

    def _handle_simulation_state(self, state: Dict[str, Any]) -> None:
        with self._simulation_state_lock:
            if self._destroyed:
                return

            status_value = state.get("status", SimulationStatus.INITIALIZING.value)
            try:
                worker_status = SimulationStatus(status_value)
            except ValueError:
                return

            self._emit_status_if_changed(worker_status)
            if worker_status != SimulationStatus.RUNNING and self._running_confirmed:
                self._notify_run_listener(lambda listener: listener.run_ended())

            if worker_status not in _SCENE_STREAM_STATUSES:
                self._running_confirmed = False
                self._last_processed_clock = None
                return

            scene_dict = state.get("scene")
            if not scene_dict:
                return

            scene = ConcreteScene.from_dict(scene_dict)

            if worker_status == SimulationStatus.RUNNING:
                if not self._running_confirmed:
                    self._reset_running_trajectory()
                    self._notify_run_listener(lambda listener: listener.run_started())
                clock = float(state.get("clock", 0.0))
                if self._last_processed_clock is not None and clock <= self._last_processed_clock:
                    return
                self._last_processed_clock = clock
                self.live_trajectory_builder.add_scene(scene)
                self._notify_run_listener(lambda listener: listener.state_simulated(clock, scene))
                self.monitor_session.step_simulation_monitor(
                    self.scenario_session.scenario_id,
                    scene,
                    int(clock),
                    self.time_step,
                )
                return

            self._running_confirmed = False
            self._last_processed_clock = None
            self._step_prep_scene(scene)
