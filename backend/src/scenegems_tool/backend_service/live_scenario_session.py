import json
from datetime import datetime, timezone
from typing import Callable

from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from concrete_level.trajectory_generation.trajectory_data import TrajectoryData
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from scenegems_tool.monitoring.monitor_session import MonitorSession, iter_scene_batches
from scenegems_tool.backend_service.protocol import ServerMessage, make_initial_state_message
from scenegems_tool.backend_service.scenario_session import ScenarioSession
from utils.global_constants import ONE_HOUR_IN_SEC, ONE_SECOND


class LiveScenarioSession(ScenarioSession):
    def __init__(self, scenario_id: str, file_name: str, file_path: str, file_content: str, monitor_session: MonitorSession, send_payload: Callable[[ServerMessage], None]) -> None:
        try:
            trajectory_data: TrajectoryData = TrajectoryData.from_dict(json.loads(file_content))
            trajectory_builder = TrajectoryBuilder(trajectory_data.trajectories.time_step, trajectory_data.trajectories.scene_list).convert_to_time_step(ONE_SECOND)
        except Exception:
            eval_data: EvaluationData = EvaluationData.from_dict(json.loads(file_content))
            trajectory_builder = TrajectoryBuilder.default_builder_from_scene(eval_data.best_scene, ONE_SECOND, ONE_HOUR_IN_SEC)

        trajectories = trajectory_builder.simulate_acceleration_from_zero().shift_positions_to_zero().build()
        self._scenario_id = scenario_id
        self.file_name = file_name
        self.file_path = file_path
        self.loaded_at_utc = datetime.now(timezone.utc).isoformat()
        self._trajectories = trajectories

        initial_state_message = make_initial_state_message(scenario_id=scenario_id, time_step=trajectories.time_step, trajectory_length=trajectories.timespan)
        send_payload(initial_state_message)
        super().__init__(monitor_session, send_payload)

    def _send_scenario_chunks(self) -> None:
        for scenes, timestamps in iter_scene_batches(self.trajectories, self.time_step):
            self.monitor_session.step_preview_monitor_batch(
                scenario_id=self.scenario_id,
                scenes=scenes,
                timestamps=timestamps,
                time_step=self.time_step,
            )

    @property
    def time_step(self) -> int:
        return self.trajectories.time_step

    @property
    def scenario_id(self) -> str:
        return self._scenario_id

    @property
    def trajectory_length(self) -> int:
        return self.trajectories.timespan

    @property
    def is_initialized(self) -> bool:
        return self.trajectory_length > 0

    @property
    def trajectories(self) -> Trajectories:
        return self._trajectories
