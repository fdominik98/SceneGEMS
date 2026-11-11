import asyncio
import threading
from abc import ABC, abstractmethod
from typing import Callable, Dict, Optional

from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.gateway.protocol import ServerMessage, SimulationStatus, make_simulation_models_message, make_simulation_status_message
from scenegems_tool.subsystems.monitoring.monitor_session import MonitorSession
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_model_generator import GAZEBO_MODEL_CONTROL_LAYERS, generate_vessel_model


class SimulationSession(ABC):

    STATUS_UPDATE_INTERVAL_SEC = 1.0

    def __init__(self, send_payload: Callable[[ServerMessage], None], status: SimulationStatus):
        self.status = status
        self.send_payload = send_payload
        # Host port of each Mission Planner vessel's ground control station, by agent id, once the stack publishes them.
        self.ground_control_ports: Dict[str, int] = {}
        self._sent_ground_control_ports: Dict[str, int] = {}
        self._send_status()
        self._monitor_generation = 0
        self._chunk_send_task: Optional[asyncio.Task[None]] = None
        self.status_update_worker = asyncio.create_task(self._status_update_loop())

    async def _status_update_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.STATUS_UPDATE_INTERVAL_SEC)
                self._refresh_status()
        except asyncio.CancelledError:
            return
        except Exception as e:
            print(f"Error in status update loop: {e}")

    def _refresh_status(self) -> None:
        """Send the status when it, or the ground control station ports, changed since it was last sent."""
        new_status = self._status_update()
        if new_status == self.status and self.ground_control_ports == self._sent_ground_control_ports:
            return
        self.status = new_status
        self._send_status()

    def _send_status(self) -> None:
        ports = dict(self.ground_control_ports)
        self.send_payload(make_simulation_status_message(self.status, ports))
        self._sent_ground_control_ports = ports

    def teardown(self) -> None:
        self._cancel_workers()
        self._schedule_destroy()

    def destroy(self) -> None:
        self._cancel_workers()
        self.status = SimulationStatus.NOT_INITIALIZED
        self.ground_control_ports = {}
        self._send_status()
        self._schedule_destroy()

    def _cancel_workers(self) -> None:
        self.status_update_worker.cancel()
        if self._chunk_send_task is not None and not self._chunk_send_task.done():
            self._chunk_send_task.cancel()

    def _schedule_destroy(self) -> None:
        threading.Thread(
            target=self._destroy,
            name="simulation_session_destroy",
            daemon=True,
        ).start()

    @abstractmethod
    def _destroy(self) -> None:
        pass

    @abstractmethod
    def _status_update(self) -> SimulationStatus:
        pass

    def set_monitor_session(self, monitor_session: MonitorSession) -> None:
        if self._chunk_send_task is not None and not self._chunk_send_task.done():
            self._chunk_send_task.cancel()
        self._monitor_generation += 1
        generation = self._monitor_generation
        self.monitor_session = monitor_session
        self._chunk_send_task = asyncio.create_task(self._send_scenario_chunks_when_ready(generation))

    async def _send_scenario_chunks_when_ready(self, generation: int) -> None:
        try:
            if generation != self._monitor_generation:
                return
            self._send_scenario_chunks()
        except asyncio.CancelledError:
            return

    @abstractmethod
    def _send_scenario_chunks(self) -> None:
        pass

    @abstractmethod
    def start_simulation_runtime(self) -> None:
        pass

    def generate_vessel_models(self, scene: ConcreteScene, simulation_config: SimulationInstanceConfig) -> None:
        for vessel_config in simulation_config.vessels.values():
            if vessel_config.gazebo_vessel_model is not None or not vessel_config.is_simulated:
                continue
            if vessel_config.stack.control_layer not in GAZEBO_MODEL_CONTROL_LAYERS:
                continue  # a kinematic vessel has no Gazebo model
            vessel = scene.get_by_id(vessel_config.agent_id)
            if not isinstance(vessel, ConcreteVessel):
                continue
            vessel_model = generate_vessel_model(vessel, vessel_config.require_connection().agent_name, vessel_config.stack.control_layer, simulation_config.environment)
            vessel_config.gazebo_vessel_model = vessel_model

        message = make_simulation_models_message(simulation_config)
        self.send_payload(message)
