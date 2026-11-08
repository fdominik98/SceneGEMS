"""The straight trajectory generator: every vessel goes straight on from the initial scene up to a timespan.

One of the two trajectory generators a pipeline chooses from (the other is the
monitor-guided planner). It searches nothing and draws no random numbers, so it returns at once
and its plan is always complete.
"""

from datetime import datetime
from typing import Optional

from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from concrete_level.trajectory_generation.trajectory_data import TrajectoryData
from utils.global_constants import ONE_HOUR_IN_SEC

STRAIGHT_ALGORITHM = "straight"  # TrajectoryData.algorithm_desc
DEFAULT_TIMESPAN_S = ONE_HOUR_IN_SEC  # what the workbench appended to a bare scene so far


def straight_trajectory_data(initial_scene: ConcreteScene, time_step: int, timespan: Optional[float], config_name: str, seed: Optional[int]) -> TrajectoryData:
    """Every vessel holds its initial heading and speed, sampled every time_step seconds until timespan (rounded up to a step)."""
    started = datetime.now()
    trajectories = TrajectoryBuilder.default_trajectory_from_scene(initial_scene, time_step, timespan if timespan is not None else DEFAULT_TIMESPAN_S)
    elapsed = (datetime.now() - started).total_seconds()
    return TrajectoryData(
        measurement_name="trajectory_generation",
        iter_numbers={0: 0},
        algorithm_desc=STRAIGHT_ALGORITHM,
        config_name=config_name,
        scene_path=None,
        random_seed=seed,
        timestamp=datetime.now().isoformat(),
        trajectories=trajectories,
        overall_eval_time=elapsed,
        rrt_evaluation_times={0: elapsed},
    )
