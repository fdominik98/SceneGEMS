import asyncio
import os
from datetime import datetime, timezone
from typing import Mapping, Optional, Tuple, Union

from fastapi import WebSocket

from scenegems_tool.cluster.worker_node.launchers.per_job.simulation_session_stack import new_live_session_scope
from scenegems_tool.gateway.live_run_recorder import LiveRunRecorder, LiveRunSetup, LiveSessionRecording
from scenegems_tool.gateway.protocol import ClientMessage, ServerMessage, make_error_message, make_monitor_status_message, make_mqtt_broker_status_message
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo, resolve_mqtt_broker_endpoints
from scenegems_tool.subsystems.simulation.lockstep_simulation_driver import uses_lockstep_driver
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig
from scenegems_tool.vessel_stack.control_layers.ardupilot.arduagent_control_mode import ARDUAGENT_ADAPTER_IDS
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from scenegems_tool.workbench.empty_scenario_session import EmptyScenarioSession
from scenegems_tool.workbench.empty_subsystem_integration_session import EmptySubsystemIntegrationSession
from scenegems_tool.workbench.live_scenario_session import LiveScenarioSession
from scenegems_tool.workbench.live_subsystem_integration_session import LiveSubsystemIntegrationSession
from scenegems_tool.workbench.scenario_session import ScenarioSession
from scenegems_tool.workbench.subsystem_integration_session import SubsystemIntegrationSession

NO_TRAJECTORIES_MESSAGE = "Cannot simulate without trajectories: generate trajectories first (monitor-guided planner or straight). The simulation never invents trajectories."
NO_CONTROL_NODE_BROKER_MESSAGE = "This server has no control node broker (SCENEGEMS_BROKER_HOST is not set): choose another MQTT broker."
DEFAULT_BROKER_PORT = 1883


def control_node_broker(environ: Optional[Mapping[str, str]] = None) -> Optional[Tuple[str, int]]:
    """The control node's own cluster broker as this server dials it, from the control node's settings
    (SCENEGEMS_BROKER_HOST, SCENEGEMS_BROKER_PORT); None when the server runs without one."""
    environ = os.environ if environ is None else environ
    host = environ.get("SCENEGEMS_BROKER_HOST", "").strip()
    if not host:
        return None
    return host, int(environ.get("SCENEGEMS_BROKER_PORT", "").strip() or DEFAULT_BROKER_PORT)


def control_node_broker_label(environ: Optional[Mapping[str, str]] = None) -> Optional[str]:
    broker = control_node_broker(environ)
    return None if broker is None else f"{broker[0]}:{broker[1]}"


class SocketSession:

    def __init__(self, websocket: WebSocket, run_recorder: Optional[LiveRunRecorder] = None):
        self.websocket: WebSocket = websocket
        # Records the live session's runs as workbench entries on the control node; None when the gateway runs on its own.
        self.run_recorder: Optional[LiveRunRecorder] = run_recorder
        self.loop = asyncio.get_running_loop()

        self.outbound_queue: asyncio.Queue[ServerMessage] = asyncio.Queue()
        self.outbound_task: asyncio.Task[None] = asyncio.create_task(self._outbound_loop())
        self.mqtt_broker_status_task: asyncio.Task[None] = asyncio.create_task(self._mqtt_broker_status_loop())

        self.created_at_utc = datetime.now(timezone.utc).isoformat()
        self.subsystem_integration_session: SubsystemIntegrationSession = EmptySubsystemIntegrationSession(send_payload=self.send_payload)
        self.scenario_session: ScenarioSession = EmptyScenarioSession(monitor_session=self.subsystem_integration_session.monitor_session, send_payload=self.send_payload)

    @property
    def connection_id(self) -> str:
        return str(id(self.websocket))

    def mqtt_broker_status_message(self, status: Optional[str] = None) -> ServerMessage:
        if status is None:
            status = "connected" if self.subsystem_integration_session.is_connected else "disconnected"
        return make_mqtt_broker_status_message(status=status, control_node_broker=control_node_broker_label())

    async def _mqtt_broker_status_loop(self) -> None:
        while True:
            await asyncio.sleep(1)
            self.send_payload(self.mqtt_broker_status_message())

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

    async def connect_to_mqtt_broker(
        self,
        user: str,
        password: str,
        agent_broker: str,
        client_broker: str,
        port: int,
        tls_connection: bool,
        allow_certificates: bool,
        reference_geofence: Geofence,
        use_control_node_broker: bool = False,
    ):
        """Connect the interactive simulation to a broker: the control node's own (plain, anonymous, on the
        compose network the session's containers join) or any other, resolved for this container.

        Every connection is a live session with its own scope, which names its simulation stack. On
        the control node's broker its topics are scoped too, so several live sessions share that broker; on
        any other broker (WARA-PS, a lab broker) they stay the unscoped WARA-PS topics that real
        vessels, the WARA-PS map and external monitors use. Real vessels keep the unscoped topics
        on the control node's broker as well (vessel_stack/agent_topic_scope.py)."""
        session_scope = new_live_session_scope()
        topic_prefix = ""
        if use_control_node_broker:
            broker = control_node_broker()
            if broker is None:
                raise ValueError(NO_CONTROL_NODE_BROKER_MESSAGE)
            agent_broker = client_broker = broker[0]
            port = broker[1]
            user, password, tls_connection, allow_certificates = "", "", False, False
            topic_prefix = session_scope.topic_prefix
        else:
            requested_broker = client_broker.strip()
            agent_broker, client_broker, port = resolve_mqtt_broker_endpoints(
                agent_broker,
                client_broker,
                port,
                tls_connection=tls_connection,
            )
            if requested_broker and requested_broker.lower() != client_broker.lower():
                print(f"MQTT broker {requested_broker} resolved to {client_broker} for this container")
        self.subsystem_integration_session.cancel()
        session = LiveSubsystemIntegrationSession(
            mqtt_connection=MQttConnectionInfo(
                user=user,
                password=password,
                agent_broker=agent_broker,
                client_broker=client_broker,
                port=port,
                tls_connection=tls_connection,
                allow_certificates=allow_certificates,
                topic_prefix=topic_prefix,
            ),
            reference_geofence=reference_geofence,
            send_payload=self.send_payload,
            session_scope=session_scope,
        )
        try:
            await session.start()
        except Exception:
            # Leave the slot empty so the next attempt starts clean instead of
            # inheriting half-connected MQTT clients from the failed one.
            session.cancel()
            self.subsystem_integration_session = EmptySubsystemIntegrationSession(send_payload=self.send_payload)
            self.scenario_session.set_monitor_session(self.subsystem_integration_session.monitor_session)
            raise
        self.subsystem_integration_session = session

    def disconnect_from_mqtt_broker(self) -> None:
        self.send_payload(self.mqtt_broker_status_message(status="disconnected"))
        self.subsystem_integration_session.cancel()
        self.subsystem_integration_session = EmptySubsystemIntegrationSession(send_payload=self.send_payload)
        self.scenario_session.set_monitor_session(self.subsystem_integration_session.monitor_session)

    def set_monitor_session(self, name: str, topic: str, scope: str, colregs_constraints_content: str) -> None:
        self.subsystem_integration_session.set_monitor_session(name=name, topic=topic, scope=scope, colregs_constraints_content=colregs_constraints_content)
        self.scenario_session.set_monitor_session(self.subsystem_integration_session.monitor_session)

    def shut_down_monitor(self) -> None:
        self.send_payload(make_monitor_status_message(status="disconnected"))
        self.subsystem_integration_session.reset_monitor_session()
        self.scenario_session.set_monitor_session(self.subsystem_integration_session.monitor_session)

    def set_scenario_session(self, scenario_id: str, file_name: str, file_path: str, file_content: str) -> None:
        self.subsystem_integration_session.reset_simulation_session()
        self.scenario_session = LiveScenarioSession(
            scenario_id=scenario_id,
            file_name=file_name,
            file_path=file_path,
            file_content=file_content,
            monitor_session=self.subsystem_integration_session.monitor_session,
            send_payload=self.send_payload,
        )

    def _accept_simulation_config(self, simulation_config: SimulationInstanceConfig) -> bool:
        """Validate the vessel stacks, environment and speedup through the adapter registry."""
        resolution = default_resolver().resolve_instance(simulation_config)
        for warning in resolution.warnings:
            print(f"Simulation configuration warning: {warning}")
        if not resolution.accepted:
            self.send_runtime_error(f"Simulation configuration rejected: {resolution.reason}")
            return False
        if not uses_lockstep_driver(simulation_config):
            # A real vessel is reached only through its ArduAgent over MQTT, so ArduAgent drives every vessel of the instance.
            without_arduagent = [
                f"vessel {agent_id} ({chain.stack})" for agent_id, chain in resolution.chains.items() if chain.asv_adapter is None or chain.asv_adapter.id not in ARDUAGENT_ADAPTER_IDS
            ]
            if without_arduagent:
                self.send_runtime_error(f"Simulation configuration rejected: with a real vessel, ArduAgent drives every simulated vessel, and it cannot drive {', '.join(without_arduagent)}")
                return False
        return True

    def set_simulation_session(self, simulation_config: SimulationInstanceConfig) -> None:
        if not self.scenario_session.is_initialized:
            self.send_runtime_error("No scenario loaded")
            return
        if not self.scenario_session.has_trajectories:
            self.send_runtime_error(NO_TRAJECTORIES_MESSAGE)
            return
        if self._accept_simulation_config(simulation_config):
            self.subsystem_integration_session.set_simulation_session(scenario_session=self.scenario_session, simulation_config=simulation_config)
            self._record_runs(simulation_config)

    def _record_runs(self, simulation_config: SimulationInstanceConfig) -> None:
        """Records every run of the new live simulation session as a workbench entry (or reports that it cannot)."""
        simulation_session = self.subsystem_integration_session.simulation_session
        set_run_listener = getattr(simulation_session, "set_run_listener", None)
        if set_run_listener is None:
            return
        setup = LiveRunSetup(
            scenario_name=getattr(self.scenario_session, "file_name", None) or self.scenario_session.scenario_id,
            trajectories=self.scenario_session.trajectories,
            simulation_config=simulation_config,
            time_step=int(getattr(simulation_session, "time_step", self.scenario_session.time_step)),
        )
        set_run_listener(LiveSessionRecording(self.run_recorder, setup, self.loop, self.send_payload))

    def generate_simulation_models(self, simulation_config: SimulationInstanceConfig) -> None:
        if not self.scenario_session.is_initialized:
            self.send_runtime_error("No scenario loaded")
            return
        if not self._accept_simulation_config(simulation_config):
            return
        scene = self.scenario_session.trajectories.initial_scene
        if scene is None:
            self.send_runtime_error("No initial scene found")
            return
        self.subsystem_integration_session.simulation_session.generate_vessel_models(scene, simulation_config)

    def cancel(self) -> None:
        self.subsystem_integration_session.cancel()
        self.outbound_task.cancel()
        self.mqtt_broker_status_task.cancel()
