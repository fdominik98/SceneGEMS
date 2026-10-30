"""The operator's routes: jobs and nodes, for tests, scripts and the later control panel UI.

They have no authentication yet (Phase 5 adds operator accounts), so the master serves
them only on its operator listener, which is bound to the local machine, next to the
workbench gateway.

    POST JOBS_PATH                       JobSubmission; 201 with the new job, 200 with the job the
                                         idempotency key already names, 422 when the payload does
                                         not match its job type, 503 while the master's expected
                                         fingerprints are not available
    GET  JOBS_PATH?state=&limit=         jobs in submission order
    GET  JOBS_PATH/<job id>              one job with its payload, events, progress and recent log lines
    POST JOBS_PATH/<job id>/cancel       cancels the job; its node is told to stop
    GET  NODES_PATH                      nodes with status, connection and fingerprint state
    GET  NODES_PATH/<node id>
    POST NODES_PATH/<node id>/drain      no new jobs; running ones finish
    POST NODES_PATH/<node id>/resume     ends the drain
    POST NODES_PATH/<node id>/remove     forgets an offline node; 409 while it is not offline or holds a lease
    GET  STATUS_PATH                     master id, expected fingerprints (by image repository), connected
                                         nodes, and live_sessions: whether the workbench gateway starts live sessions

The node view carries the machine the node runs on (null until a node that reports it says hello).

The catalog routes (catalog_routes.py) and the setting routes (setting_routes.py: the domain configuration and the campaign presets,
read-only without the campaign stores) are always there; the campaign routes (campaign_routes.py) join them when the master has the campaign stores.
"""

from typing import Optional

import anyio
from fastapi import APIRouter, Body, HTTPException, Response

from scenegems_tool.cluster.master.api.campaign_routes import campaign_router, unavailable_router
from scenegems_tool.cluster.master.api.catalog_routes import catalog_router
from scenegems_tool.cluster.master.api.setting_routes import setting_router
from scenegems_tool.cluster.master.api.views import job_detail_view, job_view, node_view
from scenegems_tool.cluster.master.control_plane import ControlPlane, FingerprintsUnavailable, InvalidPayload
from scenegems_tool.cluster.protocol.jobs import JobState, JobSubmission
from scenegems_tool.cluster.protocol.routes import JOBS_PATH
from scenegems_tool.persistence.stores import AssuranceStores, SubmitOutcome, UnknownJob

NODES_PATH = "/cluster/nodes"
STATUS_PATH = "/cluster/status"
MAX_LISTED_JOBS = 1000


def operator_router(plane: ControlPlane, assurance: Optional[AssuranceStores] = None, live_sessions: bool = False) -> APIRouter:
    router = APIRouter()
    router.include_router(catalog_router())
    router.include_router(setting_router(assurance))
    router.include_router(unavailable_router() if assurance is None else campaign_router(assurance, plane))
    router.include_router(_job_routes(plane))
    router.include_router(_node_routes(plane, live_sessions))
    return router


async def _submit(plane: ControlPlane, submission: JobSubmission) -> SubmitOutcome:
    try:
        return await plane.submit(submission)
    except FingerprintsUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error))
    except InvalidPayload as error:
        raise HTTPException(status_code=422, detail={"message": str(error), "job_type": error.job_type.value, "errors": error.errors})


def _job_routes(plane: ControlPlane) -> APIRouter:
    router = APIRouter()

    @router.post(JOBS_PATH)
    async def submit_job(submission: JobSubmission, response: Response) -> dict:
        outcome = await _submit(plane, submission)
        response.status_code = 201 if outcome.created else 200
        return job_view(outcome.job)

    @router.get(JOBS_PATH)
    async def list_jobs(state: Optional[JobState] = None, limit: int = 100) -> list:
        jobs = await anyio.to_thread.run_sync(lambda: plane.jobs.list_jobs(state=state, limit=max(1, min(limit, MAX_LISTED_JOBS))))
        return [job_view(job, plane.activity.progress(job.job_id)) for job in jobs]

    @router.get(JOBS_PATH + "/{job_id}")
    async def get_job(job_id: str) -> dict:
        job = await anyio.to_thread.run_sync(plane.jobs.get, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"no job {job_id}")
        events = await anyio.to_thread.run_sync(plane.jobs.events, job_id)
        return job_detail_view(job, plane.activity.progress(job_id), events, plane.activity.lines(job_id))

    @router.post(JOBS_PATH + "/{job_id}/cancel")
    async def cancel_job(job_id: str, reason: str = Body("cancelled by the operator", embed=True)) -> dict:
        try:
            outcome = await plane.cancel(job_id, reason)
        except UnknownJob:
            raise HTTPException(status_code=404, detail=f"no job {job_id}")
        return {"cancelled": outcome.cancelled, "job": job_view(outcome.job)}

    return router


def _node_routes(plane: ControlPlane, live_sessions: bool) -> APIRouter:
    router = APIRouter()

    @router.get(NODES_PATH)
    async def list_nodes() -> list:
        return [node_view(node, plane.registry.session(node.node_id)) for node in await plane.registry.nodes()]

    @router.get(NODES_PATH + "/{node_id}")
    async def get_node(node_id: str) -> dict:
        node = await plane.registry.node(node_id)
        if node is None:
            raise HTTPException(status_code=404, detail=f"no node {node_id}")
        return node_view(node, plane.registry.session(node_id))

    @router.get(STATUS_PATH)
    async def status() -> dict:
        expected = plane.expected.current()
        return {
            "master_id": plane.master_id,
            "expected_fingerprints": {"state": plane.expected.state.value, "error": plane.expected.error, "images": expected or {}},
            "connected_nodes": [session.node_id for session in plane.registry.connected()],
            "live_sessions": live_sessions,
        }

    router.include_router(_node_control_routes(plane))
    return router


def _node_control_routes(plane: ControlPlane) -> APIRouter:
    router = APIRouter()

    @router.post(NODES_PATH + "/{node_id}/drain")
    async def drain_node(node_id: str, reason: str = Body("drained by the operator", embed=True)) -> dict:
        node = await plane.drain(node_id, reason)
        if node is None:
            raise HTTPException(status_code=404, detail=f"no node {node_id}")
        return node_view(node, plane.registry.session(node_id))

    @router.post(NODES_PATH + "/{node_id}/resume")
    async def resume_node(node_id: str) -> dict:
        node = await plane.resume(node_id)
        if node is None:
            raise HTTPException(status_code=404, detail=f"no node {node_id}")
        return node_view(node, plane.registry.session(node_id))

    @router.post(NODES_PATH + "/{node_id}/remove")
    async def remove_node(node_id: str) -> dict:
        removed = await plane.remove_node(node_id)
        if removed is None:
            raise HTTPException(status_code=404, detail=f"no node {node_id}")
        if not removed:
            raise HTTPException(status_code=409, detail=f"node {node_id} cannot be removed: only an offline node without leases can be")
        return {"removed": node_id}

    return router
