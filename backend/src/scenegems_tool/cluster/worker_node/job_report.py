"""How a running job talks back to its caller: status lines, log lines and failure.

The worker node daemon (P3.4) turns these calls into JobStatus and LogLines frames; the workbench
or a test can collect them directly.
"""

import threading
from typing import Any, Dict, Optional, Protocol, Tuple

from scenegems_tool.cluster.protocol.messages import LogStream

JobResultData = Dict[str, Any]  # the result field of JobResult


class JobReport(Protocol):
    def status(self, message: str, progress: Optional[float] = None, detail: Optional[Dict[str, Any]] = None) -> None: ...

    def log(self, source: str, text: str, stream: LogStream = LogStream.STDOUT) -> None: ...


class StatusDetailReport:
    """A job's report that adds what its launcher knows to the detail of every status, such as the ports the stack published.

    The control node keeps only a job's latest status, so a detail has to be on each of them: what is added later
    goes out at once with the latest status again.
    """

    def __init__(self, report: JobReport):
        self._report = report
        self._extra: Dict[str, Any] = {}
        self._latest: Optional[Tuple[str, Optional[float], Optional[Dict[str, Any]]]] = None
        self._lock = threading.Lock()

    def status(self, message: str, progress: Optional[float] = None, detail: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            self._latest = (message, progress, detail)
            merged = {**(detail or {}), **self._extra}
        if merged:
            self._report.status(message, progress, merged)
        else:
            self._report.status(message, progress)

    def add_detail(self, extra: Dict[str, Any]) -> None:
        with self._lock:
            self._extra.update(extra)
            latest = self._latest
        if latest is not None:
            self.status(*latest)

    def log(self, source: str, text: str, stream: LogStream = LogStream.STDOUT) -> None:
        self._report.log(source, text, stream)


class JobFailed(RuntimeError):
    """A job that did not produce a result. retryable says whether another attempt can succeed."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable
