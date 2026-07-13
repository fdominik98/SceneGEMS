import random
from datetime import datetime
from typing import Dict, Optional, Tuple

import numpy as np

from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from concrete_level.models.vessel_order_graph import VesselOrderGraph, VesselOrderNode
from concrete_level.trajectory_generation.monitor_driven_rrt_search import MonitorDrivenRRTSearch
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from concrete_level.trajectory_generation.trajectory_data import TrajectoryData
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from utils.colregs_approximations import COLREGSConstraints
from utils.global_constants import ONE_HOUR_IN_SEC, ONE_SECOND
from utils.safety_domains import SafetyDomain

# TIME_STEP = ONE_SECOND
# TIME_STEP = TEN_SECONDS
# TIME_STEP = ONE_SECOND * 12
TIME_STEP = ONE_SECOND * 15
MAX_STEPS = 200


class TrajectoryGenerator:
    @staticmethod
    def generate_trajectories(eval_data: EvaluationData, initial_scene: ConcreteScene, colregs_constants: COLREGSConstraints) -> TrajectoryData:
        seed = 1234
        random.seed(seed)
        np.random.seed(seed)
        # ordered_vessels = VesselOrderGraph(scenario).sort()

        start_time = datetime.now()
        iter_numbers: Dict[int, int] = {}
        eval_times: Dict[int, float] = {}
        trajectories = TrajectoryBuilder.default_trajectory_from_scene(initial_scene, TIME_STEP, ONE_HOUR_IN_SEC)

        # for v_node in ordered_vessels:
        #     vessel = v_node.vessel
        #     o_start_time = datetime.now()
        #     potential_collision_domain = trajectories.potential_collision_domain(vessel)

        #     trajectories = TrajectoryBuilder.from_trajectories(trajectories).remove_vessel(vessel).build()

        #     path, iter_number = TrajectoryGenerator.run_trajectory_generation(v_node, trajectories, scenario, potential_collision_domain)

        #     builder = TrajectoryBuilder.from_trajectories(path).simulate_to_length(len(trajectories))
        #     trajectories = builder.merge(trajectories).build()

        #     o_eval_time = (datetime.now() - o_start_time).total_seconds()
        #     eval_times[vessel.id] = o_eval_time
        #     iter_numbers[vessel.id] = iter_number
        #     print(f"Trajectory generation for {vessel.name} took {o_eval_time} seconds")

        rrt = MonitorDrivenRRTSearch(
            start_scene=initial_scene,
            other_trajectories=trajectories,
            colregs_constants=colregs_constants,
        )

        # Add the original position to start the path
        trajectories, iter_number = rrt.plan_trajectory()

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

    # @staticmethod
    # def run_trajectory_generation(
    #     v_node: VesselOrderNode,
    #     trajectories: Trajectories,
    #     scenario: MultiLevelScenario,
    #     potential_collision_domain: Optional[SafetyDomain],
    # ) -> Tuple[Trajectories, int]:
    #     vessel = v_node.vessel
    #     vessel_state = scenario.concrete_scene[vessel]
    #     print(f"Calculation {vessel}:")

    #     if len(v_node.relations) == 0 or potential_collision_domain is None:
    #         return (
    #             TrajectoryBuilder.default_trajectory_from_vessel(vessel, vessel_state, trajectories.time_step, trajectories.timespan),
    #             0,
    #         )

    #     # ====Search Path with RRT====
    #     print(f"start RRT path planning for {vessel}")
    #     # Set Initial parameters

    #     rrt = MonitorDrivenRRTSearch(
    #         start_scene=scenario.concrete_scene,
    #         other_trajectories=trajectories,
    #         colregs_constants=colregs_constants,
    #     )

    #     # Add the original position to start the path
    #     path, iteration_count = rrt.plan_trajectory()

    #     return path, iteration_count
