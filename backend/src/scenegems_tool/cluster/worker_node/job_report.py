"""How a running job talks back to its caller: status lines, log lines and failure.

The worker node daemon (P3.4) turns these calls into JobStatus and LogLines frames; the workbench
or a test can collect them directly.
"""

from typing import Any, Dict, Optional, Protocol

from scenegems_tool.cluster.protocol.messages import LogStream

JobResultData = Dict[str, Any]  # the result field of JobResult


class JobReport(Protocol):
    def status(self, message: str, progress: Optional[float] = None, detail: Optional[Dict[str, Any]] = None) -> None: ...

    def log(self, source: str, text: str, stream: LogStream = LogStream.STDOUT) -> None: ...


class JobFailed(RuntimeError):
    """A job that did not produce a result. retryable says whether another attempt can succeed."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable
