"""The runner's side of live observation: the request from the job folder, pacing, and frames on stdout.

The worker node copies the control node's request into the job folder (OBSERVE_DOCUMENT, see
launchers/per_job/job_container_io.py); the runner has no network. A run's step observer
(RunObserver.step, called after every step) reads the request at most every
check_interval_s, and while it is active:

- pacing (kinematic runs): the run sleeps so that scenario time advances at speed times wall
  time from the step the observation started or last changed at. A run that falls behind
  (more than max_lag_s) is not hurried: the pace starts again from where it is. Sleeps are cut
  into slices of check_interval_s, so a stop or another speed takes effect within one slice.
- frames: one frame every stride steps (frame_stride), so at most max_frames_per_s frames a
  second are written whatever the speed, plus the run's last step. Each is one stdout line.

An observation that starts mid-run picks up at the current step. The observer only reads the
run's states, so the run, its digest and its result are the same whether or not it was
observed; only its wall time changes.
"""

import json
import math
import sys
import time
from typing import Any, Callable, Optional, TextIO

from scenegems_tool.cluster.worker_node.jobs.in_container.json_values import json_safe
from scenegems_tool.cluster.worker_node.launchers.per_job.job_container_io import JOB_FOLDER, OBSERVE_DOCUMENT, ObservationControl, format_frame_line

CHECK_INTERVAL_S = 0.25
MAX_FRAMES_PER_S = 20.0
MAX_LAG_S = 1.0

Clock = Callable[[], float]
Sleep = Callable[[float], None]
BuildFrame = Callable[[int, Any], dict]  # (step index, the step's states) to a frame in the workbench's wire format


def frame_stride(speed: float, dt: float, max_frames_per_s: float = MAX_FRAMES_PER_S) -> int:
    """Steps between two frames, so that a run at speed times real time writes at most max_frames_per_s frames a second."""
    steps_per_s = speed / dt
    return max(1, math.ceil(steps_per_s / max_frames_per_s - 1e-9))


class ControlFile:
    """The request in the job folder, read at most every check_interval_s; an unreadable or partly copied file keeps the last one."""

    def __init__(self, path: str, clock: Clock = time.monotonic, check_interval_s: float = CHECK_INTERVAL_S):
        self.path = path
        self._clock = clock
        self._check_interval_s = check_interval_s
        self._checked_at: Optional[float] = None
        self._control = ObservationControl()
        self.reads = 0

    def __call__(self) -> ObservationControl:
        now = self._clock()
        if self._checked_at is not None and now - self._checked_at < self._check_interval_s:
            return self._control
        self._checked_at = now
        try:
            with open(self.path, encoding="utf-8") as file:
                text = file.read()
        except OSError:
            return self._control  # not observed yet
        self.reads += 1
        try:
            self._control = ObservationControl.from_document(text)
        except ValueError:
            pass  # a copy in progress: the next check reads it
        return self._control


class Pacer:
    """How long a step waits so scenario time follows speed times wall time from an anchor step."""

    def __init__(self, clock: Clock = time.monotonic, max_lag_s: float = MAX_LAG_S):
        self._clock = clock
        self._max_lag_s = max_lag_s
        self._anchor: Optional[tuple] = None  # (wall time, scenario time, speed)

    def reset(self) -> None:
        self._anchor = None

    def delay(self, scenario_time_s: float, speed: float) -> float:
        now = self._clock()
        if self._anchor is None or self._anchor[2] != speed:
            self._anchor = (now, scenario_time_s, speed)
            return 0.0
        anchor_wall, anchor_scenario, _ = self._anchor
        due = anchor_wall + (scenario_time_s - anchor_scenario) / speed
        if due > now:
            return due - now
        if now - due > self._max_lag_s:
            self._anchor = (now, scenario_time_s, speed)  # behind: go on at the speed from here instead of racing to catch up
        return 0.0


class RunObserver:
    """The step observer of an observable run (see the module docstring)."""

    def __init__(
        self,
        control: Callable[[], ObservationControl],
        write_frame: Callable[[dict], None],
        build_frame: BuildFrame,
        dt: float,
        *,
        last_index: Optional[int] = None,
        pace: bool = True,
        stride_speed: Optional[float] = None,
        clock: Clock = time.monotonic,
        sleep: Sleep = time.sleep,
        max_frames_per_s: float = MAX_FRAMES_PER_S,
        check_interval_s: float = CHECK_INTERVAL_S,
    ):
        self._control = control
        self._write_frame = write_frame
        self._build_frame = build_frame
        self._dt = dt
        self._last_index = last_index
        self._pace = pace
        self._stride_speed = stride_speed  # the run's own pace when it is not paced (ArduPilot's speedup)
        self._sleep = sleep
        self._max_frames_per_s = max_frames_per_s
        self._check_interval_s = check_interval_s
        self._pacer = Pacer(clock)
        self._speed: Optional[float] = None  # while observing
        self._last_frame: Optional[int] = None
        self.frames_written = 0
        self.slept_s = 0.0

    def step(self, index: int, states: Any, last: bool = False) -> None:
        """After a step; last says the run ends with it (an early stop), which writes its frame too."""
        control = self._control()
        if not control.active:
            self._speed = None
            return
        if self._speed != control.speed:  # started, or another speed: pick up from this step
            self._speed = control.speed
            self._last_frame = None
            self._pacer.reset()
        if self._pace and not self._wait(index * self._dt):
            return  # the observation ended during the wait
        stride = frame_stride(self._stride_speed or self._speed, self._dt, self._max_frames_per_s)
        if self._last_frame is None or index - self._last_frame >= stride or index == self._last_index or last:
            self._write_frame(self._build_frame(index, states))
            self._last_frame = index
            self.frames_written += 1

    def _wait(self, scenario_time_s: float) -> bool:
        """Sleeps until the step is due; False when the observation ended meanwhile (a new speed ends the wait too)."""
        speed = self._speed
        remaining = self._pacer.delay(scenario_time_s, speed)
        while remaining > 0.0:
            pause = min(remaining, self._check_interval_s)
            self._sleep(pause)
            self.slept_s += pause
            control = self._control()
            if not control.active:
                self._speed = None
                return False
            if control.speed != speed:
                return True  # the next step picks the new speed up
            remaining = self._pacer.delay(scenario_time_s, speed)
        return True


class ContainerObservation:
    """A runner container's observation: the request from its job folder, frames to its stdout."""

    def __init__(self, folder: str = JOB_FOLDER, out: Optional[TextIO] = None, clock: Clock = time.monotonic, sleep: Sleep = time.sleep):
        self.control = ControlFile(f"{folder}/{OBSERVE_DOCUMENT}", clock)
        self._out = out
        self._clock = clock
        self._sleep = sleep

    def now(self) -> float:
        """The observation's clock, for what a waiting run does from time to time."""
        return self._clock()

    def wait_for_start(self, timeout_s: float, while_waiting: Optional[Callable[[], None]] = None, poll_s: float = CHECK_INTERVAL_S) -> bool:
        """Waits for the operator's Start of an attended run; False when it does not come within timeout_s.

        while_waiting runs between two looks at the request, for what the run shows before it starts.
        """
        deadline = self._clock() + timeout_s
        while not self.control().started:
            if self._clock() >= deadline:
                return False
            if while_waiting is not None:
                while_waiting()
            self._sleep(poll_s)
        return True

    def write_frame(self, frame: dict) -> None:
        out = self._out or sys.stdout
        out.write(format_frame_line(json.dumps(json_safe(frame), separators=(",", ":"), allow_nan=False)) + "\n")
        out.flush()

    def observer(self, build_frame: BuildFrame, dt: float, *, last_index: Optional[int] = None, pace: bool = True, stride_speed: Optional[float] = None) -> RunObserver:
        return RunObserver(self.control, self.write_frame, build_frame, dt, last_index=last_index, pace=pace, stride_speed=stride_speed, clock=self._clock, sleep=self._sleep)
