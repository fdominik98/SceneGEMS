"""The worker node's entry point for a leased job: run_job(job, worker node, report).

The daemon (P3.4) calls it on a worker thread per lease, within the worker node's slots. It
returns the job's result or raises JobFailed; any other exception is a failure that may
succeed on another attempt.

Artifacts (cluster/protocol/artifacts.py): before the job runs, every reference in its
type's input fields is replaced by the artifact's content, downloaded through the worker node's
artifact transport, so the job and its runner container (which has no network) see inline
data. After the run, the type's large result fields are uploaded and the result carries
references in their place. A job without references runs exactly as before; a worker node
without artifact transport (tests, the workbench) keeps its results inline.

Failures: a download or upload that fails (connection, timeout, control node error) is
retryable; content that does not match its hash, a missing artifact or a reference that
does not fit its document is not.
"""

import threading
from typing import Optional

from scenegems_tool.cluster.protocol.artifacts import ArtifactField, ArtifactRef, is_reference, resolve_references, store_results
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.worker_node.artifacts.artifact_client import ArtifactTransferError
from scenegems_tool.cluster.worker_node.job_report import JobFailed, JobReport, JobResultData
from scenegems_tool.cluster.worker_node.jobs.job_types import artifact_input_fields, artifact_result_fields, job_type_module
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext


def run_job(job: JobSpec, worker_node: WorkerNodeContext, report: JobReport, cancel: Optional[threading.Event] = None) -> JobResultData:
    """Run one job in its subsystem container and return its result. Setting cancel stops it."""
    if worker_node.slots and job.job_type not in worker_node.slots:
        raise JobFailed(f"This worker node offers no {job.job_type.value} slots", retryable=True)
    lacking = worker_node.lacks(job)
    if lacking:
        raise JobFailed(f"This worker node does not offer the components {', '.join(lacking)}", retryable=True)
    resolved = resolve_job_inputs(job, worker_node, report)
    result = job_type_module(job.job_type).run(resolved, worker_node, report, cancel)
    return store_job_results(job, result, worker_node, report)


def resolve_job_inputs(job: JobSpec, worker_node: WorkerNodeContext, report: JobReport) -> JobSpec:
    """The job with its input references replaced by their content; the job itself when it has none."""
    fields = artifact_input_fields(job.job_type)
    references = sum(1 for field in fields for item in _field_items(job.payload.get(field.name), field) if is_reference(item))
    if not references:
        return job
    if worker_node.artifacts is None:
        raise JobFailed(f"The {job.job_type.value} payload holds artifact references, but this worker node has no artifact transport", retryable=False)
    report.status(f"Downloading {references} input artifacts")

    def load(reference: ArtifactRef) -> bytes:
        return worker_node.artifacts.load(reference)

    try:
        payload = resolve_references(job.payload, fields, load)
    except ArtifactTransferError as error:
        raise JobFailed(f"Cannot resolve the job's input artifacts: {error}", retryable=error.retryable) from error
    except (KeyError, IndexError, ValueError, UnicodeDecodeError) as error:
        raise JobFailed(f"An input artifact does not hold what its reference names: {type(error).__name__}: {error}", retryable=False) from error
    return job.model_copy(update={"payload": payload})


def _field_items(value, field: ArtifactField) -> list:
    return list(value) if field.many and isinstance(value, (list, tuple)) else [value]


def store_job_results(job: JobSpec, result: JobResultData, worker_node: WorkerNodeContext, report: JobReport) -> JobResultData:
    """The result with its large fields uploaded and replaced by references; unchanged without artifact transport."""
    fields = artifact_result_fields(job.job_type)
    if worker_node.artifacts is None or not fields or not result:
        return result

    def put(field: ArtifactField, data: bytes) -> ArtifactRef:
        report.status(f"Uploading the {field.name} artifact ({len(data)} bytes)")
        return worker_node.artifacts.store(job, field, data)

    try:
        return store_results(result, fields, put)
    except ArtifactTransferError as error:
        raise JobFailed(f"Cannot upload the job's result artifacts: {error}", retryable=error.retryable) from error
    except (TypeError, ValueError) as error:  # encode_document: not JSON
        raise JobFailed(f"The job's result cannot be stored as an artifact: {type(error).__name__}: {error}", retryable=False) from error
