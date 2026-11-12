"""What a run's runner container is handed: the job document, and the status callback of its in-container part.

The runner container belongs to a simulation's stack (launchers/per_job/job_stack.py); no job has a container
of its own any more.
"""

from typing import Callable

from scenegems_tool.cluster.protocol.jobs import JobSpec

StatusCallback = Callable[..., None]  # status(message, progress=None), inside the container


def job_document(job: JobSpec) -> dict:
    """What the runner container receives: the leased job, payload included."""
    return {"job": job.model_dump(mode="json")}
