"""The worker thread of one lease: run_job as a request to the job's subsystem, then its JobResult.

JobFailed becomes a failed result with the job's own `retryable`; any other exception a
failed result the control node may retry, as run_job documents. A result that cannot be encoded
fails for good, since another attempt would produce the same value.
"""

import logging
import threading
from typing import Callable, Optional

from scenegems_tool.cluster.protocol.codec import encode
from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobSpec
from scenegems_tool.cluster.protocol.messages import JobResult
from scenegems_tool.cluster.worker_node.daemon.leases.lease import Lease
from scenegems_tool.cluster.worker_node.daemon.leases.report_batcher import ReportBatcher
from scenegems_tool.cluster.worker_node.job_report import JobFailed, JobReport, JobResultData
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext

_logger = logging.getLogger(__name__)

JobRunner = Callable[[JobSpec, WorkerNodeContext, JobReport, threading.Event], JobResultData]  # the signature of run_job
MAX_ERROR_CHARACTERS = 4000


def job_result(lease: Lease, outcome: JobOutcome, *, result: Optional[JobResultData] = None, error: Optional[str] = None, retryable: bool = False) -> JobResult:
    return JobResult(
        lease_id=lease.lease_id,
        job_id=lease.job_id,
        idempotency_key=lease.job.idempotency_key,
        outcome=outcome,
        result=result or {},
        error=error[:MAX_ERROR_CHARACTERS] if error else None,
        retryable=retryable,
    )


def execute_lease(lease: Lease, run: JobRunner, worker_node: WorkerNodeContext, report: ReportBatcher) -> JobResult:
    """Run the leased job to its JobResult; never raises."""
    try:
        data = run(lease.job, worker_node, report, lease.cancel)
    except JobFailed as failure:
        return job_result(lease, JobOutcome.FAILED, error=str(failure) or type(failure).__name__, retryable=failure.retryable)
    except Exception as error:
        _logger.exception("Job %s of lease %s raised", lease.job_id, lease.lease_id)
        return job_result(lease, JobOutcome.FAILED, error=f"{type(error).__name__}: {error}", retryable=True)
    try:
        result = job_result(lease, JobOutcome.SUCCEEDED, result=dict(data or {}))
        encode(result)  # fails here, not later on the wire
        return result
    except Exception as error:
        return job_result(lease, JobOutcome.FAILED, error=f"The job's result cannot be sent: {type(error).__name__}: {error}", retryable=False)


def start_lease_worker(lease: Lease, run: JobRunner, worker_node: WorkerNodeContext, report: ReportBatcher, on_stopped: Callable[[Lease, JobResult], None]) -> threading.Thread:
    def work() -> None:
        result = execute_lease(lease, run, worker_node, report)
        on_stopped(lease, result)

    thread = threading.Thread(target=work, name=f"lease-{lease.lease_id}", daemon=True)
    thread.start()
    return thread
