"""Entry point of a per-job runner container: run the job's in-container part and write its result.

The launcher has copied the job document into JOB_FOLDER before the start, and copies the
result document out after the stop (launchers/per_job/job_container_io.py). An observable
job (a simulation) also gets the job folder's observation (run_observation.py).
"""

import json
import sys
import traceback
from typing import Any, Dict, Optional

from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.worker_node.job_observation import OBSERVABLE_JOB_TYPES
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.jobs.in_container.json_values import json_safe
from scenegems_tool.cluster.worker_node.jobs.in_container.run_observation import ContainerObservation
from scenegems_tool.cluster.worker_node.jobs.job_types import job_type_module
from scenegems_tool.cluster.worker_node.launchers.per_job.job_container_io import JOB_DOCUMENT, JOB_FOLDER, RESULT_DOCUMENT, format_status_line


def status(message: str, progress: Optional[float] = None, detail: Optional[Dict[str, Any]] = None) -> None:
    print(format_status_line(message, progress, detail), flush=True)


def _write_outcome(outcome: dict) -> None:
    with open(f"{JOB_FOLDER}/{RESULT_DOCUMENT}", "w", encoding="utf-8") as file:
        json.dump(outcome, file)


def main() -> int:
    with open(f"{JOB_FOLDER}/{JOB_DOCUMENT}", encoding="utf-8") as file:
        job = JobSpec.model_validate(json.load(file)["job"])
    status(f"{job.job_type.value} job {job.job_id} attempt {job.attempt} started")
    try:
        if job.job_type in OBSERVABLE_JOB_TYPES:
            result = job_type_module(job.job_type).execute(job, status, observation=ContainerObservation(JOB_FOLDER))
        else:
            result = job_type_module(job.job_type).execute(job, status)
    except JobFailed as error:
        _write_outcome({"error": str(error), "retryable": error.retryable})
        return 1
    except Exception as error:
        traceback.print_exc()
        _write_outcome({"error": f"{type(error).__name__}: {error}", "retryable": False})
        return 1
    _write_outcome({"result": json_safe(result)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
