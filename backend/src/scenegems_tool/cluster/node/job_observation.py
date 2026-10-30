"""A running job's observation on the node: the master's latest Observe and the frames its run produced.

The lease manager opens one per accepted job in NodeContext.observations and closes it when
the job's worker stops. The master's Observe sets the request (request); the job's stack
(launchers/per_job/job_stack.py) passes every change into its runner container and hands the
frames the runner writes back to add_frames. The daemon's relay takes them out in batches
(take_batch) for ObservationFrames:

- at most one batch per min_interval_s and job (about 10 a second);
- at most MAX_OBSERVATION_FRAMES frames and MAX_OBSERVATION_BATCH_BYTES bytes of frame JSON
  per batch, so a batch stays far below the control link's 64 MiB; a single larger frame is dropped;
- at most max_buffered frames wait while the master is unreachable; older ones are dropped.

Only simulations are observable (OBSERVABLE_JOB_TYPES); other jobs get no observation, and
an Observe about them is ignored. Frames that arrive while the job is not observed are dropped, and an Observe off drops the
waiting ones, so nothing is sent for a job nobody observes. The time spent observed is
counted (observed_seconds): an observed run is paced, so the job's timeout leaves it out.
"""

import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, Iterable, List, Optional, Tuple

from scenegems_tool.cluster.node.launchers.per_job.job_container_io import ObservationControl
from scenegems_tool.cluster.protocol.jobs import JobSpec, JobType
from scenegems_tool.cluster.protocol.messages import MAX_OBSERVATION_BATCH_BYTES, MAX_OBSERVATION_FRAMES

OBSERVABLE_JOB_TYPES = (JobType.SIMULATION_KINEMATIC, JobType.SIMULATION_ARDUPILOT_SIM, JobType.SIMULATION_GAZEBO)
BATCH_INTERVAL_S = 0.1
MAX_BUFFERED_FRAMES = 1000

SizedFrame = Tuple[dict, int]  # a frame and the length of its JSON text


class JobObservation:
    def __init__(
        self,
        job_id: str,
        attempt: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        min_interval_s: float = BATCH_INTERVAL_S,
        max_frames: int = MAX_OBSERVATION_FRAMES,
        max_bytes: int = MAX_OBSERVATION_BATCH_BYTES,
        max_buffered: int = MAX_BUFFERED_FRAMES,
    ):
        self.job_id = job_id
        self.attempt = attempt
        self._clock = clock
        self._min_interval_s = min_interval_s
        self._max_frames = max_frames
        self._max_bytes = max_bytes
        self._changed = threading.Condition()
        self._control = ObservationControl()
        self._frames: Deque[SizedFrame] = deque()
        self._max_buffered = max_buffered
        self._seq = 0
        self._last_batch_at: Optional[float] = None
        self._observed_since: Optional[float] = None
        self._observed_s = 0.0
        self.dropped = 0  # frames dropped: too large, or the buffer was full
        self.closed = False

    # The master's request

    def request(self, active: bool, speed: float) -> bool:
        """Observe's on or off and speed; True when it changed what the runner is asked."""
        with self._changed:
            if self.closed or (active, speed) == (self._control.active, self._control.speed) or (not active and not self._control.active):
                return False
            now = self._clock()
            if active and self._observed_since is None:
                self._observed_since = now
            elif not active:
                self._observed_s += now - self._observed_since
                self._observed_since = None
                self._frames.clear()
            self._control = ObservationControl(active=active, speed=speed if active else self._control.speed, revision=self._control.revision + 1)
            self._changed.notify_all()
            return True

    @property
    def control(self) -> ObservationControl:
        with self._changed:
            return self._control

    @property
    def active(self) -> bool:
        return self.control.active

    def wait_for_change(self, revision: int, timeout_s: float) -> ObservationControl:
        """The request once its revision differs from revision, or as it is after timeout_s or the close."""
        with self._changed:
            self._changed.wait_for(lambda: self._control.revision != revision or self.closed, timeout=timeout_s)
            return self._control

    def observed_seconds(self) -> float:
        with self._changed:
            current = self._clock() - self._observed_since if self._observed_since is not None else 0.0
            return self._observed_s + current

    # Frames

    def add_frames(self, frames: Iterable[SizedFrame]) -> None:
        with self._changed:
            if self.closed or not self._control.active:
                return
            for frame, size in frames:
                if size > self._max_bytes:
                    self.dropped += 1
                    continue
                if len(self._frames) >= self._max_buffered:
                    self._frames.popleft()
                    self.dropped += 1
                self._frames.append((frame, size))

    def take_batch(self, force: bool = False) -> Optional[Tuple[int, List[dict]]]:
        """(seq, frames) of the next batch when one is due; with force regardless of the interval (the job ended)."""
        with self._changed:
            if not self._frames:
                return None
            now = self._clock()
            if not force and self._last_batch_at is not None and now - self._last_batch_at < self._min_interval_s:
                return None
            batch: List[dict] = []
            size = 0
            while self._frames and len(batch) < self._max_frames and size + self._frames[0][1] <= self._max_bytes:
                frame, frame_size = self._frames.popleft()
                batch.append(frame)
                size += frame_size
            self._seq += 1
            self._last_batch_at = now
            return self._seq, batch

    def close(self) -> None:
        with self._changed:
            if self._observed_since is not None:
                self._observed_s += self._clock() - self._observed_since
                self._observed_since = None
            self.closed = True
            self._changed.notify_all()


class JobObservations:
    """The node's open observations, one per running job attempt (NodeContext.observations)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._open: Dict[Tuple[str, int], JobObservation] = {}

    def open(self, job: JobSpec) -> Optional[JobObservation]:
        """The job's observation, opened on the first call; None for a job type that is not observable."""
        if job.job_type not in OBSERVABLE_JOB_TYPES:
            return None
        with self._lock:
            key = (job.job_id, job.attempt)
            observation = self._open.get(key)
            if observation is None:
                observation = self._open[key] = JobObservation(job.job_id, job.attempt, clock=self._clock)
            return observation

    def get(self, job_id: str, attempt: int) -> Optional[JobObservation]:
        with self._lock:
            return self._open.get((job_id, attempt))

    def of(self, job: JobSpec) -> Optional[JobObservation]:
        return self.get(job.job_id, job.attempt)

    def close(self, job: JobSpec) -> Optional[JobObservation]:
        with self._lock:
            observation = self._open.pop((job.job_id, job.attempt), None)
        if observation is not None:
            observation.close()
        return observation

    def __len__(self) -> int:
        with self._lock:
            return len(self._open)
