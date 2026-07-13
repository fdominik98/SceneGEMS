import asyncio
from abc import ABC, abstractmethod
from typing import Callable, Optional

from concrete_level.models.trajectories import Trajectories
from scenegems_tool.monitoring.monitor_session import MonitorSession
from scenegems_tool.backend_service.protocol import ServerMessage


class ScenarioSession(ABC):
    def __init__(self, monitor_session: MonitorSession, send_payload: Callable[[ServerMessage], None]) -> None:
        self.send_payload = send_payload
        self._chunk_send_task: Optional[asyncio.Task[None]] = None
        self._monitor_generation = 0
        self.set_monitor_session(monitor_session)

    @abstractmethod
    def _send_scenario_chunks(self) -> None:
        pass

    def set_monitor_session(self, monitor_session: MonitorSession) -> None:
        if self._chunk_send_task is not None and not self._chunk_send_task.done():
            self._chunk_send_task.cancel()
        self._monitor_generation += 1
        generation = self._monitor_generation
        self.monitor_session = monitor_session
        self._chunk_send_task = asyncio.create_task(self._send_scenario_chunks_task(generation))

    async def _send_scenario_chunks_task(self, generation: int) -> None:
        try:
            if generation != self._monitor_generation:
                return
            self._send_scenario_chunks()
        except asyncio.CancelledError:
            return

    @property
    @abstractmethod
    def scenario_id(self) -> str:
        pass

    @property
    @abstractmethod
    def is_initialized(self) -> bool:
        pass

    @property
    @abstractmethod
    def trajectories(self) -> Trajectories:
        pass
