"""The worker node's control WebSocket on the control node: the Hello handshake and the frame loop.

Every machine on the VPN is trusted, so there is no authentication. A connection goes
through three steps:

    1. The first frame must be Hello, within ControlTiming.hello_timeout_s; it names the
       worker node. Another protocol version gets ProtocolError(version_mismatch) and close 1002;
       anything else invalid gets ProtocolError(malformed_frame) and close 1002.
    2. The control plane registers the worker node, reconciles its leases and sends Welcome. A worker node
       that connects again under the same id replaces its earlier connection.
    3. Every later frame goes to the control plane. A malformed frame is answered with
       ProtocolError and the connection stays; a version change mid-connection closes it.
"""

import asyncio
import logging
from typing import Optional, Union

from starlette.websockets import WebSocket, WebSocketDisconnect

from scenegems_tool.cluster.control_node.control_plane import ControlPlane
from scenegems_tool.cluster.control_node.registry.worker_node_session import WorkerNodeSession
from scenegems_tool.cluster.protocol.codec import MalformedFrame, decode_worker_node_message, encode
from scenegems_tool.cluster.protocol.messages import Hello, ProtocolError, ProtocolErrorCode
from scenegems_tool.cluster.protocol.model_base import ProtocolFrame
from scenegems_tool.cluster.protocol.version import ProtocolVersionMismatch
from scenegems_tool.cluster.scope_names import is_scope_name

logger = logging.getLogger(__name__)

CLOSE_PROTOCOL_ERROR = 1002  # another protocol version, or no valid Hello


class WebSocketControlSocket:
    """A starlette WebSocket as the control plane's ControlSocket: one frame at a time, errors as False."""

    def __init__(self, websocket: WebSocket):
        self.address = websocket.client.host if websocket.client else None  # the worker node's address as the control node sees it
        self._websocket = websocket
        self._send_lock = asyncio.Lock()

    async def send(self, frame: ProtocolFrame) -> bool:
        try:
            async with self._send_lock:
                await self._websocket.send_text(encode(frame))
            return True
        except Exception:  # closed or broken; the receive loop sees the disconnect
            return False

    async def close(self, code: int, reason: str) -> None:
        try:
            await self._websocket.close(code=code, reason=reason)
        except Exception:
            pass

    async def receive(self) -> Union[str, bytes]:
        message = await self._websocket.receive()
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000))
        text = message.get("text")
        return text if text is not None else message.get("bytes") or b""

    async def refuse(self, code: ProtocolErrorCode, message: str, close_code: int) -> None:
        await self.send(ProtocolError(code=code, message=message))
        await self.close(close_code, code.value)


async def serve_worker_node_control(websocket: WebSocket, plane: ControlPlane) -> None:
    await websocket.accept()
    socket = WebSocketControlSocket(websocket)
    hello = await _receive_hello(socket, plane.timing.hello_timeout_s)
    if hello is None:
        return

    session = await plane.open_session(hello, socket)
    try:
        await _serve_frames(socket, session, plane)
    except (WebSocketDisconnect, RuntimeError):  # RuntimeError: receive after the control node closed the socket
        pass
    finally:
        await plane.close_session(session)


async def _serve_frames(socket: WebSocketControlSocket, session: WorkerNodeSession, plane: ControlPlane) -> None:
    """Hands every frame to the control plane until the socket closes or the worker node changes its protocol version."""
    while True:
        try:
            frame = decode_worker_node_message(await socket.receive())
        except ProtocolVersionMismatch as error:
            await socket.refuse(ProtocolErrorCode.VERSION_MISMATCH, str(error), CLOSE_PROTOCOL_ERROR)
            return
        except MalformedFrame as error:
            await session.send(ProtocolError(code=ProtocolErrorCode.MALFORMED_FRAME, message=str(error)))
            continue
        try:
            await plane.handle_frame(session, frame)
        except Exception:  # a store outage, for example: the lease timeouts cover what this frame missed
            logger.exception("Handling a %s frame of worker node %s failed", frame.type, session.worker_node_id)


async def _receive_hello(socket: WebSocketControlSocket, timeout_s: float) -> Optional[Hello]:
    """The worker node's Hello, or None after refusing the connection."""
    try:
        frame = decode_worker_node_message(await asyncio.wait_for(socket.receive(), timeout_s))
    except asyncio.TimeoutError:
        await socket.refuse(ProtocolErrorCode.MALFORMED_FRAME, f"No Hello within {timeout_s:.0f} s", CLOSE_PROTOCOL_ERROR)
        return None
    except ProtocolVersionMismatch as error:
        await socket.refuse(ProtocolErrorCode.VERSION_MISMATCH, str(error), CLOSE_PROTOCOL_ERROR)
        return None
    except MalformedFrame as error:
        await socket.refuse(ProtocolErrorCode.MALFORMED_FRAME, str(error), CLOSE_PROTOCOL_ERROR)
        return None
    except (WebSocketDisconnect, RuntimeError):
        return None
    if not isinstance(frame, Hello):
        await socket.refuse(ProtocolErrorCode.MALFORMED_FRAME, f"The first frame must be hello, got {frame.type}", CLOSE_PROTOCOL_ERROR)
        return None
    if not is_scope_name(frame.worker_node_id):  # it becomes a topic level and part of Docker names
        await socket.refuse(ProtocolErrorCode.MALFORMED_FRAME, f"Invalid worker node id {frame.worker_node_id!r}: use 1 to 63 lowercase letters, digits and hyphens", CLOSE_PROTOCOL_ERROR)
        return None
    return frame
