import time
from abc import abstractmethod
from typing import Callable, List, Optional, Tuple

import numpy as np
from scenic.core.scenarios import Scenario as ScenicScenario

from functional_level.metamodels.functional_scenario import FunctionalScenario
from utils.colregs_approximations import drift_threshold, o2VisibilityByo1, possible_vis_distances_by_bearing, possible_vis_distances_by_length, vis_distance
from logical_level.constraint_satisfaction.aggregates import Aggregate
from logical_level.constraint_satisfaction.assignments import Assignments
from logical_level.constraint_satisfaction.csp_evaluation.csp_solver import CSPSolver
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from logical_level.constraint_satisfaction.rejection_sampling.scenic_utils import generate_scene, scenic_scenario
from logical_level.models.logical_scenario import LogicalScenario
from utils.global_constants import BEAM_ROTATION_ANGLE, BOW_ANGLE, ONE_N_MILE_IN_M, SIDE_ANGLE, STERN_ANGLE


class RejectionSamplingPipeline(CSPSolver):
    def __init__(self, verbose: bool, observer: Callable[[List[float], int, float], None] = lambda x, y, z: None,
                 termination_signal: Callable[[], bool] = lambda: False) -> None:
        self.verbose = verbose
        self.observer = observer
        self.termination_signal = termination_signal

    def init_problem(
        self,
        logical_scenario: LogicalScenario,
        functional_scenario: Optional[FunctionalScenario],
        initial_population: List[List[float]],
        eval_data: EvaluationData,
    ):
        aggregate = Aggregate.factory(logical_scenario, eval_data.aggregate_strat, minimize=True)
        return aggregate, logical_scenario, functional_scenario, initial_population

    @abstractmethod
    def _provide_region_maps(
        self,
        os_id: int,
        ts_ids: List[int],
        obst_ids: List[int],
        length_map: dict,
        radius_map: dict,
        functional_scenario: Optional[FunctionalScenario] = None,
    ) -> Tuple[dict, dict, dict, dict]:
        pass

    def first_sampling_step(
        self,
        logical_scenario: LogicalScenario,
        functional_scenario: Optional[FunctionalScenario],
        eval_data: EvaluationData,
    ) -> Tuple[ScenicScenario, List[float]]:
        first_solution = logical_scenario.get_population(eval_data.population_size)[0]
        assignments = Assignments(logical_scenario.actor_variables).update_from_individual(first_solution)

        os_id = logical_scenario.os_variable.id
        ts_ids = [v.id for v in logical_scenario.ts_variables]
        obst_ids = [v.id for v in logical_scenario.obstacle_variables]
        length_map = {}
        radius_map = {}
        speed_boundary_map = {}

        for var in logical_scenario.actor_variables:
            length_map[var.id] = assignments[var].l
            radius_map[var.id] = assignments[var].r
            speed_boundary_map[var.id] = (var.min_speed, var.max_speed)
            
        drift_threshold_map = {}
        for var in logical_scenario.actor_variables:
            if var.id == os_id:
                continue
            drift_threshold_map[(os_id, var.id)] = drift_threshold(length_map[os_id], length_map[var.id])

        (
            possible_distances_map,
            min_distance_map,
            vis_distance_map,
            bearing_map,
        ) = self._provide_region_maps(os_id, ts_ids, obst_ids, length_map, radius_map, functional_scenario)

        scenario = scenic_scenario(
            os_id,
            ts_ids,
            obst_ids,
            length_map,
            radius_map,
            speed_boundary_map,
            possible_distances_map,
            min_distance_map,
            vis_distance_map=vis_distance_map,
            bearing_map=bearing_map,
            drift_threshold_map=drift_threshold_map,
            verbose=self.verbose,
        )
        return scenario, first_solution

    def evaluate(
        self,
        some_input: Tuple[Aggregate, LogicalScenario, FunctionalScenario, List[float]],
        eval_data: EvaluationData,
    ):
        (
            aggregate,
            logical_scenario,
            functional_scenario,
            default_population,
        ) = some_input
        iterations = 0
        start_time = time.time()
        while True and not self.termination_signal():
            runtime = time.time() - start_time
            if runtime >= eval_data.timeout:
                print(f"Sampling reached timeout.")
                break
            scenario, first_solution = self.first_sampling_step(logical_scenario, functional_scenario, eval_data)
            solution, rejection = generate_scene(scenario, aggregate, first_solution)
            self.observer(solution, iterations, runtime)
            default_population = solution
            if not rejection:
                break

            if self.verbose:
                print(f"Rejected sample {iterations} because of {rejection}")
            iterations += 1
        return default_population, iterations, time.time() - start_time

    def convert_results(self, some_results: Tuple[List[float], int, float], eval_data: EvaluationData) -> Tuple[List[float], int, float]:
        scene, iterations, runtime = some_results
        return scene, iterations, runtime


class TwoStepCDRejectionSampling(RejectionSamplingPipeline):
    def __init__(self, verbose: bool, observer: Callable[[List[float], int, float], None] = lambda x, y, z: None,
                 termination_signal: Callable[[], bool] = lambda: False) -> None:
        super().__init__(verbose, observer, termination_signal)

    def _provide_region_maps(
        self,
        os_id: int,
        ts_ids: List[int],
        obst_ids: List[int],
        length_map: dict,
        radius_map: dict,
        functional_scenario: Optional[FunctionalScenario] = None,
    ) -> Tuple[dict, dict, dict, dict]:
        if functional_scenario is None:
            raise ValueError("Functional scenario must be provided for TwoStepCDRejectionSampling.")

        vis_distance_map = {}
        bearing_map = {}

        for obst_id in obst_ids:
            vis_distance_map[(os_id, obst_id)] = o2VisibilityByo1(True, radius_map[obst_id])

        os = functional_scenario.os_object
        for ts in functional_scenario.ts_objects:
            vis_distance_map[(os.id, ts.id)] = vis_distance(
                functional_scenario.in_stern_sector_of_interpretation.contains((ts, os)),
                length_map[os.id],
                functional_scenario.in_stern_sector_of_interpretation.contains((os, ts)),
                length_map[ts.id],
            )

            sin_half_col_cone_theta = np.clip(
                max(radius_map[os.id], radius_map[ts.id]) / vis_distance_map[(os.id, ts.id)],
                -1,
                1,
            )
            angle_col_cone = abs(np.arcsin(sin_half_col_cone_theta)) * 2

            # heading_ego_to_ts, bearing_angle_ego_to_ts, heading_ts_to_ego, bearing_angle_ts_to_ego
            # heading_ego_to_ts: relative angle to ego heading
            # heading_ts_to_ego: relative angle to p12
            bow_angle = max(angle_col_cone, BOW_ANGLE)

            # scenarios = [
            #     (functional_scenario.in_port_side_sector_of_interpretation.contains, (GlobalConfig.BEAM_ROTATION_ANGLE,  GlobalConfig.SIDE_ANGLE)),
            #     (functional_scenario.in_starboard_side_sector_of_interpretation.contains, (-GlobalConfig.BEAM_ROTATION_ANGLE, GlobalConfig.SIDE_ANGLE)),
            #     (functional_scenario.in_stern_sector_of_interpretation.contains, (-np.pi, GlobalConfig.STERN_ANGLE)),
            #     (lambda tuple : (functional_scenario.in_bow_sector_of_interpretation.contains(tuple) and
            #                      functional_scenario.in_port_side_sector_of_interpretation),
            #                                 (bow_angle/4, bow_angle/2)),
            #     (lambda tuple : (functional_scenario.in_bow_sector_of_interpretation.contains(tuple) and
            #                      functional_scenario.in_port_side_sector_of_interpretation),
            #                                 (-bow_angle/4, bow_angle/2)),
            # ]

            scenarios = [
                (functional_scenario.head_on(os, ts), (0.0, bow_angle, 0.0, bow_angle)),
                (
                    functional_scenario.crossing_from_port(os, ts),
                    (
                        -BEAM_ROTATION_ANGLE,
                        SIDE_ANGLE,
                        -BEAM_ROTATION_ANGLE,
                        SIDE_ANGLE,
                    ),
                ),
                (
                    functional_scenario.crossing_from_port(ts, os),
                    (
                        BEAM_ROTATION_ANGLE,
                        SIDE_ANGLE,
                        BEAM_ROTATION_ANGLE,
                        SIDE_ANGLE,
                    ),
                ),
                (
                    functional_scenario.overtaking_to_port(os, ts),
                    (
                        BEAM_ROTATION_ANGLE,
                        SIDE_ANGLE,
                        -np.pi,
                        STERN_ANGLE,
                    ),
                ),
                (
                    functional_scenario.overtaking_to_port(ts, os),
                    (
                        -np.pi,
                        STERN_ANGLE,
                        -BEAM_ROTATION_ANGLE,
                        SIDE_ANGLE,
                    ),
                ),
                (
                    functional_scenario.overtaking_to_starboard(os, ts),
                    (
                        -BEAM_ROTATION_ANGLE,
                        SIDE_ANGLE,
                        -np.pi,
                        STERN_ANGLE,
                    ),
                ),
                (
                    functional_scenario.overtaking_to_starboard(ts, os),
                    (
                        -np.pi,
                        STERN_ANGLE,
                        BEAM_ROTATION_ANGLE,
                        SIDE_ANGLE,
                    ),
                ),
            ]

            for condition, bearing in scenarios:
                if condition:
                    bearing_map[(os.id, ts.id)] = bearing

            # scenario1 = (0, 0)
            # for condition, bearing in scenarios:
            #     if condition((o, os)):
            #         scenario1 = bearing

            # scenario2 = (0, 0)
            # for condition, bearing in scenarios:
            #     if condition((os, o)):
            #         scenario2 = bearing

            # bearing_map[(os.id, o.id)] = (scenario1[0], scenario1[1], scenario2[0], scenario2[1])

            for ts in functional_scenario.obstacle_objects:
                os = functional_scenario.os_object

                sin_half_col_cone_theta = np.clip(
                    max(radius_map[os.id], radius_map[ts.id]) / vis_distance_map[(os.id, ts.id)],
                    -1,
                    1,
                )
                angle_col_cone = abs(np.arcsin(sin_half_col_cone_theta)) * 2

                if functional_scenario.dangerous_head_on_sector_of(ts, os):
                    bearing_map[(os.id, ts.id)] = (
                        0.0,
                        max(angle_col_cone, BOW_ANGLE),
                        0,
                        2 * np.pi,
                    )

        return {}, {}, vis_distance_map, bearing_map

    @classmethod
    def algorithm_desc(cls) -> str:
        return "Two_Step_CD_Rejection_Sampling"


class TwoStepRejectionSampling(RejectionSamplingPipeline):
    def __init__(self, verbose: bool) -> None:
        super().__init__(verbose)

    def _provide_region_maps(
        self,
        os_id: int,
        ts_ids: List[int],
        obst_ids: List[int],
        length_map: dict,
        radius_map: dict,
        functional_scenario: Optional[FunctionalScenario] = None,
    ) -> Tuple[dict, dict, dict, dict]:
        possible_distances_map = {}
        min_distance_map = {}

        for ts_id in ts_ids:
            distances = possible_vis_distances_by_length(length_map[os_id], length_map[ts_id])
            possible_distances_map[(os_id, ts_id)] = distances
            min_distance_map[(os_id, ts_id)] = min(distances)

        return possible_distances_map, min_distance_map, {}, {}

    @classmethod
    def algorithm_desc(cls) -> str:
        return "Two_Step_Rejection_Sampling"


class BaseRejectionSampling(RejectionSamplingPipeline):
    def __init__(self, verbose: bool) -> None:
        super().__init__(verbose)

    def _provide_region_maps(
        self,
        os_id: int,
        ts_ids: List[int],
        obst_ids: List[int],
        length_map: dict,
        radius_map: dict,
        functional_scenario: Optional[FunctionalScenario] = None,
    ) -> Tuple[dict, dict, dict, dict]:
        possible_distances_map = {}
        min_distance_map = {}

        for ts_id in ts_ids:
            distances = [
                2 * ONE_N_MILE_IN_M,
                3 * ONE_N_MILE_IN_M,
                5 * ONE_N_MILE_IN_M,
                6 * ONE_N_MILE_IN_M,
            ]
            possible_distances_map[(os_id, ts_id)] = distances
            min_distance_map[(os_id, ts_id)] = min(distances)

        return possible_distances_map, min_distance_map, {}, {}

    @classmethod
    def algorithm_desc(cls) -> str:
        return "Base_Rejection_Sampling"


class CDRejectionSampling(RejectionSamplingPipeline):
    def __init__(self, verbose: bool) -> None:
        super().__init__(verbose)

    def _provide_region_maps(
        self,
        os_id: int,
        ts_ids: List[int],
        obst_ids: List[int],
        length_map: dict,
        radius_map: dict,
        functional_scenario: Optional[FunctionalScenario] = None,
    ) -> Tuple[dict, dict, dict, dict]:
        if functional_scenario is None:
            raise ValueError("Functional scenario must be provided for TwoStepCDRejectionSampling.")

        bearing_map = {}
        possible_distances_map = {}
        min_distance_map = {}

        os = functional_scenario.os_object
        for ts in functional_scenario.ts_objects:
            distances = possible_vis_distances_by_bearing(
                functional_scenario.in_stern_sector_of_interpretation.contains((ts, os)),
                functional_scenario.in_stern_sector_of_interpretation.contains((os, ts)),
            )
            possible_distances_map[(os.id, ts.id)] = distances
            min_distance_map[(os.id, ts.id)] = min(distances)

            sin_half_col_cone_theta = np.clip(
                max(radius_map[os.id], radius_map[ts.id]) / min_distance_map[(os.id, ts.id)],
                -1,
                1,
            )
            angle_col_cone = abs(np.arcsin(sin_half_col_cone_theta)) * 2

            # heading_ego_to_ts, bearing_angle_ego_to_ts, heading_ts_to_ego, bearing_angle_ts_to_ego
            # heading_ego_to_ts: relative angle to ego heading
            # heading_ts_to_ego: relative angle to p12
            bow_angle = max(angle_col_cone, BOW_ANGLE)

            scenarios = [
                (functional_scenario.head_on(os, ts), (0.0, bow_angle, 0.0, bow_angle)),
                (
                    functional_scenario.crossing_from_port(os, ts),
                    (
                        -BEAM_ROTATION_ANGLE,
                        SIDE_ANGLE,
                        -BEAM_ROTATION_ANGLE,
                        SIDE_ANGLE,
                    ),
                ),
                (
                    functional_scenario.crossing_from_port(ts, os),
                    (
                        BEAM_ROTATION_ANGLE,
                        SIDE_ANGLE,
                        BEAM_ROTATION_ANGLE,
                        SIDE_ANGLE,
                    ),
                ),
                (
                    functional_scenario.overtaking_to_port(os, ts),
                    (
                        BEAM_ROTATION_ANGLE,
                        SIDE_ANGLE,
                        -np.pi,
                        STERN_ANGLE,
                    ),
                ),
                (
                    functional_scenario.overtaking_to_port(ts, os),
                    (
                        -np.pi,
                        STERN_ANGLE,
                        -BEAM_ROTATION_ANGLE,
                        SIDE_ANGLE,
                    ),
                ),
                (
                    functional_scenario.overtaking_to_starboard(os, ts),
                    (
                        -BEAM_ROTATION_ANGLE,
                        SIDE_ANGLE,
                        -np.pi,
                        STERN_ANGLE,
                    ),
                ),
                (
                    functional_scenario.overtaking_to_starboard(ts, os),
                    (
                        -np.pi,
                        STERN_ANGLE,
                        BEAM_ROTATION_ANGLE,
                        SIDE_ANGLE,
                    ),
                ),
            ]

            for condition, bearing in scenarios:
                if condition:
                    bearing_map[(os.id, ts.id)] = bearing

        return possible_distances_map, min_distance_map, {}, bearing_map

    @classmethod
    def algorithm_desc(cls) -> str:
        return "CD_Rejection_Sampling"
