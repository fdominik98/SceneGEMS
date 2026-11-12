"""The scenario a workbench connection has loaded: its trajectories, and the preview the console draws.

The gateway is a set of in-process helpers of the console (gateway/socket_session.py): it reads a
scenario file and sends the scenes back as a plain preview. Nothing here runs a subsystem. The
console has the cluster judge the preview (a monitoring job) and run the scenario (a simulation
job), each on a worker node.
"""

import json
from datetime import datetime, timezone
from typing import Callable, Iterable, Iterator, List, Tuple

from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from concrete_level.trajectory_generation.trajectory_data import TrajectoryData
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from scenegems_tool.gateway.protocol import ServerMessage, make_initial_state_message, make_preview_chunk_message
from scenegems_tool.gateway.serialization import serialize_frame
from utils.global_constants import ONE_SECOND

# Scenes per preview message: a chunk the console can draw while the rest is still on its way.
SCENARIO_CHUNK_BATCH_SIZE = 100


def iter_scene_batches(
    scenes: Iterable[ConcreteScene],
    time_step: int,
    batch_size: int = SCENARIO_CHUNK_BATCH_SIZE,
) -> Iterator[Tuple[List[ConcreteScene], List[int]]]:
    """The scenes in batches with their timestamps: the first scene alone, so the console has something to draw at once."""
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


def scenario_trajectories(file_content: str) -> Trajectories:
    """The trajectories of a scenario file: a trajectory data file as it is planned, or a bare scene as a scenario of its initial scene only.

    json.JSONDecodeError for text that is no JSON; TypeError or ValueError for JSON that is neither.
    """
    raw_data = json.loads(file_content)
    # Dispatch on the payload shape rather than try/except. A bare "except Exception" here
    # used to swallow the real deserialization error and surface the EvaluationData
    # fallback's complaint about the TrajectoryData-only "scene_path" field instead, which
    # hid the actual cause of every failed scenario load.
    if isinstance(raw_data, dict) and raw_data.get("trajectories") is not None:
        trajectory_data: TrajectoryData = TrajectoryData.from_payload(raw_data)
        trajectory_builder = TrajectoryBuilder(trajectory_data.trajectories.time_step, trajectory_data.trajectories.scene_list).convert_to_time_step(ONE_SECOND)
        trajectory_builder = trajectory_builder.simulate_acceleration_from_zero().shift_positions_to_zero()
    else:
        # A bare scene is a scenario of its initial scene only. The trajectories come from a
        # trajectory generator (monitor-guided planner or straight); the workbench never appends any.
        eval_data: EvaluationData = EvaluationData.from_dict(raw_data)
        trajectory_builder = TrajectoryBuilder(ONE_SECOND, [eval_data.best_scene]).shift_positions_to_zero()
    return trajectory_builder.build()


class ScenarioSession:
    """A loaded scenario. Loading it tells the console its length (initial_state) and sends every scene as a plain preview frame."""

    def __init__(self, scenario_id: str, file_name: str, file_path: str, file_content: str, send_payload: Callable[[ServerMessage], None]) -> None:
        self.trajectories = scenario_trajectories(file_content)
        self.scenario_id = scenario_id
        self.file_name = file_name
        self.file_path = file_path
        self.loaded_at_utc = datetime.now(timezone.utc).isoformat()
        self.send_payload = send_payload
        send_payload(make_initial_state_message(scenario_id=scenario_id, time_step=self.time_step, trajectory_length=self.trajectory_length))
        self._send_preview()

    def _send_preview(self) -> None:
        for scenes, timestamps in iter_scene_batches(self.trajectories, self.time_step):
            frames = [serialize_frame(scenario_id=self.scenario_id, scene=scene, timestamp=timestamp, time_step=self.time_step) for scene, timestamp in zip(scenes, timestamps)]
            self.send_payload(make_preview_chunk_message(scenario_id=self.scenario_id, from_timestamp=timestamps[0], to_timestamp=timestamps[-1], frames=frames))

    @property
    def time_step(self) -> int:
        return self.trajectories.time_step

    @property
    def trajectory_length(self) -> int:
        return self.trajectories.timespan

    @property
    def is_initialized(self) -> bool:
        return len(self.trajectories) > 0
