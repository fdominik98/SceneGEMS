import asyncio
from datetime import datetime, timezone
from typing import Dict, Union

from scenegems_tool.backend_service.empty_scenario_session import EmptyScenarioSession
from scenegems_tool.backend_service.live_scenario_session import LiveScenarioSession
from scenegems_tool.backend_service.protocol import ClientMessage, InitializeSimulationMessage, ServerMessage, SimulationConnectionInfo, make_error_message, make_monitor_status_message, make_waraps_status_message
from scenegems_tool.backend_service.scenario_session import ScenarioSession
from scenegems_tool.simulators.simulation_config import SimulationConfig
from scenegems_tool.waraps_integration.empty_waraps_session import EmptyWARAPSSession
from scenegems_tool.waraps_integration.mqtt_client import MQttConnectionInfo, resolve_mqtt_broker_endpoints
from scenegems_tool.waraps_integration.live_waraps_session import LiveWARAPSSession
from scenegems_tool.waraps_integration.sim_utils import Geofence
from fastapi import WebSocket

from scenegems_tool.waraps_integration.waraps_session import WARAPSSession

class SocketSession:

    def __init__(self, websocket: WebSocket):
        self.websocket: WebSocket = websocket
        
        self.outbound_queue: asyncio.Queue[ServerMessage] = asyncio.Queue()
        self.outbound_task: asyncio.Task[None] = asyncio.create_task(self._outbound_loop())
        self.waraps_connection_task: asyncio.Task[None] = asyncio.create_task(self._waraps_connection_loop())
        
        self.created_at_utc = datetime.now(timezone.utc).isoformat()
        self.waraps_session: WARAPSSession = EmptyWARAPSSession(send_payload=self.send_payload)
        self.scenario_session: ScenarioSession = EmptyScenarioSession(monitor_session=self.waraps_session.monitor_session, send_payload=self.send_payload)


    @property
    def connection_id(self) -> str:
        return str(id(self.websocket))
    
    async def _waraps_connection_loop(self) -> None:
        while True:
            await asyncio.sleep(1)
            if self.waraps_session.is_connected:
                status = "connected"
            else:
                status = "disconnected"
            self.send_payload(make_waraps_status_message(status=status))
    
    def log_payload(self, direction: str, payload: Union[ServerMessage, ClientMessage]) -> None:
        if payload["type"] == "preview_trajectory_chunk" or payload["type"] == "simulation_trajectory_chunk":
            return
        if "status" in payload["type"]:
            return
        print(f"[ws][{direction}] session_id={self.connection_id} type={payload.get('type')}")

    async def _send_payload(self, payload: ServerMessage) -> None:
        self.log_payload("outgoing", payload=payload)
        await self.websocket.send_json(payload)
        
    async def _outbound_loop(self):
        while True:
            payload = await self.outbound_queue.get()
            await self._send_payload(payload)
            
    def send_payload(self, payload: ServerMessage) -> None:
        self.outbound_queue.put_nowait(payload)
            
    def send_runtime_error(self, message: str) -> None:
        self.send_payload(make_error_message(message=message))
        
    def connect_to_waraps(self, user: str, password: str, agent_broker: str, client_broker: str, port: int, tls_connection: bool, allow_certificates: bool, reference_geofence: Geofence):
        agent_broker, client_broker, port = resolve_mqtt_broker_endpoints(
            agent_broker,
            client_broker,
            port,
            tls_connection=tls_connection,
        )
        self.waraps_session.cancel()
        self.waraps_session = LiveWARAPSSession(
            mqtt_connection=MQttConnectionInfo(
                user=user, password=password, agent_broker=agent_broker, client_broker=client_broker, port=port, tls_connection=tls_connection, allow_certificates=allow_certificates
            ),
            reference_geofence=reference_geofence,
            send_payload=self.send_payload,
        )

    def disconnect_from_waraps(self) -> None:
        self.send_payload(make_waraps_status_message(status="disconnected"))
        self.waraps_session.cancel()
        self.waraps_session = EmptyWARAPSSession(send_payload=self.send_payload)
        self.scenario_session.set_monitor_session(self.waraps_session.monitor_session)

    def set_monitor_session(self, name: str, topic: str, scope: str, colregs_constraints_content: str) -> None:
        self.waraps_session.set_monitor_session(name=name, topic=topic, scope=scope, colregs_constraints_content=colregs_constraints_content)
        self.scenario_session.set_monitor_session(self.waraps_session.monitor_session)
        
    def shut_down_monitor(self) -> None:
        self.send_payload(make_monitor_status_message(status="disconnected"))
        self.waraps_session.reset_monitor_session()
        self.scenario_session.set_monitor_session(self.waraps_session.monitor_session)

    def set_scenario_session(self, scenario_id: str, file_name: str, file_path: str, file_content: str) -> None:
        self.waraps_session.reset_simulation_session()
        self.scenario_session = LiveScenarioSession(scenario_id=scenario_id,
                                                    file_name=file_name,
                                                    file_path=file_path,
                                                    file_content=file_content,
                                                    monitor_session=self.waraps_session.monitor_session,
                                                    send_payload=self.send_payload)
        
    def set_simulation_session(self, simulation_config: SimulationConfig) -> None:
        if self.scenario_session.is_initialized:
            self.waraps_session.set_simulation_session(scenario_session=self.scenario_session, simulation_config=simulation_config)
            return
        self.send_runtime_error("No scenario loaded")
        
    def generate_simulation_models(self, simulation_config: SimulationConfig) -> None:
        if not self.scenario_session.is_initialized:
            self.send_runtime_error("No scenario loaded")
            return
        scene = self.scenario_session.trajectories.initial_scene
        if scene is None:
            self.send_runtime_error("No initial scene found")
            return
        self.waraps_session.simulation_session.generate_vessel_models(scene, simulation_config)

    def cancel(self) -> None:
        self.waraps_session.cancel()
        self.outbound_task.cancel()
        self.waraps_connection_task.cancel()

