"""The master process: its two listeners in one event loop (api/master_apps.py says why two).

    python -m scenegems_tool.cluster.master [--env-file deploy/master/.env]

The database must be migrated first (`python -m scenegems_tool.persistence.migrate upgrade
head`; the compose service does both). Nodes and the master trust each other on the VPN: there
is no security folder, certificate or credential to set up.
"""

import argparse
import asyncio
import contextlib
import logging
import multiprocessing
import os
import signal
import sys
from pathlib import Path
from typing import List, Optional, Sequence

import uvicorn
from sqlalchemy.orm import Session, sessionmaker

from scenegems_tool.architecture.architecture_files import start_architecture_files_writer
from scenegems_tool.cluster.master.api.master_apps import MasterApps, create_master_apps
from scenegems_tool.cluster.master.control_plane import ControlPlane
from scenegems_tool.cluster.master.live.live_channel import LiveChannel
from scenegems_tool.cluster.master.live.observation_hub import paho_broker
from scenegems_tool.cluster.master.live.topics import create_live_channel
from scenegems_tool.cluster.master.master_artifacts import MasterArtifacts
from scenegems_tool.cluster.master.scheduling.fingerprint_policy import ExpectedFingerprints
from scenegems_tool.cluster.master.settings import MasterSettings, SettingMissing
from scenegems_tool.persistence.artifacts.file_artifact_store import FileArtifactStore
from scenegems_tool.persistence.artifacts.recorded_artifacts import RecordedArtifacts
from scenegems_tool.persistence.database import create_database_engine, create_session_factory
from scenegems_tool.persistence.stores import ArtifactRecordStore, AssuranceStores, JobStore, NodeStore

logger = logging.getLogger(__name__)

STARTUP_POLL_S = 0.1
MAX_NODE_FRAME_BYTES = 64 * 1024 * 1024  # the node daemon's limit; job results can exceed uvicorn's default of 16 MiB


class _Listener(uvicorn.Server):
    """A uvicorn server that leaves signals to the process, which stops every listener at once."""

    @contextlib.contextmanager
    def capture_signals(self):
        yield


def build_assurance_stores(sessions: sessionmaker[Session]) -> AssuranceStores:
    """The stores of campaigns and their results on the master's database; the campaign routes and the pipeline engine share one."""
    return AssuranceStores.create(sessions)


def load_env_file(path: Path, environ: dict) -> None:
    """KEY=VALUE lines into `environ`; variables already set keep their value."""
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        environ.setdefault(key, value)


def build_master(settings: MasterSettings, with_gateway: bool = True) -> MasterApps:
    sessions = create_session_factory(create_database_engine(settings.database_url))
    plane = ControlPlane(settings.master_id, NodeStore(sessions), JobStore(sessions), ExpectedFingerprints.of_release(settings.release_manifest))
    assurance = build_assurance_stores(sessions)
    plane.attach_pipeline(assurance)  # the pipeline engine, a timer of the control plane, on the master's one AssuranceStores
    artifacts = build_artifacts(settings, sessions)
    live = build_live_channel(settings, plane, assurance)
    gateway = None
    if with_gateway:
        from scenegems_tool.gateway.websocket_app import app as gateway
        from scenegems_tool.gateway.websocket_app import set_live_sessions, set_run_recorder

        set_run_recorder(build_run_recorder(plane, assurance, artifacts, live), gateway)
        set_live_sessions(settings.live_sessions, gateway)
    live_sessions = gateway is not None and settings.live_sessions
    if not live_sessions:
        logger.info("Live sessions are off on this master (SCENEGEMS_LIVE_SESSIONS or --no-workbench): the workbench refuses them")

    return create_master_apps(
        plane,
        gateway=gateway,
        artifacts=artifacts,
        assurance=assurance,
        allowed_origins=settings.operator_allowed_origins,
        live=live,
        live_sessions=live_sessions,
    )


def build_run_recorder(plane: ControlPlane, assurance: AssuranceStores, artifacts: MasterArtifacts, live: LiveChannel):
    """The gateway's recorder of live sessions: workbench entries on the master's stores, artifacts and pipeline engine (design doc 6.4)."""
    from scenegems_tool.gateway.live_run_recorder import LiveRunRecorder

    campaign_list = getattr(live.producers, "campaign_list", None)
    announce = None if campaign_list is None else campaign_list.campaigns_changed
    return LiveRunRecorder(assurance, artifacts.artifacts, plane.pipeline, max_bytes=artifacts.max_bytes, announce=announce)


def build_live_channel(settings: MasterSettings, plane: ControlPlane, assurance: AssuranceStores) -> LiveChannel:
    """The browsers' live channel; it observes pools on the cluster broker when the master knows where it is."""
    broker = None
    if settings.broker is not None:
        broker = paho_broker(settings.broker.host, settings.broker.port)
    else:
        logger.info("No cluster broker for the master (SCENEGEMS_BROKER_HOST): the live channel observes jobs, not pools")
    return create_live_channel(plane, assurance, broker)


def build_artifacts(settings: MasterSettings, sessions) -> MasterArtifacts:
    """The artifact store on its folder with its Postgres records, and the sweep's timing."""
    artifacts = RecordedArtifacts(FileArtifactStore(settings.artifacts.folder), ArtifactRecordStore(sessions))
    return MasterArtifacts(artifacts, settings.artifacts.max_bytes, settings.artifacts.sweep_interval_s, settings.artifacts.sweep_grace_s)


def listeners(settings: MasterSettings, apps: MasterApps) -> List[uvicorn.Server]:
    # uvicorn's loggers are process-wide, so both listeners share one log setup. Access logs
    # are off: the health check would fill them; the master logs its own events.
    logging_options = dict(log_level="info", access_log=False)
    return [
        _Listener(
            uvicorn.Config(
                apps.node_api,
                host=settings.node_api.host,
                port=settings.node_api.port,
                ws_max_size=MAX_NODE_FRAME_BYTES,
                **logging_options,
            )
        ),
        # The workbench frontend expects no WebSocket pings, as the gateway's own main runs it
        _Listener(uvicorn.Config(apps.operator, host=settings.operator.host, port=settings.operator.port, ws_ping_interval=None, **logging_options)),
    ]


async def serve(servers: Sequence[uvicorn.Server]) -> None:
    def stop(*_arguments) -> None:
        for server in servers:
            server.should_exit = True

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop)
    tasks = [asyncio.create_task(server.serve()) for server in servers]
    while not all(server.started for server in servers) and not any(task.done() for task in tasks):
        await asyncio.sleep(STARTUP_POLL_S)
    # Again after startup: the workbench gateway's lifespan installs handlers that end the process at
    # once. These stop every listener instead, and the gateway's lifespan teardown removes its containers.
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop)
    await asyncio.gather(*tasks)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scenegems_tool.cluster.master", description="Run a SceneGEMS master: node API and operator API with the workbench.")
    parser.add_argument("--env-file", type=Path, help="read settings from this .env file (variables already set win)")
    parser.add_argument("--no-workbench", action="store_true", help="do not mount the workbench gateway on the operator listener")
    arguments = parser.parse_args(argv)
    # force: an import may already have logged, which gives the root logger a WARNING handler
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s", force=True)
    environ = dict(os.environ)
    try:
        if arguments.env_file:
            load_env_file(arguments.env_file, environ)
        settings = MasterSettings.from_environment(environ)
        apps = build_master(settings, with_gateway=not arguments.no_workbench)
    except (SettingMissing, FileNotFoundError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    multiprocessing.set_start_method("spawn", force=True)  # as the gateway's own main: workbench workers are spawned
    start_architecture_files_writer()  # the Capabilities page's description files, regenerated from the code on every start
    asyncio.run(serve(listeners(settings, apps)))
    return 0
