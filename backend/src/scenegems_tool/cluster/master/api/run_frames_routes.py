"""Monitor frames of a recorded run, on demand: a post-hoc monitoring job over the run's stored state log.

A campaign keeps monitor frames only with policy keep_frames; for any other run the UI asks
for them here when it plays the run back. Served on the operator listener with the campaign
routes (campaign_routes.py), without authentication like them.

    POST CAMPAIGNS_PATH/<id>/run-records/<run record id>/frames
         submits a monitoring.post_hoc job with include_frames over the run's state log (the
         campaign's COLREGS constants, labels and pinned fingerprints), or finds the newest one
         of the run record: 201 when submitted, 200 when it existed. 404 for an unknown campaign
         or run record, 409 when the run's state log is not kept (retention removed it, or the
         run never stored one), 503 while the master's expected fingerprints are not available,
         422 when the master refuses the payload
    POST the same path with ?retry=true
         as above, except that a newest job that failed or was cancelled is not returned: a new
         job is submitted (201). A queued, leased, running or succeeded newest job is returned
    GET  the same path
         the newest job's state: 404 when none was made

Both answer {"run_record_id", "job": the job view, "frames": the frames artifact reference once
the job succeeded, else null}; the frames download from the artifact route (artifact_routes.py).
The jobs of a run record are keyed frames:<run record id> (the first), then frames:<id>:2, :3
and so on, one per retry; the newest is the one submitted last. Two retries at once name the
same next key, so they create one job. Without retry a failed or cancelled job is returned as it is.
"""

from functools import partial
from typing import Any, Callable, Dict, Optional, Tuple

import anyio
from fastapi import APIRouter, HTTPException, Response

from scenegems_tool.assurance.pipeline.pipeline_queries import latest_job_by_key_family
from scenegems_tool.cluster.fingerprints.job_images import job_images
from scenegems_tool.cluster.master.api.views import job_view
from scenegems_tool.cluster.master.control_plane import ControlPlane, FingerprintsUnavailable, InvalidPayload
from scenegems_tool.cluster.protocol.artifacts import ArtifactKind, ArtifactRef, is_reference
from scenegems_tool.cluster.protocol.jobs import JobRequirements, JobState, JobSubmission, JobType
from scenegems_tool.cluster.protocol.routes import CAMPAIGNS_PATH
from scenegems_tool.persistence.stores import AssuranceStores, JobRecord, RunRecord

FRAMES_PATH = CAMPAIGNS_PATH + "/{campaign_id}/run-records/{run_record_id}/frames"
FRAMES_PRIORITY = 100  # ahead of campaign work: an operator waits for it
STATE_LOG_ROLE = "state_log"
RETRYABLE_STATES = (JobState.FAILED, JobState.CANCELLED)


def frames_key(run_record_id: int, attempt: int = 1) -> str:
    """The first request of a run record keeps frames:<id>; a request after a failed or cancelled one is frames:<id>:<n>."""
    return f"frames:{run_record_id}" if attempt <= 1 else f"frames:{run_record_id}:{attempt}"


async def _run(function: Callable[..., Any], *arguments: Any) -> Any:
    return await anyio.to_thread.run_sync(partial(function, *arguments))


def _frames_of(job: JobRecord) -> Optional[Dict[str, Any]]:
    if job.state != JobState.SUCCEEDED or not job.result:
        return None
    frames = job.result.get("frames")
    return dict(frames) if is_reference(frames) else None


def _view(run_record_id: int, job: JobRecord) -> Dict[str, Any]:
    return {"run_record_id": run_record_id, "job": job_view(job), "frames": _frames_of(job)}


def _run_record(stores: AssuranceStores, campaign_id: str, run_record_id: int) -> RunRecord:
    if stores.campaigns.get_campaign(campaign_id) is None:
        raise HTTPException(status_code=404, detail=f"no campaign {campaign_id}")
    record = stores.results.get_run_record(run_record_id)
    if record is None or record.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail=f"no run record {run_record_id} in campaign {campaign_id}")
    return record


def _state_log(stores: AssuranceStores, plane: ControlPlane, record: RunRecord) -> Dict[str, Any]:
    """The state log's reference: the simulation job's own (with its pointer), else from the artifact record."""
    sha256 = record.artifacts.get(STATE_LOG_ROLE)
    if not sha256:
        raise HTTPException(status_code=409, detail=f"run record {record.run_record_id} has no state log: the campaign's retention removed it or the run kept none")
    job = plane.jobs.get(record.job_id) if record.job_id else None
    trajectories = (job.result or {}).get("trajectories") if job is not None else None
    if is_reference(trajectories) and dict(trajectories).get("sha256") == sha256:
        return dict(trajectories)
    artifact = stores.artifacts.get(sha256)
    if artifact is None:
        raise HTTPException(status_code=409, detail=f"the state log of run record {record.run_record_id} is no longer stored")
    return ArtifactRef(sha256=sha256, size_bytes=artifact.size_bytes, kind=ArtifactKind.TRAJECTORIES, media_type=artifact.media_type).model_dump(mode="json")


def _submission(stores: AssuranceStores, plane: ControlPlane, campaign_id: str, run_record_id: int, attempt: int = 1) -> JobSubmission:
    """The post-hoc job with frames over the run's state log, with the campaign's COLREGS constants, labels and pinned fingerprints."""
    record = _run_record(stores, campaign_id, run_record_id)
    trajectories = _state_log(stores, plane, record)
    campaign = stores.campaigns.get_campaign(campaign_id)
    case = stores.cases.get_case(record.case_id)
    version = stores.campaigns.config_version(campaign_id, None if case is None else case.config_version)
    config = {} if version is None else version.config
    payload = {
        "trajectories": trajectories,
        "colregs_constraints_content": config.get("domain", {}).get("colregs_constants"),
        "scenario_id": f"run-record-{run_record_id}",
        "include_frames": True,
    }
    pinned = campaign.pinned_fingerprints if campaign is not None else {}
    fingerprints = {image: pinned[image] for image in job_images(JobType.MONITORING_POST_HOC) if image in pinned}
    resources = config.get("resources", {})
    labels = dict(resources.get("required_labels", {}))
    return JobSubmission(
        job_type=JobType.MONITORING_POST_HOC,
        payload=payload,
        requirements=JobRequirements(labels=labels, fingerprints=fingerprints),
        priority=FRAMES_PRIORITY,
        idempotency_key=frames_key(run_record_id, attempt),
        allowed_nodes=list(resources.get("nodes", [])),
    )


def _attempt_of(run_record_id: int, key: str) -> int:
    """The request number a frames key names: 1 for the base key, n for frames:<id>:<n>."""
    return 1 if key == frames_key(run_record_id) else int(key.rsplit(":", 1)[1])


def _requested(stores: AssuranceStores, plane: ControlPlane, campaign_id: str, run_record_id: int) -> Optional[Tuple[JobRecord, int]]:
    """The newest frames job of the run record with its request number, if one was requested."""
    _run_record(stores, campaign_id, run_record_id)
    with stores.transaction() as session:
        newest = latest_job_by_key_family(session, frames_key(run_record_id))
    if newest is None:
        return None
    job = plane.jobs.get(newest[0])
    return None if job is None else (job, _attempt_of(run_record_id, newest[1]))


def run_frames_router(stores: AssuranceStores, plane: ControlPlane) -> APIRouter:
    router = APIRouter()

    @router.post(FRAMES_PATH)
    async def request_frames(campaign_id: str, run_record_id: int, response: Response, retry: bool = False) -> dict:
        existing = await _run(_requested, stores, plane, campaign_id, run_record_id)
        attempt = 1
        if existing is not None:
            job, number = existing
            if not (retry and job.state in RETRYABLE_STATES):
                response.status_code = 200
                return _view(run_record_id, job)
            attempt = number + 1
        try:
            outcome = await plane.submit(await _run(_submission, stores, plane, campaign_id, run_record_id, attempt))
        except FingerprintsUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error))
        except InvalidPayload as error:
            raise HTTPException(status_code=422, detail={"message": str(error), "job_type": error.job_type.value, "errors": error.errors})
        response.status_code = 201 if outcome.created else 200
        return _view(run_record_id, outcome.job)

    @router.get(FRAMES_PATH)
    async def frames_status(campaign_id: str, run_record_id: int) -> dict:
        requested = await _run(_requested, stores, plane, campaign_id, run_record_id)
        if requested is None:
            raise HTTPException(status_code=404, detail=f"no frames were requested for run record {run_record_id}")
        return _view(run_record_id, requested[0])

    return router
