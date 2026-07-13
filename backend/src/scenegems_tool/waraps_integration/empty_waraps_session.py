from typing import Callable

from scenegems_tool.backend_service.protocol import ServerMessage, make_error_message
from scenegems_tool.backend_service.scenario_session import ScenarioSession
from scenegems_tool.simulators.simulation_config import SimulationConfig
from scenegems_tool.waraps_integration.waraps_session import WARAPSSession


class EmptyWARAPSSession(WARAPSSession):
    def __init__(self, send_payload: Callable[[ServerMessage], None]):
        super().__init__(send_payload)

    @property
    def is_connected(self) -> bool:
        return False

    def set_monitor_session(self, name: str, topic: str, scope: str, colregs_constraints_content: str) -> None:
        self.send_payload(make_error_message(message="WARAPS is not connected"))

    def set_simulation_session(self, scenario_session: ScenarioSession, simulation_config: SimulationConfig) -> None:
        self.send_payload(make_error_message(message="WARAPS is not connected"))

    def _cancel(self) -> None:
        pass

    def generate_scene(self, request_id: str, functional_scenario_content: str, colregs_constraints_content: str, vessel_types_content: str, obstacle_types_content: str, timeout: int) -> None:
        self.send_payload(make_error_message(message="WARAPS is not connected"))

    async def stop_scene_generation(self) -> None:
        self.send_payload(make_error_message(message="WARAPS is not connected"))
