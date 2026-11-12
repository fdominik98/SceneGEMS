"""The worker of a monitoring task: it judges one series of scenes against COLREGS as the scenes arrive.

A monitor-scenario request names the scenario, its time step and its COLREGS constants; the scenes follow as
scenes signals, batch by batch in time order, and a close signal ends the series (monitoring_types.py). The
worker keeps the series' monitor and its rule outcomes from the first scene to the last, so a rule is judged
over the whole series. For every batch it emits how far the series is, whether every rule has its final
outcome, and the monitored frames when the request or the batch itself asks for them (a batch's own "frames"
wins: a run that is judged while it runs asks only for the batches somebody watches);
once every rule has its final outcome it says so in its progress, so a requester that produces the scenes may
stop; at the close it emits the verdict.

A batch that does not follow the last one fails the series: the monitor only takes the scene after the last.
A batch delivered twice is taken once. A series that gets no signal for the idle limit fails, so a requester
that is gone holds no place in the pool.

SeriesMonitor is the monitor of a series on its own, for whoever judges in process.
"""

import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from concrete_level.colregs_monitoring.colregs_monitor_runtime import ColregsMonitorRuntime, MonitoringTask
from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.gateway.serialization import serialize_monitored_frame
from scenegems_tool.subsystems.monitoring.monitoring_types import CLOSE_SIGNAL, MONITOR_RESULT_STREAM, MONITORED_SCENE_STREAM, SCENES_SIGNAL, SERIES_IDLE_LIMIT_S, MonitorScenarioTask
from scenegems_tool.subsystems.monitoring.rule_outcomes import RuleOutcomes
from utils.colregs_approximations import COLREGSConstraints

SIGNAL_WAIT_S = 0.2  # how long the worker waits for a signal before it looks at its cancel flag and its idle time again


class SeriesError(Exception):
    """A series the monitor cannot judge: its batches do not follow each other, or its requester is gone."""


class SeriesMonitor:
    """The monitor of one series: scenes in, in time order; frames and rule outcomes out."""

    def __init__(self, scenario_id: str, time_step: int, colregs_constraints_content: Optional[str] = None, include_frames: bool = False):
        constants = COLREGSConstraints.from_file_content(colregs_constraints_content) if colregs_constraints_content else COLREGSConstraints.default_general_maritime()
        self.scenario_id = scenario_id
        self.time_step = time_step
        self.include_frames = include_frames
        self.scenes = 0
        self._runtime = ColregsMonitorRuntime(constants)
        self._outcomes = RuleOutcomes()

    @property
    def next_timestamp(self) -> int:
        """The timestamp the next scene of the series gets."""
        return self.scenes * self.time_step

    @property
    def monitored_scenes(self) -> int:
        return self._outcomes.monitored_scenes

    @property
    def every_rule_decided(self) -> bool:
        return self._outcomes.every_rule_decided()

    def add(self, scenes: Sequence[ConcreteScene], frames_wanted: Optional[bool] = None) -> List[Dict[str, Any]]:
        """Judge the next scenes of the series; returns their monitored frames when they are wanted: frames_wanted, or what the series was asked for when None."""
        include_frames = self.include_frames if frames_wanted is None else frames_wanted
        frames: List[Dict[str, Any]] = []
        for scene in scenes:
            self._runtime.add_task(MonitoringTask(scene=scene, scene_timestamp=self.next_timestamp, time_step=self.time_step))
            self.scenes += 1
            for monitored_scene in self._runtime.monitor_current_tasks():
                self._outcomes.add(monitored_scene)
                if include_frames:
                    frames.append(serialize_monitored_frame(scenario_id=self.scenario_id, monitored_scene=monitored_scene, timestamp=monitored_scene.timestamp, time_step=self.time_step))
        return frames

    def summary(self) -> Dict[str, Any]:
        """The rule outcomes so far (rule_outcomes.py)."""
        return self._outcomes.summary()


class _FollowedSeries:
    """The series of a task as its worker follows it: its monitor, the batches it took, and whether it advised to stop."""

    def __init__(self, task: MonitorScenarioTask, channel: Any):
        self.monitor = SeriesMonitor(task.scenario_id, task.time_step, task.colregs_constraints_content, task.include_frames)
        self.channel = channel
        self.batches = 0
        self.stop_advised = False

    def take(self, data: Mapping[str, Any]) -> None:
        """Judge the batch of a scenes signal and say how far the series is; a batch out of order fails the series."""
        monitor = self.monitor
        index = int(data["index"])
        if index < self.batches:
            return  # the broker delivered the batch a second time
        if index > self.batches:
            raise SeriesError(f"batch {index} arrived before batch {self.batches}")
        first_timestamp = int(data.get("first-timestamp", monitor.next_timestamp))
        if first_timestamp != monitor.next_timestamp:
            raise SeriesError(f"batch {index} starts at {first_timestamp}, but the series is at {monitor.next_timestamp}")
        frames_wanted = data.get("frames")
        frames = monitor.add([ConcreteScene.from_dict(scene) for scene in data["scenes"]], None if frames_wanted is None else bool(frames_wanted))
        self.batches += 1
        message = {"index": index, "monitored-scenes": monitor.monitored_scenes, "every-rule-decided": bool(monitor.every_rule_decided), "monitored-frames": frames}
        self.channel.emit(MONITORED_SCENE_STREAM, message)
        if not self.stop_advised and monitor.every_rule_decided:
            self.stop_advised = True
            self.channel.progress("every rule is decided", None, {"stop-advised": True, "decided-at": monitor.next_timestamp - monitor.time_step})

    def close(self, data: Mapping[str, Any]) -> None:
        """Emit the verdict of the closed series; a series closed before all its batches arrived fails."""
        announced = data.get("batches")
        if announced is not None and int(announced) != self.batches:
            raise SeriesError(f"the series was closed after {self.batches} of its {int(announced)} batches")
        monitor = self.monitor
        result = {"scenes": monitor.scenes, "monitored-scenes": monitor.monitored_scenes, "time-step": monitor.time_step, "batches": self.batches, "summary": monitor.summary()}
        self.channel.emit(MONITOR_RESULT_STREAM, result, final=True)


def monitor_series(task: MonitorScenarioTask, channel: Any, idle_limit_s: float = SERIES_IDLE_LIMIT_S, clock: Callable[[], float] = time.monotonic) -> None:
    """Judge the task's series from its signals until it is closed or cancelled; SeriesError for a series that cannot be judged."""
    series = _FollowedSeries(task, channel)
    last_signal = clock()
    while not channel.cancelled:
        signal = channel.next_signal(SIGNAL_WAIT_S)
        if signal is None:
            if clock() - last_signal > idle_limit_s:
                raise SeriesError(f"the series got no scenes for {idle_limit_s:g} s and was not closed")
            continue
        last_signal = clock()
        if signal.name == CLOSE_SIGNAL:
            series.close(signal.data or {})
            return
        if signal.name == SCENES_SIGNAL:
            series.take(signal.data or {})


def run_monitoring_worker(task: MonitorScenarioTask, channel: Any) -> None:
    """What a worker process of the monitoring pool runs for a task."""
    monitor_series(task, channel)
