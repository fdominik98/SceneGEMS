"""
FastAPI WebSocket entrypoint. Copy `python_backend/` into your project and run:

    uvicorn python_backend.websocket_app:app --reload --port 8000

Or mount `websocket_router` on your existing app.
"""

import atexit
import json
import multiprocessing
import signal
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from scenegems_tool.backend_service.protocol import make_waraps_status_message
from scenegems_tool.backend_service.web_socket_session_manager import WebSocketSessionManager
from scenegems_tool.docker_subsystem_shutdown import shutdown_all_docker_subsystems
from utils.file_system_utils import ensure_directories

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
    yield
    websocket_session_manager.shutdown_all()
    shutdown_all_docker_subsystems()


app = FastAPI(title="SceneGEMS Tool Backend", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws/scenegems_backend_service")
async def backend_service_socket(websocket: WebSocket) -> None:  # noqa: C901
    await websocket.accept()
    session, message_processor = websocket_session_manager.create_session(websocket=websocket)
    try:
        session.send_payload(make_waraps_status_message(status="disconnected"))
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


def create_app() -> FastAPI:
    return app


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn")
    # Run the WebSocket app with uvicorn when executed as a script.
    # Example:
    #   python -m simulation.backend_service.websocket_app
    # or (if PYTHONPATH is configured appropriately):
    #   python src/simulation/backend_service/websocket_app.py
    import uvicorn

    uvicorn.run(
        "scenegems_tool.backend_service.websocket_app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        ws_ping_interval=None,
    )
