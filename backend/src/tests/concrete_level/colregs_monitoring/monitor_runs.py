"""Monitored two-vessel runs for the monitor tests: an own ship heading east and a target that may turn."""

import math
import os
from functools import lru_cache
from typing import Callable, List, Optional, Tuple

from concrete_level.colregs_monitoring.colregs_monitor_runtime import ColregsMonitorRuntime, MonitoringTask
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredSceneWithResults
from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.vessel_stack.calibration.reference_scenarios import make_vessel
from utils.colregs_approximations import COLREGSConstraints
from utils.file_system_utils import COLREGS_CONSTANTS_FOLDER

OWN_SHIP = make_vessel(0, True)
TARGET = make_vessel(1, False)
SPEED = 8.0


@lru_cache(maxsize=1)
def constants() -> COLREGSConstraints:
    with open(os.path.join(COLREGS_CONSTANTS_FOLDER, "general_maritime_constants.yaml"), encoding="utf-8") as file:
        return COLREGSConstraints.from_file_content(file.read())


@lru_cache(maxsize=8)
def monitored_run(target_start: Tuple[float, float], steps: int, turn_at: int = -1, turn_s: int = 0) -> List[MonitoredSceneWithResults]:
    """The own ship from the origin heading east, the target from target_start heading north, both at SPEED,
    the target turning to port at 1 degree per second for turn_s seconds from turn_at. One result per second."""
    scenes = []
    target = ActorState(target_start[0], target_start[1], SPEED, math.pi / 2)
    for t in range(steps):
        scenes.append(ConcreteScene({OWN_SHIP: ActorState(SPEED * t, 0.0, SPEED, 0.0), TARGET: target}))
        heading = target.heading + (math.radians(1.0) if turn_at <= t < turn_at + turn_s else 0.0)
        target = ActorState(target.x + SPEED * math.cos(heading), target.y + SPEED * math.sin(heading), SPEED, heading)
    runtime = ColregsMonitorRuntime(constants())
    results: List[MonitoredSceneWithResults] = []
    for index, scene in enumerate(scenes):
        runtime.add_task(MonitoringTask(scene=scene, scene_timestamp=index, time_step=1))
        results.extend(runtime.monitor_current_tasks())
    return results


def scripted_run(
    own_start: ActorState,
    target_start: ActorState,
    steps: int,
    own_turn: Callable[[int], float] = lambda t: 0.0,
    target_turn: Callable[[int], float] = lambda t: 0.0,
    time_step: int = 1,
) -> List[MonitoredSceneWithResults]:
    """OWN_SHIP and TARGET from their start states, each turning by its turn(t) in radians per second
    (positive to port), at constant speed. One result per time_step seconds."""
    own, target = own_start, target_start
    runtime = ColregsMonitorRuntime(constants())
    results: List[MonitoredSceneWithResults] = []
    for index in range(steps):
        runtime.add_task(MonitoringTask(scene=ConcreteScene({OWN_SHIP: own, TARGET: target}), scene_timestamp=index * time_step, time_step=time_step))
        results.extend(runtime.monitor_current_tasks())
        for second in range(time_step):
            t = index * time_step + second
            own = _advance(own, own_turn(t))
            target = _advance(target, target_turn(t))
    return results


def _advance(state: ActorState, turn: float) -> ActorState:
    heading = state.heading + turn
    return ActorState(state.x + state.speed * math.cos(heading), state.y + state.speed * math.sin(heading), state.speed, heading)


def rule_result(monitored: MonitoredSceneWithResults, rule_number: str, subject: Optional[ConcreteActor] = None):
    """The result of the one rule with this number (and subject vessel, for a rule kept per vessel) in a two-vessel run, or None while it was never active."""
    found = [
        value
        for results in monitored.monitor_result_map_set.values()
        for rule, value in results.items()
        if rule.rule_number == rule_number and (subject is None or rule.subject_actor_id == subject.id)
    ]
    assert len(found) <= 1, found
    return found[0] if found else None
