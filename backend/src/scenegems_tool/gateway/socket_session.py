"""One console's connection to the workbench gateway: the scenario it loaded and the answers to its helper requests.

The gateway runs no subsystem and holds no broker connection. It reads a scenario file, sends its
scenes as a plain preview, generates Gazebo vessel models for a setup and lists the stack options;
everything that computes runs as a job on a worker node, which the console submits to the operator API.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional, Union

from fastapi import WebSocket

from scenegems_tool.gateway.protocol import ClientMessage, ServerMessage, make_error_message, make_simulation_models_message
from scenegems_tool.gateway.vessel_models import generate_vessel_models
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from scenegems_tool.workbench.scenario_session import ScenarioSession


class SocketSession:

    def __init__(self, websocket: WebSocket):
        self.websocket: WebSocket = websocket
        self.outbound_queue: asyncio.Queue[ServerMessage] = asyncio.Queue()
        self.outbound_task: asyncio.Task[None] = asyncio.create_task(self._outbound_loop())

        self.created_at_utc = datetime.now(timezone.utc).isoformat()
        self.scenario_session: Optional[ScenarioSession] = None  # the loaded scenario; None until load_scenario_file

    @property
    def connection_id(self) -> str:
        return str(id(self.websocket))

    def log_payload(self, direction: str, payload: Union[ServerMessage, ClientMessage]) -> None:
        if payload["type"] == "preview_trajectory_chunk":
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

    def set_scenario_session(self, scenario_id: str, file_name: str, file_path: str, file_content: str) -> None:
        """Loads a scenario file: the console gets its length and its scenes as a plain preview. json.JSONDecodeError, TypeError or ValueError for a file that is no scenario."""
        self.scenario_session = ScenarioSession(scenario_id=scenario_id, file_name=file_name, file_path=file_path, file_content=file_content, send_payload=self.send_payload)

    def _accept_simulation_config(self, simulation_config: SimulationInstanceConfig) -> bool:
        """Validate the vessel stacks, environment and speedup through the adapter registry."""
        resolution = default_resolver().resolve_instance(simulation_config)
        for warning in resolution.warnings:
            print(f"Simulation configuration warning: {warning}")
        if not resolution.accepted:
            self.send_runtime_error(f"Simulation configuration rejected: {resolution.reason}")
            return False
        return True

    def generate_simulation_models(self, simulation_config: SimulationInstanceConfig) -> None:
        """Answers with the setup, every simulated vessel that had no Gazebo model now carrying a generated one."""
        if self.scenario_session is None or not self.scenario_session.is_initialized:
            self.send_runtime_error("No scenario loaded")
            return
        if not self._accept_simulation_config(simulation_config):
            return
        scene = self.scenario_session.trajectories.initial_scene
        if scene is None:
            self.send_runtime_error("No initial scene found")
            return
        self.send_payload(make_simulation_models_message(generate_vessel_models(scene, simulation_config)))

    def cancel(self) -> None:
        self.outbound_task.cancel()
