import asyncio
import time
from typing import Callable, Optional

from scenegems_tool.cluster.worker_node.instance_scope import InstanceScope
from scenegems_tool.cluster.worker_node.launchers.per_job.simulation_session_stack import new_live_session_scope
from scenegems_tool.gateway.protocol import ServerMessage
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.messaging.mqtt_scenegems_client import MqttSceneGEMSClient
from scenegems_tool.messaging.mqtt_scenegems_service import MqttSceneGEMSService
from scenegems_tool.subsystems.monitoring.live_monitor_session import LiveMonitorSession
from scenegems_tool.subsystems.scenario_execution.live_simulation_session import LiveSimulationSession
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig
from scenegems_tool.workbench.scenario_session import ScenarioSession
from scenegems_tool.workbench.subsystem_integration_session import SubsystemIntegrationSession

_CONNECT_TIMEOUT_SEC = 5.0
_CONNECT_POLL_INTERVAL_SEC = 0.1


class LiveSubsystemIntegrationSession(SubsystemIntegrationSession):
    def __init__(
        self,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        send_payload: Callable[[ServerMessage], None],
        session_scope: Optional[InstanceScope] = None,
    ):
        """session_scope names the session's simulation stack; mqtt_connection carries its topic prefix when it has one."""
        super().__init__(send_payload)

        self.session_scope = session_scope or new_live_session_scope()
        self.mqtt_connection = mqtt_connection
        self.reference_geofence = reference_geofence

        self.mqtt_service = MqttSceneGEMSService(self.mqtt_connection, self.reference_geofence)
        self.mqtt_client = MqttSceneGEMSClient(self.mqtt_connection, self.mqtt_service.topic, self.reference_geofence)

        # Assigned by `start()`. It stays None when the handshake never completes, so
        # `_cancel()` can tear down a half-built session without an AttributeError.
        self.heartbeat_and_info_task: asyncio.Task | None = None

        self.mqtt_client.connect()
        self.mqtt_service.connect()

    async def start(self) -> None:
        """Wait for the broker handshake, then start the heartbeat.

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

    def set_simulation_session(self, scenario_session: ScenarioSession, simulation_config: SimulationInstanceConfig) -> None:
        previous = self.simulation_session
        self.simulation_session = LiveSimulationSession(
            scenario_session=scenario_session,
            mqtt_connection=self.mqtt_connection,
            simulation_config=simulation_config,
            trajectories=scenario_session.trajectories,
            monitor_session=self.monitor_session,
            reference_geofence=self.reference_geofence,
            send_payload=self.send_payload,
            session_scope=self.session_scope,
        )
        previous.teardown()

    def _cancel(self) -> None:
        if self.heartbeat_and_info_task is not None:
            self.heartbeat_and_info_task.cancel()
        self.mqtt_service.disconnect()
        self.mqtt_client.disconnect()

    @property
    def is_connected(self) -> bool:
        return self.mqtt_service.is_connected
