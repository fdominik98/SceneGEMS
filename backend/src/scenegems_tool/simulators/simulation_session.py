import asyncio
import threading
from abc import ABC, abstractmethod
from typing import Callable, Optional

from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.backend_service.protocol import ServerMessage, SimulationStatus, make_simulation_models_message, make_simulation_status_message
from scenegems_tool.monitoring.monitor_session import MonitorSession
from scenegems_tool.simulators.gazeboo.vessel_model_generator import generate_vessel_model
from scenegems_tool.simulators.simulation_config import SimulationConfig


class SimulationSession(ABC):

    STATUS_UPDATE_INTERVAL_SEC = 1.0

    def __init__(self, send_payload: Callable[[ServerMessage], None], status: SimulationStatus):
        self.status = status
        self.send_payload = send_payload
        self.send_payload(make_simulation_status_message(status=self.status))
        self._monitor_generation = 0
        self._chunk_send_task: Optional[asyncio.Task[None]] = None
        self.status_update_worker = asyncio.create_task(self._status_update_loop())

    async def _status_update_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.STATUS_UPDATE_INTERVAL_SEC)
                new_status = self._status_update()
                if new_status == self.status:
                    continue
                self.status = new_status
                self.send_payload(make_simulation_status_message(status=self.status))
        except asyncio.CancelledError:
            return
        except Exception as e:
            print(f"Error in status update loop: {e}")

    def teardown(self) -> None:
        self._cancel_workers()
        self._schedule_destroy()

    def destroy(self) -> None:
        self._cancel_workers()
        self.status = SimulationStatus.NOT_INITIALIZED
        self.send_payload(make_simulation_status_message(status=self.status))
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

    def generate_vessel_models(self, scene: ConcreteScene, simulation_config: SimulationConfig) -> None:
        for agent_config in simulation_config.simulated_agents.values():
            if agent_config.gazebo_vessel_model is not None or agent_config.context != "simulation":
                continue
            vessel = scene.get_by_id(agent_config.agent_id)
            if not isinstance(vessel, ConcreteVessel):
                continue
            vessel_model = generate_vessel_model(vessel, agent_config.agent_name)
            agent_config.gazebo_vessel_model = vessel_model

        message = make_simulation_models_message(simulation_config)
        self.send_payload(message)
