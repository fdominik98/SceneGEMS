"""The route worker nodes use, served over plain HTTP on the VPN: the control WebSocket.

    WS   WORKER_NODE_CONTROL_PATH     the control link (control_link/worker_node_control_socket.py)

There is no pairing and no credential: the control node trusts every machine that can reach it.
"""

from fastapi import APIRouter, WebSocket

from scenegems_tool.cluster.control_node.control_link.worker_node_control_socket import serve_worker_node_control
from scenegems_tool.cluster.control_node.control_plane import ControlPlane
from scenegems_tool.cluster.protocol.routes import WORKER_NODE_CONTROL_PATH


def worker_node_router(plane: ControlPlane) -> APIRouter:
    router = APIRouter()

    @router.websocket(WORKER_NODE_CONTROL_PATH)
    async def worker_node_control(websocket: WebSocket) -> None:
        await serve_worker_node_control(websocket, plane)

    return router
