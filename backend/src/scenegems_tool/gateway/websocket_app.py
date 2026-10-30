"""
The workbench gateway: the web console's WebSocket. The master mounts `app` on its operator
listener (cluster/master/server.py); it does not run on its own.
"""

import atexit
import json
import logging
import signal
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from scenegems_tool.cluster.node.docker_subsystem_shutdown import shutdown_all_docker_subsystems
from scenegems_tool.gateway.live_run_recorder import LiveRunRecorder
from scenegems_tool.gateway.web_socket_session_manager import WebSocketSessionManager
from utils.file_system_utils import ensure_directories

logger = logging.getLogger(__name__)
websocket_session_manager = WebSocketSessionManager()
_shutdown_handlers_registered = False


def _register_process_shutdown_handlers() -> None:
    global _shutdown_handlers_registered
    if _shutdown_handlers_registered:
        return
    _shutdown_handlers_registered = True
    atexit.register(shutdown_all_docker_subsystems)

    def _handle_signal(signum, frame) -> None:  # noqa: ARG001
        shutdown_all_docker_subsystems()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_directories()
    _register_process_shutdown_handlers()
    recorder = run_recorder(_app)
    if recorder is not None:
        # No connection exists yet, so a live session entry still running without a run lost its session with the last process
        try:
            await recorder.stop_stranded_entries()
        except Exception:
            logger.exception("Cannot stop the live session entries the last master process left running")
    yield
    websocket_session_manager.shutdown_all()
    shutdown_all_docker_subsystems()


app = FastAPI(title="SceneGEMS Tool Backend", lifespan=lifespan)
app.state.run_recorder = None  # the master sets its LiveRunRecorder (set_run_recorder); on its own the gateway records nothing
app.state.live_sessions = True  # the master turns them off without the Docker socket (set_live_sessions)


def set_run_recorder(recorder: Optional[LiveRunRecorder], gateway: FastAPI = app) -> None:
    """Live sessions of this gateway's connections are recorded through the recorder from now on (the master's, cluster/master/server.py)."""
    gateway.state.run_recorder = recorder


def run_recorder(gateway: FastAPI = app) -> Optional[LiveRunRecorder]:
    return getattr(gateway.state, "run_recorder", None)


def set_live_sessions(enabled: bool, gateway: FastAPI = app) -> None:
    """Whether this gateway's new connections may start live sessions (the master's SCENEGEMS_LIVE_SESSIONS); when off they are refused."""
    gateway.state.live_sessions = enabled


def live_sessions(gateway: FastAPI = app) -> bool:
    return bool(getattr(gateway.state, "live_sessions", True))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws/scenegems_backend_service")
async def backend_service_socket(websocket: WebSocket) -> None:  # noqa: C901
    await websocket.accept()
    session, message_processor = websocket_session_manager.create_session(websocket=websocket, live_sessions=live_sessions())
    session.run_recorder = run_recorder()
    try:
        session.send_payload(session.mqtt_broker_status_message(status="disconnected"))
    except WebSocketDisconnect:
        websocket_session_manager.remove_session(websocket=websocket)
        return

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                session.send_runtime_error("Invalid JSON message payload.")
                continue
            except ValueError as exc:
                session.send_runtime_error(str(exc))
                continue

            session.log_payload("incoming", payload=message)
            await message_processor.inbound_queue.put(message)

    except WebSocketDisconnect:
        websocket_session_manager.remove_session(websocket=websocket)
        return
