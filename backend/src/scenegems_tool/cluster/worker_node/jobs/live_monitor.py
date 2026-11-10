"""The COLREGS monitor inside a simulation job, judging the run step by step (monitor: live).

The simulation job's runners (kinematic, ardupilot) feed it from their step
observers with the scene of each step, as monitoring.post_hoc feeds it scene by scene, and report its summary in the
post-hoc result shape (subsystems/monitoring/rule_outcomes.py).
"""

from enum import Enum
from typing import Any, Dict, Optional


class SimulationMonitor(str, Enum):
    NONE = "none"  # no monitor in the run; a post-hoc or empty monitor may follow
    LIVE = "live"  # the COLREGS monitor in process, step by step


class LiveMonitor:
    """The COLREGS monitor fed by the run's step observer, as monitoring.post_hoc feeds it scene by scene."""

    def __init__(self, actors, time_step: int, colregs_constraints_content: Optional[str], early_stop: bool):
        from concrete_level.colregs_monitoring.colregs_monitor_runtime import ColregsMonitorRuntime
        from scenegems_tool.subsystems.monitoring.rule_outcomes import RuleOutcomes
        from utils.colregs_approximations import COLREGSConstraints

        constants = COLREGSConstraints.from_file_content(colregs_constraints_content) if colregs_constraints_content else COLREGSConstraints.default_general_maritime()
        self.actors = tuple(actors)
        self.time_step = time_step
        self.early_stop = early_stop
        self.runtime = ColregsMonitorRuntime(constants)
        self.outcomes = RuleOutcomes()
        self.scenes = 0
        self.decided_at: Optional[int] = None  # scenario time at which every rule was decided, with early_stop
        self.last_monitored: Any = None  # the latest MonitoredSceneWithResults, for the frames of an observed run
        self.last_monitored_index: Optional[int] = None

    def on_step(self, index: int, states) -> bool:
        """Judge a step's states (one per actor, in `actors` order); true when early_stop ends the run."""
        from concrete_level.colregs_monitoring.colregs_monitor_runtime import MonitoringTask
        from concrete_level.trajectory_generation.scene_builder import SceneBuilder

        builder = SceneBuilder()
        builder.set_states_as_dict(dict(zip(self.actors, states)))  # the scene the run's trajectories hold for this step
        self.runtime.add_task(MonitoringTask(scene=builder.build(), scene_timestamp=index * self.time_step, time_step=self.time_step))
        self.scenes += 1
        for monitored_scene in self.runtime.monitor_current_tasks():
            self.outcomes.add(monitored_scene)
            self.last_monitored, self.last_monitored_index = monitored_scene, index
        if self.early_stop and self.outcomes.every_rule_decided():
            self.decided_at = index * self.time_step
            return True
        return False

    def result(self, stopped_early: bool) -> Dict[str, Any]:
        """The post-hoc result shape, plus the scenario time the run stopped at when the monitor ended it early."""
        return {
            "scenes": self.scenes,
            "monitored_scenes": self.outcomes.monitored_scenes,
            "time_step": self.time_step,
            **self.outcomes.summary(),
            "stopped_early_at": self.decided_at if stopped_early else None,
        }
