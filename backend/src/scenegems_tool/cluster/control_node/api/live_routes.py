"""The browser's live channel on the operator listener: one WebSocket per browser tab.

    WS LIVE_PATH    subscribe to topics, receive their snapshots and updates (cluster/protocol/live.py)

Like the other operator routes it has no authentication yet and is served on the operator
listener only, which is bound to the control node's machine.
"""

from fastapi import APIRouter, WebSocket

from scenegems_tool.cluster.control_node.live.live_channel import LiveChannel
from scenegems_tool.cluster.protocol.routes import LIVE_PATH


def live_router(channel: LiveChannel) -> APIRouter:
    router = APIRouter()

    @router.websocket(LIVE_PATH)
    async def live(websocket: WebSocket) -> None:
        await channel.serve(websocket)

    return router
