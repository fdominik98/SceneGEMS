"""Running a job in a single runner container of a subsystem image, with no network.

Used by the job types whose work is a batch in process (post-hoc monitoring, the calibration's
deviation between repeats). Their execute function runs inside the container. A job the node observes
(NodeContext.observations) gets its observation requests and returns its frames through
the job folder and its output (launchers/per_job/job_container_io.py).
"""

import threading
from typing import Callable, Optional

from scenegems_tool.cluster.node.job_report import JobReport, JobResultData
from scenegems_tool.cluster.node.launchers.per_job.job_stack import RUNNER_SERVICE, JobStack, runner_service
from scenegems_tool.cluster.node.node_context import NodeContext
from scenegems_tool.cluster.node.subsystem import Subsystem, subsystem_image
from scenegems_tool.cluster.protocol.jobs import JobSpec

StatusCallback = Callable[..., None]  # status(message, progress=None), inside the container


def job_document(job: JobSpec) -> dict:
    """What the runner container receives: the leased job, payload included."""
    return {"job": job.model_dump(mode="json")}


def run_in_runner_container(job: JobSpec, node: NodeContext, report: JobReport, subsystem: Subsystem, *, timeout_s: float, cancel: Optional[threading.Event] = None) -> JobResultData:
    stack = JobStack(node.job_scope(job), {RUNNER_SERVICE: runner_service(subsystem_image(subsystem))})
    return stack.run(job_document(job), report, timeout_s=timeout_s, cancel=cancel, observation=node.observations.of(job))
