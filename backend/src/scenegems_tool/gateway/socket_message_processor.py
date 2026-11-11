import asyncio
import json

from scenegems_tool.gateway.protocol import ClientMessage, simulation_config_from_body
from scenegems_tool.gateway.socket_session import SocketSession
from scenegems_tool.gateway.stack_options import stack_options_message


class SocketMessageProcessor:
    """Answers a console's helper requests one at a time: load a scenario file, generate vessel models, list the stack options.

    Any other message type is refused as unknown. That includes the messages of the former live
    session (connect_to_mqtt_broker, initialize_simulation, start_simulation, initialize_monitor and
    the rest): the gateway runs nothing, a simulation is a job on a worker node.
    """

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
                    case "generate_simulation_models":
                        try:
                            simulation_config = simulation_config_from_body(message)
                        except ValueError as exc:
                            self.session.send_runtime_error(f"Invalid simulation configuration: {exc}")
                        else:
                            self.session.generate_simulation_models(simulation_config)
                    case "query_stack_options":
                        self.session.send_payload(stack_options_message())
                    case _:
                        self.session.send_runtime_error(f"Unknown message type: {message['type']}")
                        print(f"Unknown message: {message}")
            except Exception as exc:
                self.session.send_runtime_error(f"Unhandled message processing error: {str(exc)}")

    def cancel(self) -> None:
        self.worker_task.cancel()
