import json
import random
import time
from datetime import datetime
from multiprocessing.synchronize import Event
from typing import Callable, Optional

import numpy as np

from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.monitor_driven_rrt_search import MonitorDrivenRRTSearch
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from concrete_level.trajectory_generation.trajectory_data import TrajectoryData
from concrete_level.trajectory_generation.trajectory_generator import TIME_STEP as DEFAULT_TIME_STEP
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from scenegems_tool.trajectory_generation.trajectory_generation_types import MqttTrajectoryGenerationTask
from utils.colregs_approximations import COLREGSConstraints
from utils.global_constants import ONE_HOUR_IN_SEC

_SEED = 1234
_MIN_PREVIEW_INTERVAL_SEC = 1.0

TrajectoryDataFactory = Callable[[Trajectories, int], TrajectoryData]


def _parse_initial_scene(scenario_content: str) -> ConcreteScene:
    data = json.loads(scenario_content)
    try:
        eval_data = EvaluationData.from_dict(data)
        if isinstance(eval_data.best_scene, ConcreteScene):
            return eval_data.best_scene
    except Exception:
        pass
    for key in ("best_scene", "scene", "initial_scene"):
        if isinstance(data.get(key), dict):
            return ConcreteScene.from_dict(data[key])
    raise ValueError("Scenario content does not contain a concrete scene.")


def _scenario_name(scenario_content: str) -> str:
    try:
        data = json.loads(scenario_content)
        name = data.get("scenario_name") or data.get("config_name")
        if isinstance(name, str) and name:
            return name
    except Exception:
        pass
    return "trajectory_generation"


def _make_trajectory_data_factory(scenario_content: str, start_time: datetime) -> TrajectoryDataFactory:
    config_name = _scenario_name(scenario_content)

    def _factory(trajectories: Trajectories, iteration: int) -> TrajectoryData:
        elapsed = (datetime.now() - start_time).total_seconds()
        return TrajectoryData(
            measurement_name="trajectory_generation",
            iter_numbers={0: iteration},
            algorithm_desc="RRTStar_algo",
            config_name=config_name,
            scene_path=None,
            random_seed=_SEED,
            timestamp=datetime.now().isoformat(),
            trajectories=trajectories,
            overall_eval_time=elapsed,
            rrt_evaluation_times={0: elapsed},
        )

    return _factory


def _build_rrt(
    task: MqttTrajectoryGenerationTask,
    initial_scene: ConcreteScene,
    other_trajectories: Trajectories,
    colregs_constants: COLREGSConstraints,
    observer: Callable[[Trajectories, int], None],
    termination_signal: Callable[[], bool],
) -> MonitorDrivenRRTSearch:
    params = task.params
    return MonitorDrivenRRTSearch(
        start_scene=initial_scene,
        other_trajectories=other_trajectories,
        colregs_constants=colregs_constants,
        observer=observer,
        termination_signal=termination_signal,
        max_iterations=params.max_iterations,
        goal_sample_rate=params.goal_sample_rate,
        best_leaf_sample_rate=params.best_leaf_sample_rate,
        max_leafs=params.max_leafs,
        anim_update_interval=params.preview_interval,
        direction_threshold=params.direction_threshold,
        best_random_nodes_k=params.best_random_nodes_k,
        verbose=False,
        show_animation=False,
    )


def _emit_result(
    result_queue,
    task: MqttTrajectoryGenerationTask,
    rrt: MonitorDrivenRRTSearch,
    factory: TrajectoryDataFactory,
) -> None:
    try:
        trajectories, iter_number = rrt.plan_trajectory()
        valid = trajectories is not None and len(trajectories) > 1
        result_queue.put((task, factory(trajectories, iter_number).to_dict(), valid, None))
        return
    except Exception as exc:
        error = str(exc)

    # Per spec: return the best partial path when the search ends without a complete one.
    try:
        partial = rrt.current_best_trajectories()
    except Exception:
        partial = None
    if partial is not None and len(partial) > 1:
        result_queue.put((task, factory(partial, rrt.iteration_count).to_dict(), True, None))
    else:
        result_queue.put((task, None, False, f"No trajectory could be planned: {error}"))


def run_trajectory_generation_worker(
    task: MqttTrajectoryGenerationTask,
    preview_queue,
    result_queue,
    terminate_event: Event,
) -> None:
    random.seed(_SEED)
    np.random.seed(_SEED)

    params = task.params
    time_step = int(params.time_step) if params.time_step else DEFAULT_TIME_STEP
    deadline: Optional[float] = None
    if params.timeout and params.timeout > 0:
        deadline = time.monotonic() + float(params.timeout)

    try:
        initial_scene = _parse_initial_scene(task.scenario_content)
        colregs_constants = COLREGSConstraints.from_file_content(task.colregs_constraints_content)
    except Exception as exc:
        result_queue.put((task, None, False, f"Failed to load scenario: {exc}"))
        return

    other_trajectories = TrajectoryBuilder.default_trajectory_from_scene(initial_scene, time_step, ONE_HOUR_IN_SEC)
    factory = _make_trajectory_data_factory(task.scenario_content, datetime.now())
    last_preview_mono = 0.0

    def _termination_signal() -> bool:
        return terminate_event.is_set() or (deadline is not None and time.monotonic() >= deadline)

    def _observer(trajectories: Trajectories, iteration: int) -> None:
        nonlocal last_preview_mono
        now = time.monotonic()
        if now - last_preview_mono < _MIN_PREVIEW_INTERVAL_SEC:
            return
        last_preview_mono = now
        preview_queue.put((task, factory(trajectories, iteration).to_dict()))

    rrt = _build_rrt(task, initial_scene, other_trajectories, colregs_constants, _observer, _termination_signal)
    _emit_result(result_queue, task, rrt, factory)
