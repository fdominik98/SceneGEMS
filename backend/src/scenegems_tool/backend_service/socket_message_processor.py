import asyncio
import json

from scenegems_tool.backend_service.protocol import ClientMessage, simulation_config_from_body
from scenegems_tool.backend_service.socket_session import SocketSession
from scenegems_tool.waraps_integration.sim_utils import Geofence


class SocketMessageProcessor:
    def __init__(self, session: SocketSession):
        self.session = session
        self.inbound_queue: asyncio.Queue[ClientMessage] = asyncio.Queue()
        self.worker_task = asyncio.create_task(self._process_messages())

    async def _process_messages(self) -> None:
        while True:
            message = await self.inbound_queue.get()
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

                    case "connect_to_waraps":
                        geofence_msg = message["geofence"]
                        geofence = Geofence(
                            latitude=float(geofence_msg["latitude"]),
                            longitude=float(geofence_msg["longitude"]),
                            radius_meters=float(geofence_msg["radius_meters"]),
                        )
                        try:
                            self.session.connect_to_waraps(
                                user=message["user"],
                                password=message["password"],
                                agent_broker=message["agent_broker"],
                                client_broker=message["client_broker"],
                                port=message["port"],
                                tls_connection=message["tls_connection"],
                                allow_certificates=message["allow_certificates"],
                                reference_geofence=geofence,
                            )
                        except Exception as exc:
                            self.session.send_runtime_error("Failed to connect to WARAPS")
                            print(f"Failed to connect to WARAPS: {str(exc)}")
                    case "disconnect_from_waraps":
                        self.session.disconnect_from_waraps()
                    case "start_simulation":
                        self.session.waraps_session.simulation_session.start_simulation_runtime()
                    case "reset_simulation":
                        asyncio.create_task(self._handle_reset_simulation())
                    case "initialize_simulation":
                        self.session.set_simulation_session(simulation_config_from_body(message))
                    case "generate_simulation_models":
                        self.session.generate_simulation_models(simulation_config_from_body(message))
                    case "initialize_monitor":
                        self.session.set_monitor_session(message["name"], message["topic"], message["scope"], message["colregsConstraintsContent"])
                    case "shut_down_monitor":
                        self.session.shut_down_monitor()
                    case "generate_scene":
                        try:
                            self.session.waraps_session.generate_scene(
                                request_id=message["requestId"],
                                functional_scenario_content=message["functionalScenarioContent"],
                                colregs_constraints_content=message["colregsConstraintsContent"],
                                vessel_types_content=message["vesselTypesContent"],
                                obstacle_types_content=message["obstacleTypesContent"],
                                timeout=message["timeout"],
                            )
                            pass
                        except Exception as exc:
                            self.session.send_runtime_error(f"Failed to generate scene: {str(exc)}")
                            print(f"Failed to generate scene: {str(exc)}")
                    case "stop_scene_generation":
                        asyncio.create_task(self._handle_stop_scene_generation())
                    case _:
                        self.session.send_runtime_error(f"Unknown message type: {message['type']}")
                        print(f"Unknown message: {message}")
            except Exception as exc:
                self.session.send_runtime_error(f"Unhandled message processing error: {str(exc)}")

    async def _handle_stop_scene_generation(self) -> None:
        try:
            await self.session.waraps_session.stop_scene_generation()
        except Exception as exc:
            self.session.send_runtime_error(f"Failed to stop scene generation: {str(exc)}")

    async def _handle_reset_simulation(self) -> None:
        try:
            await self.session.waraps_session.reset_simulation_session_async()
        except Exception as exc:
            self.session.send_runtime_error(f"Failed to reset simulation: {str(exc)}")

    def cancel(self) -> None:
        self.worker_task.cancel()
