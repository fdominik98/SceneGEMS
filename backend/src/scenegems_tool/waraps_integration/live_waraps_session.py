import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict

from concrete_level.models.concrete_scene import ConcreteScene
from functional_level.models.model_parser import ModelParser
from scenegems_tool.backend_service.protocol import ServerMessage, make_error_message
from scenegems_tool.backend_service.scenario_session import ScenarioSession
from scenegems_tool.monitoring.live_monitor_session import LiveMonitorSession
from scenegems_tool.scenario_generation.scenario_generation_session import ScenarioGenerationSession
from scenegems_tool.simulators.live_simulation_session import LiveSimulationSession
from scenegems_tool.simulators.simulation_config import SimulationConfig
from scenegems_tool.trajectory_generation.trajectory_generation_session import TrajectoryGenerationSession
from scenegems_tool.trajectory_generation.trajectory_generation_types import TrajectoryGenerationParams
from scenegems_tool.waraps_integration.mqtt_client import MQttConnectionInfo
from scenegems_tool.waraps_integration.mqtt_scenegems_client import MqttSceneGEMSClient
from scenegems_tool.waraps_integration.mqtt_scenegems_service import MqttSceneGEMSService
from scenegems_tool.waraps_integration.sim_utils import Geofence
from scenegems_tool.waraps_integration.waraps_session import WARAPSSession

_CONNECT_TIMEOUT_SEC = 5.0
_CONNECT_POLL_INTERVAL_SEC = 0.1


class LiveWARAPSSession(WARAPSSession):
    def __init__(self, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence, send_payload: Callable[[ServerMessage], None]):
        super().__init__(send_payload)

        self.mqtt_connection = mqtt_connection
        self.reference_geofence = reference_geofence

        self.mqtt_service = MqttSceneGEMSService(self.mqtt_connection, self.reference_geofence)
        self.mqtt_client = MqttSceneGEMSClient(self.mqtt_connection, self.mqtt_service.topic, self.reference_geofence)

        # Assigned by `start()`. They stay None when the handshake never completes, so
        # `_cancel()` can tear down a half-built session without an AttributeError.
        self.heartbeat_and_info_task: asyncio.Task | None = None
        self.scenario_generation_session: ScenarioGenerationSession | None = None
        self.trajectory_generation_session: TrajectoryGenerationSession | None = None
        # Generated scenes arrive on the MQTT callback thread; the monitor hand-off runs
        # here instead, since the live monitor can block waiting for its heartbeat.
        self._generated_scene_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="generated_scene_monitor")

        self.mqtt_client.connect()
        self.mqtt_service.connect()

    async def start(self) -> None:
        """Wait for the broker handshake, then bring up the dependent sessions.

        Separate from `__init__` so the wait can yield to the event loop: a blocking
        wait here would freeze every other socket session for its whole duration.
        """
        start_time = time.monotonic()
        while not self.is_connected:
            await asyncio.sleep(_CONNECT_POLL_INTERVAL_SEC)
            elapsed = time.monotonic() - start_time
            if elapsed > _CONNECT_TIMEOUT_SEC:
                raise TimeoutError(f"No CONNACK from broker {self.mqtt_service.endpoint} after {elapsed:.1f}s: {self._connect_failure_reason()}")
        self.heartbeat_and_info_task = asyncio.create_task(self._heartbeat_and_info_loop())

        self.scenario_generation_session = ScenarioGenerationSession(self.mqtt_connection, self.reference_geofence, self.send_payload, self._on_generated_scene)
        self.trajectory_generation_session = TrajectoryGenerationSession(self.mqtt_connection, self.reference_geofence, self.send_payload)

    def _on_generated_scene(self, request_id: str, scene: ConcreteScene, evaluation_data: Dict[str, Any], valid: bool) -> None:
        try:
            self._generated_scene_executor.submit(self._monitor_generated_scene, request_id, scene, evaluation_data, valid)
        except RuntimeError:
            # The executor is shut down: this session is being cancelled.
            return

    def _monitor_generated_scene(self, request_id: str, scene: ConcreteScene, evaluation_data: Dict[str, Any], valid: bool) -> None:
        # Read at run time: the monitor session can be replaced while scenes are queued.
        try:
            self.monitor_session.monitor_generated_scene(request_id, scene, evaluation_data, valid)
        except Exception as exc:
            print(f"Failed to monitor generated scene {request_id}: {exc}")

    def _connect_failure_reason(self) -> str:
        """The most specific explanation the MQTT clients managed to capture."""
        refusal = self.mqtt_service.last_broker_refusal or self.mqtt_client.last_broker_refusal
        if refusal:
            return refusal
        if self.mqtt_connection.tls_connection:
            return "the TCP connection opened but the broker never completed the MQTT handshake. Check the credentials and whether that port speaks MQTT over TLS"
        return "the TCP connection opened but the broker never completed the MQTT handshake. Check that the port speaks plain MQTT and does not require TLS"

    async def _heartbeat_and_info_loop(self) -> None:
        tick_interval_sec = 1.0 / self.mqtt_service.info_update_rate
        try:
            while self.mqtt_service.is_connected:
                await asyncio.sleep(tick_interval_sec)
                self.mqtt_service.publish_heartbeat_and_sensor_info()
        except asyncio.CancelledError as e:
            print(f"MQTTSession heartbeat and info loop cancelled: {e}")
            return
        finally:
            print("MQTTSession heartbeat and info loop finally")

    def set_monitor_session(self, name: str, topic: str, scope: str, colregs_constraints_content: str) -> None:
        self.monitor_session.destroy()
        self.monitor_session = LiveMonitorSession(
            name=name,
            topic=topic,
            scope=scope,
            mqtt_connection=self.mqtt_connection,
            parent_client=self.mqtt_service,
            colregs_constraints_content=colregs_constraints_content,
            send_payload=self.send_payload,
        )
        self.simulation_session.set_monitor_session(self.monitor_session)

    def set_simulation_session(self, scenario_session: ScenarioSession, simulation_config: SimulationConfig) -> None:
        previous = self.simulation_session
        self.simulation_session = LiveSimulationSession(
            scenario_session=scenario_session,
            mqtt_connection=self.mqtt_connection,
            simulation_config=simulation_config,
            trajectories=scenario_session.trajectories,
            monitor_session=self.monitor_session,
            reference_geofence=self.reference_geofence,
            send_payload=self.send_payload,
        )
        previous.teardown()

    def _cancel(self) -> None:
        self._generated_scene_executor.shutdown(wait=False, cancel_futures=True)
        if self.heartbeat_and_info_task is not None:
            self.heartbeat_and_info_task.cancel()
        if self.scenario_generation_session is not None:
            self.scenario_generation_session.destroy()
        if self.trajectory_generation_session is not None:
            self.trajectory_generation_session.destroy()
        self.mqtt_service.disconnect()
        self.mqtt_client.disconnect()

    @property
    def is_connected(self) -> bool:
        return self.mqtt_service.is_connected

    def generate_scene(
        self, request_id: str, functional_scenario_content: str, colregs_constraints_content: str, vessel_types_content: str, obstacle_types_content: str, timeout: int, enforce_low_tcpa: bool = False
    ) -> None:
        try:
            ModelParser.parse_problem(functional_scenario_content)
        except Exception as e:
            print(f"Error parsing functional scenario content: {e}")
            self.send_payload(make_error_message(f"Error parsing functional scenario content: {e}"))
            return
        self.scenario_generation_session.publish_generate_scene_command(
            request_id,
            functional_scenario_content,
            colregs_constraints_content,
            vessel_types_content,
            obstacle_types_content,
            timeout,
            enforce_low_tcpa,
        )

    async def stop_scene_generation(self) -> None:
        await self.scenario_generation_session.destroy_async()
        self.scenario_generation_session = ScenarioGenerationSession(self.mqtt_connection, self.reference_geofence, self.send_payload, self._on_generated_scene)

    def generate_trajectories(self, request_id: str, scenario_content: str, colregs_constraints_content: str, params: dict) -> None:
        self.trajectory_generation_session.publish_generate_trajectories_command(
            request_id,
            scenario_content,
            colregs_constraints_content,
            TrajectoryGenerationParams.from_wire(params or {}),
        )

    async def stop_trajectory_generation(self) -> None:
        self.trajectory_generation_session.publish_cancel_command()
