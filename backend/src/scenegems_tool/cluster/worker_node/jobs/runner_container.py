"""Running a job in a single runner container of a subsystem image, with no network.

Used by the job types whose work is a batch in process (post-hoc monitoring, the calibration's
deviation between repeats), whose execute function runs inside the container, and by the design
space exploration, whose image brings its own program for the same job folder protocol. A job the worker node observes
(WorkerNodeContext.observations) gets its observation requests and returns its frames through
the job folder and its output (launchers/per_job/job_container_io.py).
"""

import threading
from typing import Callable, Dict, List, Optional

from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.worker_node.job_report import JobReport, JobResultData
from scenegems_tool.cluster.worker_node.launchers.per_job.job_stack import RUNNER_SERVICE, JobStack, runner_service
from scenegems_tool.cluster.worker_node.subsystem import Subsystem, subsystem_image
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext

StatusCallback = Callable[..., None]  # status(message, progress=None), inside the container


def job_document(job: JobSpec) -> dict:
    """What the runner container receives: the leased job, payload included."""
    return {"job": job.model_dump(mode="json")}


def run_in_runner_container(
    job: JobSpec,
    worker_node: WorkerNodeContext,
    report: JobReport,
    subsystem: Subsystem,
    *,
    timeout_s: float,
    cancel: Optional[threading.Event] = None,
    command: Optional[List[str]] = None,
    environment: Optional[Dict[str, str]] = None,
) -> JobResultData:
    """command and environment replace the Python job main's, for a runner image that brings its own program (runner_service)."""
    stack = JobStack(worker_node.job_scope(job), {RUNNER_SERVICE: runner_service(subsystem_image(subsystem), command=command, environment=environment)})
    return stack.run(job_document(job), report, timeout_s=timeout_s, cancel=cancel, observation=worker_node.observations.of(job))
