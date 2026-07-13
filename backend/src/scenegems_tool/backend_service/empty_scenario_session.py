from typing import Callable
from concrete_level.models.trajectories import Trajectories
from scenegems_tool.monitoring.monitor_session import MonitorSession
from scenegems_tool.backend_service.protocol import ServerMessage
from scenegems_tool.backend_service.scenario_session import ScenarioSession

class EmptyScenarioSession(ScenarioSession):
    def __init__(self, monitor_session: MonitorSession, send_payload: Callable[[ServerMessage], None]) -> None:
        super().__init__(monitor_session, send_payload)
            
    def _send_scenario_chunks(self) -> None:
        pass
        
    @property
    def scenario_id(self) -> str:
        return ""
    
    @property
    def is_initialized(self) -> bool:
        return False
    
    @property
    def trajectories(self) -> Trajectories:
        return Trajectories(scene_list=[], time_step=0)