"""What running jobs report on the way: the latest status and the most recent log lines.

Kept in the control node's memory for the job queries, bounded per job and in the number of
jobs. Results and state changes are in the job store; this is only the live view.

A listener (the live channel, live/topics.py) hears each status and each batch of log
lines, and every change of a job's state that the control plane reports through changed().
It is called on the event loop and must return at once.
"""

from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Protocol

from scenegems_tool.cluster.protocol.messages import JobStatus, LogLine, LogLines
from scenegems_tool.persistence.clock import Clock, utc_now

MAX_LINES_PER_JOB = 200
MAX_JOBS = 1000


@dataclass
class JobProgress:
    lease_id: str
    progress: Optional[float]
    message: str
    at: datetime
    detail: Optional[Dict[str, Any]] = None  # what the job said beyond its message (JobStatus.detail)


class ActivityListener(Protocol):
    def job_status(self, job_id: str, progress: JobProgress) -> None: ...

    def job_logs(self, job_id: str, lines: List[LogLine]) -> None: ...

    def job_changed(self, job_id: str) -> None: ...


@dataclass
class _Activity:
    status: Optional[JobProgress] = None
    lines: Deque[LogLine] = field(default_factory=lambda: deque(maxlen=MAX_LINES_PER_JOB))


class JobActivity:
    def __init__(self, clock: Clock = utc_now):
        self._clock = clock
        self._jobs: "OrderedDict[str, _Activity]" = OrderedDict()
        self.listener: Optional[ActivityListener] = None

    def status(self, status: JobStatus) -> None:
        progress = JobProgress(lease_id=status.lease_id, progress=status.progress, message=status.message, at=self._clock(), detail=status.detail)
        self._entry(status.job_id).status = progress
        if self.listener is not None:
            self.listener.job_status(status.job_id, progress)

    def logs(self, logs: LogLines) -> None:
        self._entry(logs.job_id).lines.extend(logs.lines)
        if self.listener is not None:
            self.listener.job_logs(logs.job_id, list(logs.lines))

    def changed(self, job_id: str) -> None:
        """The job's state may have changed (an offer, accept, result, expiry, cancel, ...)."""
        if self.listener is not None:
            self.listener.job_changed(job_id)

    def progress(self, job_id: str) -> Optional[JobProgress]:
        activity = self._jobs.get(job_id)
        return None if activity is None else activity.status

    def lines(self, job_id: str) -> List[LogLine]:
        activity = self._jobs.get(job_id)
        return [] if activity is None else list(activity.lines)

    def _entry(self, job_id: str) -> _Activity:
        activity = self._jobs.pop(job_id, None) or _Activity()
        self._jobs[job_id] = activity
        while len(self._jobs) > MAX_JOBS:
            self._jobs.popitem(last=False)
        return activity
