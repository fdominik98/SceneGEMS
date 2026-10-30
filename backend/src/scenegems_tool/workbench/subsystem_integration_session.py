from abc import ABC, abstractmethod
from typing import Callable, Optional

from scenegems_tool.cluster.node.instance_scope import InstanceScope
from scenegems_tool.gateway.protocol import ServerMessage
from scenegems_tool.subsystems.monitoring.empty_monitor_session import EmptyMonitorSession
from scenegems_tool.subsystems.monitoring.monitor_session import MonitorSession
from scenegems_tool.subsystems.scenario_execution.empty_simulation_session import EmptySimulationSession
from scenegems_tool.subsystems.scenario_execution.simulation_session import SimulationSession
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig
from scenegems_tool.workbench.scenario_session import ScenarioSession


class SubsystemIntegrationSession(ABC):
    """The workbench's interactive simulation over one MQTT broker: the simulation session and its live monitor.

    Scene and trajectory generation are not here: the workbench runs them as jobs on the cluster.
    """

    session_scope: Optional[InstanceScope] = None  # the live session's scope; names its simulation stack

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
    def set_simulation_session(self, scenario_session: ScenarioSession, simulation_config: SimulationInstanceConfig) -> None:
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
        self.simulation_session = EmptySimulationSession(send_payload=self.send_payload, session_scope=self.session_scope)
        previous.teardown()

    async def reset_simulation_session_async(self) -> None:
        self.reset_simulation_session()

    def reset_monitor_session(self) -> None:
        self.monitor_session.destroy()
        self.monitor_session = EmptyMonitorSession(send_payload=self.send_payload)
        self.simulation_session.set_monitor_session(self.monitor_session)
