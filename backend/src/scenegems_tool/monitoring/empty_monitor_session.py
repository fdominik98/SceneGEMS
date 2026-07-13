from typing import Callable, Sequence

from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.monitoring.monitor_session import MonitorSession
from scenegems_tool.backend_service.protocol import ServerMessage, make_preview_chunk_message, make_simulation_chunk_message
from scenegems_tool.backend_service.serialization import serialize_frame


class EmptyMonitorSession(MonitorSession):
    def __init__(self, send_payload: Callable[[ServerMessage], None]):
        super().__init__(send_payload)

    def step_preview_monitor_batch(
        self,
        scenario_id: str,
        scenes: Sequence[ConcreteScene],
        timestamps: Sequence[int],
        time_step: int,
    ) -> None:
        frames = [serialize_frame(scenario_id=scenario_id, scene=scene, timestamp=timestamp, time_step=time_step) for scene, timestamp in zip(scenes, timestamps)]
        if not frames:
            return
        payload = make_preview_chunk_message(
            scenario_id=scenario_id,
            from_timestamp=timestamps[0],
            to_timestamp=timestamps[-1],
            frames=frames,
        )
        self.send_payload(payload)

    def step_simulation_monitor_batch(
        self,
        scenario_id: str,
        scenes: Sequence[ConcreteScene],
        timestamps: Sequence[int],
        time_step: int,
    ) -> None:
        frames = [serialize_frame(scenario_id=scenario_id, scene=scene, timestamp=timestamp, time_step=time_step) for scene, timestamp in zip(scenes, timestamps)]
        if not frames:
            return
        payload = make_simulation_chunk_message(
            scenario_id=scenario_id,
            from_timestamp=timestamps[0],
            to_timestamp=timestamps[-1],
            frames=frames,
        )
        self.send_payload(payload)

    @property
    def is_functioning(self) -> bool:
        return True

    @property
    def is_connected(self) -> bool:
        return False

    def _destroy(self) -> None:
        pass
