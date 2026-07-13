import asyncio
from abc import ABC, abstractmethod
from typing import Callable, Iterable, Iterator, List, Sequence, Tuple

from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.backend_service.protocol import ServerMessage, make_monitor_status_message

SCENARIO_CHUNK_BATCH_SIZE = 100


def iter_scene_batches(
    scenes: Iterable[ConcreteScene],
    time_step: int,
    batch_size: int = SCENARIO_CHUNK_BATCH_SIZE,
) -> Iterator[Tuple[List[ConcreteScene], List[int]]]:
    scene_list = list(scenes)
    if not scene_list:
        return
    yield [scene_list[0]], [0]
    if len(scene_list) == 1:
        return
    for start in range(1, len(scene_list), batch_size):
        batch = scene_list[start : start + batch_size]
        timestamps = [(start + index) * time_step for index in range(len(batch))]
        yield batch, timestamps


class MonitorSession(ABC):
    def __init__(self, send_payload: Callable[[ServerMessage], None]):
        self.send_payload = send_payload
        self.monitor_status_task = asyncio.create_task(self._monitor_status_loop())

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        pass

    async def _monitor_status_loop(self) -> None:
        while True:
            await asyncio.sleep(1)
            if self.is_connected:
                status = "connected"
            else:
                status = "disconnected"
            self.send_payload(make_monitor_status_message(status=status))

    def step_preview_monitor(self, scenario_id: str, scene: ConcreteScene, timestamp: int, time_step: int) -> None:
        self.step_preview_monitor_batch(scenario_id, [scene], [timestamp], time_step)

    def step_simulation_monitor(self, scenario_id: str, scene: ConcreteScene, timestamp: int, time_step: int) -> None:
        self.step_simulation_monitor_batch(scenario_id, [scene], [timestamp], time_step)

    @abstractmethod
    def step_preview_monitor_batch(
        self,
        scenario_id: str,
        scenes: Sequence[ConcreteScene],
        timestamps: Sequence[int],
        time_step: int,
    ) -> None:
        pass

    @abstractmethod
    def step_simulation_monitor_batch(
        self,
        scenario_id: str,
        scenes: Sequence[ConcreteScene],
        timestamps: Sequence[int],
        time_step: int,
    ) -> None:
        pass

    def destroy(self) -> None:
        self.monitor_status_task.cancel()
        self._destroy()

    @abstractmethod
    def _destroy(self) -> None:
        pass
