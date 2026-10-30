"""The master's two FastAPI apps, one per listener, because each listener has its own audience.

Both run in the master process on one event loop (server.py) and share one control plane.

    node API     plain HTTP, reachable by nodes on the VPN, which the master trusts: the
                 control WebSocket (node_routes.py), artifact downloads and uploads
                 (artifact_routes.py). Its lifespan runs the control plane and the artifact
                 sweep.
    operator     plain HTTP bound to the local machine: the workbench WebSocket gateway,
                 mounted unchanged with its own lifespan, the job and node routes
                 (operator_routes.py, and campaign_routes.py with the campaign stores),
                 the catalog routes (catalog_routes.py), the cluster's domain configuration
                 and campaign presets (setting_routes.py), artifact reads, the browsers' live
                 channel (live_routes.py) and frames on demand (run_frames_routes.py). None
                 has authentication yet, which is why they are not on the node API's
                 listener. The web UI's origins may call it from a browser (CORS, below).
                 It answers /health itself, so a master without the gateway is healthy too.
"""

from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Optional, Sequence

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from scenegems_tool.cluster.master.api.artifact_routes import lease_holder_of, node_artifact_router, operator_artifact_router
from scenegems_tool.cluster.master.api.live_routes import live_router
from scenegems_tool.cluster.master.api.node_routes import node_router
from scenegems_tool.cluster.master.api.operator_routes import operator_router
from scenegems_tool.cluster.master.api.origin_guard import OriginGuard
from scenegems_tool.cluster.master.api.run_frames_routes import run_frames_router
from scenegems_tool.cluster.master.control_plane import ControlPlane
from scenegems_tool.cluster.master.live.live_channel import LiveChannel
from scenegems_tool.cluster.master.live.topics import create_live_channel
from scenegems_tool.cluster.master.master_artifacts import MasterArtifacts
from scenegems_tool.cluster.master.settings import DEFAULT_OPERATOR_ALLOWED_ORIGINS
from scenegems_tool.persistence.stores import AssuranceStores

HEALTH_PATH = "/health"  # the compose healthcheck's and the deployment tool's ready check


@dataclass(frozen=True)
class MasterApps:
    node_api: FastAPI
    operator: FastAPI


def create_node_api_app(plane: ControlPlane, run_timers: bool = True, artifacts: Optional[MasterArtifacts] = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await plane.start(timers=run_timers)
        if artifacts is not None and run_timers:
            artifacts.start_sweep()
        try:
            yield
        finally:
            if artifacts is not None:
                await artifacts.stop_sweep()
            await plane.stop()

    app = FastAPI(title=f"SceneGEMS master {plane.master_id}: node API", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(node_router(plane))
    if artifacts is not None:
        app.include_router(node_artifact_router(artifacts.artifacts, lease_holder_of(plane.jobs), artifacts.max_bytes))
    return app


def create_operator_app(
    plane: ControlPlane,
    gateway: Optional[FastAPI] = None,
    artifacts: Optional[MasterArtifacts] = None,
    assurance: Optional[AssuranceStores] = None,
    allowed_origins: Sequence[str] = DEFAULT_OPERATOR_ALLOWED_ORIGINS,
    live: Optional[LiveChannel] = None,
    live_sessions: Optional[bool] = None,
) -> FastAPI:
    """The operator routes, with the workbench gateway mounted behind them when given.

    live_sessions is whether the gateway starts live sessions, which /cluster/status reports; by
    default it has them exactly when it is mounted.

    The campaign routes need the campaign stores (assurance); without them they answer 503.
    Browsers of allowed_origins may read, post and delete (CORS): GET, POST, DELETE and HEAD with a
    JSON, YAML or file body, and read X-Total-Count and Content-Disposition. No other origin is allowed, and the
    origin guard refuses other origins' POSTs and WebSockets, which CORS alone would let through.
    Without a live channel one is made on the control plane, observing jobs but no pools.
    """
    live = live if live is not None else create_live_channel(plane, assurance)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with AsyncExitStack() as stack:
            stack.push_async_callback(live.close)
            if gateway is not None:
                await stack.enter_async_context(gateway.router.lifespan_context(gateway))
            yield

    app = FastAPI(title=f"SceneGEMS master {plane.master_id}: operator API", lifespan=lifespan)
    # What the campaign routes use beside their stores: the artifact store their input is checked against, and the live channel's campaigns topic
    app.state.artifact_store = None if artifacts is None else artifacts.artifacts
    app.state.campaigns_topic = getattr(live.producers, "campaign_list", None)
    app.add_api_route(HEALTH_PATH, _health, methods=["GET"])  # before the gateway's mount, which answers it too
    app.include_router(operator_router(plane, assurance, live_sessions=gateway is not None if live_sessions is None else live_sessions))
    app.include_router(live_router(live))
    if assurance is not None:
        app.include_router(run_frames_router(assurance, plane))
    if artifacts is not None:
        app.include_router(operator_artifact_router(artifacts.artifacts, artifacts.max_bytes))
    if gateway is not None:
        app.mount("/", gateway)  # last, so the cluster routes match first
    app.add_middleware(OriginGuard, allowed_origins=list(allowed_origins))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_methods=["GET", "POST", "DELETE", "HEAD"],
        allow_headers=["Content-Type"],
        expose_headers=["X-Total-Count", "Content-Disposition"],
    )
    return app


def create_master_apps(
    plane: ControlPlane,
    gateway: Optional[FastAPI] = None,
    run_timers: bool = True,
    artifacts: Optional[MasterArtifacts] = None,
    assurance: Optional[AssuranceStores] = None,
    allowed_origins: Sequence[str] = DEFAULT_OPERATOR_ALLOWED_ORIGINS,
    live: Optional[LiveChannel] = None,
    live_sessions: Optional[bool] = None,
) -> MasterApps:
    return MasterApps(
        node_api=create_node_api_app(plane, run_timers, artifacts),
        operator=create_operator_app(plane, gateway, artifacts, assurance, allowed_origins=allowed_origins, live=live, live_sessions=live_sessions),
    )


def _health() -> dict:
    return {"status": "ok"}
