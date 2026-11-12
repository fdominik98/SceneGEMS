"""A running job's report calls, turned into JobStatus and LogLines frames, batched and rate limited.

run_job calls `status` and `log` from the job's threads as often as the job likes. The
batcher keeps the latest status and a bounded buffer of log lines; the daemon's ticker
takes frames from it a few times a second while connected:

- at most one JobStatus per `status_interval_s`, carrying the newest status;
- log lines in LogLines frames of up to `max_lines_per_frame`;
- at most `lines_per_second` log lines per job on average (token bucket with a burst of
  `burst_lines`); lines over the budget, and the oldest lines when the buffer is full
  during a disconnect, are dropped and counted in one daemon line.

The final flush (`force`) sends whatever is left before the job's result.
"""

import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from scenegems_tool.cluster.protocol.messages import JobStatus, LogLine, LogLines, LogStream
from scenegems_tool.cluster.protocol.model_base import ProtocolFrame

DAEMON_SOURCE = "worker-node-daemon"
MAX_LINE_CHARACTERS = 4000


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ReportBatcher:
    def __init__(
        self,
        lease_id: str,
        job_id: str,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = _utc_now,
        status_interval_s: float = 0.5,
        max_lines_per_frame: int = 200,
        lines_per_second: float = 100.0,
        burst_lines: int = 500,
        max_buffered_lines: int = 5000,
    ):
        self.lease_id = lease_id
        self.job_id = job_id
        self._clock = clock
        self._wall_clock = wall_clock
        self._status_interval_s = status_interval_s
        self._max_lines_per_frame = max_lines_per_frame
        self._lines_per_second = lines_per_second
        self._burst_lines = burst_lines
        self._lock = threading.Lock()
        self._lines: Deque[LogLine] = deque(maxlen=max_buffered_lines)
        self._status: Optional[Tuple[str, Optional[float], Optional[Dict[str, Any]]]] = None
        self._status_dirty = False
        self._status_sent_at: Optional[float] = None
        self._tokens = float(burst_lines)
        self._tokens_at = clock()
        self._dropped_by_rate = 0
        self._dropped_by_buffer = 0

    # JobReport

    def status(self, message: str, progress: Optional[float] = None, detail: Optional[Dict[str, Any]] = None) -> None:
        if progress is not None:
            progress = min(1.0, max(0.0, float(progress)))
        with self._lock:
            self._status = (str(message)[:MAX_LINE_CHARACTERS], progress, dict(detail) if detail else None)
            self._status_dirty = True

    def log(self, source: str, text: str, stream: LogStream = LogStream.STDOUT) -> None:
        with self._lock:
            if not self._take_token():
                self._dropped_by_rate += 1
                return
            self._append(LogLine(timestamp=self._wall_clock(), stream=stream, source=source, text=str(text)[:MAX_LINE_CHARACTERS]))

    def daemon_line(self, text: str) -> None:
        """A line of the daemon about this job; not rate limited."""
        with self._lock:
            self._append(LogLine(timestamp=self._wall_clock(), stream=LogStream.DAEMON, source=DAEMON_SOURCE, text=text[:MAX_LINE_CHARACTERS]))

    # Frames

    def take_frames(self, force: bool = False) -> List[ProtocolFrame]:
        """The frames due now; with force everything pending, as before the job's result."""
        now = self._clock()
        frames: List[ProtocolFrame] = []
        with self._lock:
            if self._status_dirty and (force or self._status_sent_at is None or now - self._status_sent_at >= self._status_interval_s):
                message, progress, detail = self._status
                frames.append(JobStatus(lease_id=self.lease_id, job_id=self.job_id, message=message, progress=progress, detail=detail))
                self._status_dirty = False
                self._status_sent_at = now
            pending = [*self._lines, *self._drop_notes()]
            self._lines.clear()
        for start in range(0, len(pending), self._max_lines_per_frame):
            frames.append(LogLines(lease_id=self.lease_id, job_id=self.job_id, lines=pending[start : start + self._max_lines_per_frame]))
        return frames

    def _take_token(self) -> bool:
        now = self._clock()
        self._tokens = min(float(self._burst_lines), self._tokens + (now - self._tokens_at) * self._lines_per_second)
        self._tokens_at = now
        if self._tokens < 1.0:
            return False
        self._tokens -= 1.0
        return True

    def _append(self, line: LogLine) -> None:
        if len(self._lines) == self._lines.maxlen:
            self._dropped_by_buffer += 1  # deque drops the oldest line
        self._lines.append(line)

    def _drop_notes(self) -> List[LogLine]:
        """One daemon line per kind of drop since the last frames; they follow the buffered lines, never replace one."""
        notes = []
        if self._dropped_by_rate:
            notes.append(f"{self._dropped_by_rate} log lines dropped: more than {self._lines_per_second:g} lines per second")
            self._dropped_by_rate = 0
        if self._dropped_by_buffer:
            notes.append(f"{self._dropped_by_buffer} older log lines dropped while the control node was unreachable")
            self._dropped_by_buffer = 0
        return [LogLine(timestamp=self._wall_clock(), stream=LogStream.DAEMON, source=DAEMON_SOURCE, text=note) for note in notes]
