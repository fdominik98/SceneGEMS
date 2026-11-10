"""Waiting on a pooled service from a job: its first heartbeat, then the one reply the job asked for."""

import threading
import time
from typing import Callable, Optional

from scenegems_tool.cluster.worker_node.job_report import JobFailed, JobReport

POOL_STARTUP_TIMEOUT_S = 180.0  # a cold pool: container start, imports and the broker handshake
_POLL_S = 0.1


def wait_for_pool(is_ready: Callable[[], bool], report: JobReport, description: str, cancel: Optional[threading.Event], timeout_s: float = POOL_STARTUP_TIMEOUT_S) -> None:
    """Block until the pool's service heartbeats; a pool that never does fails the attempt, which may be retried."""
    report.status(f"waiting for the {description}")
    deadline = time.monotonic() + timeout_s
    while not is_ready():
        if cancel is not None and cancel.is_set():
            raise JobFailed("cancelled", retryable=False)
        if time.monotonic() > deadline:
            raise JobFailed(f"The {description} sent no heartbeat within {timeout_s:g} s", retryable=True)
        time.sleep(_POLL_S)


def wait_for_reply(replied: threading.Event, report: JobReport, description: str, cancel: Optional[threading.Event], timeout_s: float) -> None:
    report.status(f"waiting for the {description}")
    deadline = time.monotonic() + timeout_s
    while not replied.wait(_POLL_S):
        if cancel is not None and cancel.is_set():
            raise JobFailed("cancelled", retryable=False)
        if time.monotonic() > deadline:
            raise JobFailed(f"No {description} within {timeout_s:g} s", retryable=True)
