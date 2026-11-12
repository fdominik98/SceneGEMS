"""The COLREGS monitor of a simulation that is judged while it runs (monitor: live).

The simulation job's runners feed it from their step observers with the scene of each step and report its
summary in the post-hoc result shape (subsystems/monitoring/rule_outcomes.py). The monitor itself is not here:
the run's scenes are one series of the worker node's monitoring subsystem, which judges them in time order
(PooledSeries, pooled_series.py). The run sends its scenes in batches and does not wait for them; it waits only
where it needs an answer: at every step of a run that ends early once every rule is decided, for the frame of a
step somebody observes, and at the end for the verdict.

A run that was given no monitoring subsystem (a test) judges its series with the same
monitor in process (InProcessSeries); the outcomes are the same either way.
"""

from enum import Enum
from typing import Any, Dict, Optional, Protocol

from scenegems_tool.cluster.protocol.jobs import JobSpec


class SimulationMonitor(str, Enum):
    NONE = "none"  # no monitor in the run; a post-hoc or empty monitor may follow
    LIVE = "live"  # the COLREGS monitor judges the run's scenes while it runs


class Series(Protocol):
    """A run's series of scenes as its monitor sees it: scenes in, in time order; answers out when the run asks."""

    def add(self, scene: Any) -> None: ...

    def every_rule_decided(self) -> bool:
        """Whether every rule has its final outcome after the scenes added so far."""

    def latest_frame(self) -> Optional[Dict[str, Any]]:
        """The monitored frame of the scene added last, None when it can no longer be had."""

    def close(self) -> Dict[str, Any]:
        """End the series: scenes, monitored_scenes, time_step and the rule outcomes' summary."""

    def abandon(self) -> None:
        """The run is over without a verdict: free what the series holds."""


class InProcessSeries:
    """The series judged by the monitor of the monitoring subsystem's worker, in this process."""

    def __init__(self, scenario_id: str, time_step: int, colregs_constraints_content: Optional[str]):
        from scenegems_tool.subsystems.monitoring.monitoring_worker import SeriesMonitor

        self._monitor = SeriesMonitor(scenario_id, time_step, colregs_constraints_content)
        self._frame: Optional[Dict[str, Any]] = None

    def add(self, scene: Any) -> None:
        frames = self._monitor.add([scene], frames_wanted=True)
        self._frame = frames[-1] if frames else None

    def every_rule_decided(self) -> bool:
        return self._monitor.every_rule_decided

    def latest_frame(self) -> Optional[Dict[str, Any]]:
        return self._frame

    def close(self) -> Dict[str, Any]:
        return {"scenes": self._monitor.scenes, "monitored_scenes": self._monitor.monitored_scenes, "time_step": self._monitor.time_step, **self._monitor.summary()}

    def abandon(self) -> None:
        pass


def series_of_run(job: Optional[JobSpec], time_step: int, colregs_constraints_content: Optional[str]) -> Series:
    """The series of a run: in the monitoring subsystem this process was told of (MONITORING_POOL_VARIABLE), else in process."""
    from scenegems_tool.subsystems.monitoring.monitoring_types import monitoring_pool_from_environment

    scenario_id = job.job_id if job is not None else "live"
    pool = monitoring_pool_from_environment()
    if pool is None or job is None:
        return InProcessSeries(scenario_id, time_step, colregs_constraints_content)
    from scenegems_tool.cluster.worker_node.jobs.pooled_series import pooled_series_of

    return pooled_series_of(pool, job, time_step, colregs_constraints_content)


class LiveMonitor:
    """The run's side of its series: fed by the run's step observer, asked for frames by the observation, and for the result at the end."""

    def __init__(self, actors, time_step: int, colregs_constraints_content: Optional[str], early_stop: bool, job: Optional[JobSpec] = None, series: Optional[Series] = None):
        self.actors = tuple(actors)
        self.time_step = time_step
        self.early_stop = early_stop
        self.series: Series = series if series is not None else series_of_run(job, time_step, colregs_constraints_content)
        self.scenes = 0
        self.decided_at: Optional[int] = None  # scenario time at which every rule was decided, with early_stop
        self._latest_index: Optional[int] = None
        self._verdict: Optional[Dict[str, Any]] = None

    def on_step(self, index: int, states) -> bool:
        """Hand a step's states (one per actor, in `actors` order) to the series; true when early_stop ends the run."""
        from concrete_level.trajectory_generation.scene_builder import SceneBuilder

        builder = SceneBuilder()
        builder.set_states_as_dict(dict(zip(self.actors, states)))  # the scene the run's trajectories hold for this step
        self.series.add(builder.build())
        self.scenes += 1
        self._latest_index = index
        if self.early_stop and self.series.every_rule_decided():
            self.decided_at = index * self.time_step
            return True
        return False

    def frame_of(self, index: int) -> Optional[Dict[str, Any]]:
        """The monitored frame of the step, for the run's observers; None when the step is not the one judged last (the frame is then the scene alone)."""
        if index != self._latest_index:
            return None
        frame = self.series.latest_frame()
        if frame is None:
            return None
        return {**frame, "timestamp": index * self.time_step}  # the run's own time of the step

    def result(self, stopped_early: bool) -> Dict[str, Any]:
        """The post-hoc result shape, plus the scenario time the run stopped at when the monitor ended it early. Ends the series."""
        if self._verdict is None:
            self._verdict = self.series.close()
        return {**self._verdict, "time_step": self.time_step, "stopped_early_at": self.decided_at if stopped_early else None}

    def abandon(self) -> None:
        """The run ended without its result: the series is given up."""
        if self._verdict is None:
            self.series.abandon()
