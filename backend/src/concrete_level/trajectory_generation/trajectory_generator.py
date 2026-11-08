import random
from datetime import datetime

import numpy as np

from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.trajectory_generation.monitor_guided_planner import MonitorGuidedPlanner
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from concrete_level.trajectory_generation.trajectory_data import TrajectoryData
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from utils.colregs_approximations import COLREGSConstraints
from utils.global_constants import ONE_HOUR_IN_SEC, ONE_SECOND

TIME_STEP = ONE_SECOND * 15


class TrajectoryGenerator:
    @staticmethod
    def generate_trajectories(eval_data: EvaluationData, initial_scene: ConcreteScene, colregs_constants: COLREGSConstraints) -> TrajectoryData:
        seed = 1234
        random.seed(seed)
        np.random.seed(seed)

        start_time = datetime.now()
        trajectories = TrajectoryBuilder.default_trajectory_from_scene(initial_scene, TIME_STEP, ONE_HOUR_IN_SEC)

        planner = MonitorGuidedPlanner(
            start_scene=initial_scene,
            other_trajectories=trajectories,
            colregs_constants=colregs_constants,
        )

        # Add the original position to start the path
        trajectories, iter_number = planner.plan_trajectory()

        overall_eval_time = (datetime.now() - start_time).total_seconds()
        timestamp = datetime.now().isoformat()

        trajectory_data = TrajectoryData(
            measurement_name="test",
            iter_numbers={0: iter_number},
            algorithm_desc="RRTStar_algo",
            config_name=eval_data.scenario_name,
            scene_path=eval_data.path,
            random_seed=seed,
            timestamp=timestamp,
            trajectories=trajectories,
            overall_eval_time=overall_eval_time,
            rrt_evaluation_times={0: overall_eval_time},
        )

        trajectory_data.save_as_measurement()
        return trajectory_data
