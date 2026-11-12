"""
The workbench gateway: the web console's WebSocket for its in-process helpers (reading a scenario
file, generating vessel models, listing the stack options). The control node mounts `app` on its
operator listener (cluster/control_node/server.py); it does not run on its own. It starts no
container and connects to no broker: what computes is a job on a worker node.
"""

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from scenegems_tool.gateway.web_socket_session_manager import WebSocketSessionManager
from utils.file_system_utils import ensure_directories

logger = logging.getLogger(__name__)
websocket_session_manager = WebSocketSessionManager()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_directories()
    yield
    websocket_session_manager.shutdown_all()


app = FastAPI(title="SceneGEMS Tool Backend", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws/scenegems_backend_service")
async def backend_service_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    session, message_processor = websocket_session_manager.create_session(websocket=websocket)

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
