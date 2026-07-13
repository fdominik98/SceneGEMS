from abc import ABC, abstractmethod
from typing import Callable

from scenegems_tool.backend_service.protocol import ServerMessage
from scenegems_tool.backend_service.scenario_session import ScenarioSession
from scenegems_tool.monitoring.empty_monitor_session import EmptyMonitorSession
from scenegems_tool.monitoring.monitor_session import MonitorSession
from scenegems_tool.simulators.empty_simulation_session import EmptySimulationSession
from scenegems_tool.simulators.simulation_config import SimulationConfig
from scenegems_tool.simulators.simulation_session import SimulationSession


class WARAPSSession(ABC):
    def __init__(self, send_payload: Callable[[ServerMessage], None]):
        self.send_payload = send_payload
        self.monitor_session: MonitorSession = EmptyMonitorSession(send_payload)
        self.simulation_session: SimulationSession = EmptySimulationSession(send_payload)

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        pass

    @abstractmethod
    def set_monitor_session(self, name: str, topic: str, scope: str, colregs_constraints_content: str) -> None:
        pass

    @abstractmethod
    def set_simulation_session(self, scenario_session: ScenarioSession, simulation_config: SimulationConfig) -> None:
        pass

    @abstractmethod
    def _cancel(self) -> None:
        pass

    def cancel(self) -> None:
        self.simulation_session.destroy()
        self.monitor_session.destroy()
        self._cancel()

    def reset_simulation_session(self) -> None:
        previous = self.simulation_session
        self.simulation_session = EmptySimulationSession(send_payload=self.send_payload)
        previous.teardown()

    async def reset_simulation_session_async(self) -> None:
        self.reset_simulation_session()

    def reset_monitor_session(self) -> None:
        self.monitor_session.destroy()
        self.monitor_session = EmptyMonitorSession(send_payload=self.send_payload)
        self.simulation_session.set_monitor_session(self.monitor_session)

    @abstractmethod
    def generate_scene(self, request_id: str, functional_scenario_content: str, colregs_constraints_content: str, vessel_types_content: str, obstacle_types_content: str, timeout: int) -> None:
        pass

    @abstractmethod
    async def stop_scene_generation(self) -> None:
        pass
