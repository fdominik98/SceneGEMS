import time
from copy import deepcopy
from datetime import datetime
from multiprocessing.synchronize import Event
from typing import List

from concrete_level.trajectory_generation.scene_builder import SceneBuilder
from functional_level.models.model_parser import ModelParser
from logical_level.constraint_satisfaction.aggregates import Aggregate, AggregateAll
from logical_level.constraint_satisfaction.assignments import Assignments
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from logical_level.constraint_satisfaction.rejection_sampling.rejection_sampling_pipeline import TwoStepCDRejectionSampling
from logical_level.mapping.instance_initializer import RandomInstanceInitializer
from logical_level.mapping.logical_scenario_builder import LogicalScenarioBuilder
from logical_level.mapping.static_obstacle import StaticObstacleTypeMap
from logical_level.mapping.vessel_type import VesselTypeMap
from scenegems_tool.scenario_generation.scenario_generation_types import MqttSceneGenerationTask
from utils.colregs_approximations import COLREGSConstraints

_MSR_CDRS_PS = "rs-msr"


def run_scene_generation_worker(
    task: MqttSceneGenerationTask,
    generated_scene_queue,
    terminate_event: Event,
) -> None:
    colregs_constants = COLREGSConstraints.from_file_content(task.colregs_constraints_content)
    vessel_type_map = VesselTypeMap(task.vessel_types_content)
    obstacle_type_map = StaticObstacleTypeMap(task.obstacle_types_content)
    functional_scenario = ModelParser.parse_problem(task.functional_scenario_content)

    logical_scenario = LogicalScenarioBuilder.build_from_functional(functional_scenario, vessel_type_map, obstacle_type_map, colregs_constants, RandomInstanceInitializer.name)
    aggregate = Aggregate.factory(logical_scenario, AggregateAll.name, minimize=True)
    config = EvaluationData(
        timeout=task.timeout,
        init_method=RandomInstanceInitializer.name,
        random_seed=1234,
        algorithm_desc=TwoStepCDRejectionSampling.algorithm_desc(),
        config_group=_MSR_CDRS_PS,
        vessel_number=logical_scenario.vessel_number,
        obstacle_number=logical_scenario.obstacle_number,
        measurement_name=task.request_id,
        scenario_name=logical_scenario.name,
        timestamp=datetime.now().isoformat(),
        population_size=1,
        aggregate_strat=aggregate.name,
    )

    last_observer_publish_mono: float = 0.0

    def _publish_generated_scene(solution: List[float], number_of_generations: int, runtime: float) -> None:
        eval_data = deepcopy(config)
        assignments = Assignments(logical_scenario.actor_variables).update_from_individual(solution)
        eval_data.best_scene = SceneBuilder().build_from_assignments(assignments)
        eval_data.number_of_generations = number_of_generations
        penalty = aggregate.derive_penalty(solution)
        eval_data.best_fitness = aggregate.evaluate(solution)
        eval_data.best_fitness_index = penalty.value
        eval_data.evaluation_time = runtime if eval_data.is_valid else eval_data.timeout
        generated_scene_queue.put((task, eval_data))

    def _termination_signal() -> bool:
        return terminate_event.is_set()

    def _observer(solution: List[float], number_of_generations: int, runtime: float) -> None:
        nonlocal last_observer_publish_mono
        now = time.monotonic()
        if now - last_observer_publish_mono < 1.0:
            return
        last_observer_publish_mono = now
        _publish_generated_scene(solution, number_of_generations, runtime)

    solver = TwoStepCDRejectionSampling(verbose=False, observer=_observer, termination_signal=_termination_signal)
    some_results = solver.evaluate(
        (aggregate, logical_scenario, functional_scenario, logical_scenario.get_population(1)[0]),
        config,
    )
    if not terminate_event.is_set():
        _publish_generated_scene(some_results[0], some_results[1], some_results[2])
