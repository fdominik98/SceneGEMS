import asyncio
import json
import traceback

from scenegems_tool.gateway.protocol import ClientMessage, simulation_config_from_body
from scenegems_tool.gateway.socket_session import SocketSession
from scenegems_tool.gateway.stack_options import stack_options_message
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

# The messages that start a live session's containers on the gateway's Docker (the scenario execution
# service, the monitor, the vessel stacks); a control node without the Docker socket refuses them.
LIVE_SESSION_MESSAGES = frozenset({"connect_to_mqtt_broker", "initialize_simulation", "initialize_monitor"})


def live_sessions_off_message(message_type: str) -> str:
    return (
        f"Live sessions are off on this control node, so {message_type} is refused: control-node-api has no Docker socket "
        "(SCENEGEMS_LIVE_SESSIONS=false; its COMPOSE_FILE leaves out docker-compose.live-sessions.yml). "
        "Campaigns and cluster jobs still run; run live sessions on a control node that has them on."
    )


class SocketMessageProcessor:
    def __init__(self, session: SocketSession, live_sessions: bool = True):
        self.session = session
        self.live_sessions = live_sessions
        self.inbound_queue: asyncio.Queue[ClientMessage] = asyncio.Queue()
        self.worker_task = asyncio.create_task(self._process_messages())

    async def _process_messages(self) -> None:
        while True:
            message = await self.inbound_queue.get()
            if not self.live_sessions and message.get("type") in LIVE_SESSION_MESSAGES:
                self.session.send_runtime_error(live_sessions_off_message(message["type"]))
                continue
            try:
                match message["type"]:
                    case "load_scenario_file":
                        try:
                            self.session.set_scenario_session(
                                scenario_id=message["scenarioId"],
                                file_name=message["fileName"],
                                file_path=message["filePath"],
                                file_content=message["fileContent"],
                            )
                        except json.JSONDecodeError:
                            self.session.send_runtime_error("Invalid scene file JSON.")
                        except (TypeError, ValueError) as exc:
                            self.session.send_runtime_error(f"Failed to load scene: {str(exc)}")

                    case "connect_to_mqtt_broker":
                        geofence_msg = message["geofence"]
                        geofence = Geofence(
                            latitude=float(geofence_msg["latitude"]),
                            longitude=float(geofence_msg["longitude"]),
                            radius_meters=float(geofence_msg["radius_meters"]),
                        )
                        use_control_node_broker = bool(message.get("use_control_node_broker", False))
                        try:
                            await self.session.connect_to_mqtt_broker(
                                user=message["user"],
                                password=message["password"],
                                agent_broker=message["agent_broker"],
                                client_broker=message["client_broker"],
                                port=message["port"],
                                tls_connection=message["tls_connection"],
                                allow_certificates=message["allow_certificates"],
                                reference_geofence=geofence,
                                use_control_node_broker=use_control_node_broker,
                            )
                        except Exception as exc:
                            detail = str(exc).strip() or exc.__class__.__name__
                            requested = "the control node broker" if use_control_node_broker else f"MQTT broker {message['client_broker']}:{message['port']}"
                            self.session.send_runtime_error(f"Failed to connect to {requested}. {detail}")
                            print(f"Failed to connect to the MQTT broker: {traceback.format_exc()}")
                    case "disconnect_from_mqtt_broker":
                        self.session.disconnect_from_mqtt_broker()
                    case "start_simulation":
                        self.session.subsystem_integration_session.simulation_session.start_simulation_runtime()
                    case "reset_simulation":
                        asyncio.create_task(self._handle_reset_simulation())
                    case "initialize_simulation":
                        try:
                            simulation_config = simulation_config_from_body(message)
                        except ValueError as exc:
                            self.session.send_runtime_error(f"Invalid simulation configuration: {exc}")
                        else:
                            self.session.set_simulation_session(simulation_config)
                    case "generate_simulation_models":
                        try:
                            simulation_config = simulation_config_from_body(message)
                        except ValueError as exc:
                            self.session.send_runtime_error(f"Invalid simulation configuration: {exc}")
                        else:
                            self.session.generate_simulation_models(simulation_config)
                    case "query_stack_options":
                        self.session.send_payload(stack_options_message())
                    case "initialize_monitor":
                        self.session.set_monitor_session(message["name"], message["topic"], message["scope"], message["colregsConstraintsContent"])
                    case "shut_down_monitor":
                        self.session.shut_down_monitor()
                    case _:
                        self.session.send_runtime_error(f"Unknown message type: {message['type']}")
                        print(f"Unknown message: {message}")
            except Exception as exc:
                self.session.send_runtime_error(f"Unhandled message processing error: {str(exc)}")

    async def _handle_reset_simulation(self) -> None:
        try:
            await self.session.subsystem_integration_session.reset_simulation_session_async()
        except Exception as exc:
            self.session.send_runtime_error(f"Failed to reset simulation: {str(exc)}")

    def cancel(self) -> None:
        self.worker_task.cancel()
