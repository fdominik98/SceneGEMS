"""The worker node's control WebSocket to its control node: plain `ws://` on the VPN, no credential.

One ControlLink is one connection. The connection thread opens it and reads frames; any
thread may send. A send on a closed link returns False instead of raising, so callers
treat a lost connection the same way wherever they notice it.

The WebSocket runs on a private asyncio loop in its own thread, and the other threads
hand it work: websockets' threading client reads and writes one connection from two
threads, which stalled its opening handshake under TLS, so the asyncio client stays.
"""

import asyncio
import logging
import queue
import threading
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Optional

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus, WebSocketException

from scenegems_tool.cluster.protocol.codec import decode_control_node_message, encode
from scenegems_tool.cluster.protocol.messages import ControlNodeMessage
from scenegems_tool.cluster.protocol.model_base import ProtocolFrame
from scenegems_tool.cluster.protocol.routes import WORKER_NODE_CONTROL_PATH

_logger = logging.getLogger(__name__)

OPEN_TIMEOUT_S = 15.0
SEND_TIMEOUT_S = 30.0  # a send that takes longer means the connection is dead
MAX_FRAME_BYTES = 64 * 1024 * 1024  # a lease offer or a result can carry whole trajectories
_CLOSED = object()  # end of the received frames


class LinkClosed(RuntimeError):
    """The connection is gone; the daemon reconnects."""


def control_url(control_node_url: str) -> str:
    return "ws://" + control_node_url[len("http://") :] + WORKER_NODE_CONTROL_PATH


class ControlLink:
    def __init__(self, control_node_url: str, *, open_timeout_s: float = OPEN_TIMEOUT_S):
        self.url = control_url(control_node_url)
        self._open_timeout_s = open_timeout_s
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._connection: Optional[ClientConnection] = None
        self._received: "queue.Queue" = queue.Queue()
        self._closed = threading.Event()
        self._close_reason = ""

    # Connection thread

    def open(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="control-link", daemon=True)
        self._thread.start()
        try:
            self._connection = self._call(self._open(), self._open_timeout_s + 5.0)
        except InvalidStatus as error:
            self.close()
            status = error.response.status_code
            raise LinkClosed(f"The control node refused the control connection with HTTP {status}") from error
        except (OSError, WebSocketException, TimeoutError, FutureTimeout) as error:
            self.close()
            raise LinkClosed(f"Cannot reach {self.url}: {type(error).__name__}: {error}") from error
        asyncio.run_coroutine_threadsafe(self._read(), self._loop)

    def receive(self, timeout_s: Optional[float] = None) -> Optional[ControlNodeMessage]:
        """The next frame, or None when none arrived within timeout_s; raises LinkClosed when the connection ends.

        A frame that does not decode raises its MalformedFrame or ProtocolVersionMismatch."""
        if self._connection is None:
            raise LinkClosed("The control connection is not open")
        try:
            item = self._received.get(timeout=timeout_s)
        except queue.Empty:
            return None
        if item is _CLOSED:
            self._received.put(_CLOSED)  # every later receive sees the end too
            raise LinkClosed(f"The control connection closed: {self._close_reason}")
        return decode_control_node_message(item)

    # Any thread

    @property
    def connected(self) -> bool:
        return self._connection is not None and not self._closed.is_set()

    def send(self, frame: ProtocolFrame) -> bool:
        if not self.connected:
            return False
        try:
            self._call(self._connection.send(encode(frame)), SEND_TIMEOUT_S)
            return True
        except (ConnectionClosed, OSError, RuntimeError, TimeoutError, FutureTimeout) as error:
            _logger.info("Send failed, the control connection is closed: %s", error or type(error).__name__)
            self._mark_closed(str(error) or type(error).__name__)
            return False

    def close(self) -> None:
        self._mark_closed("closed by the worker node")
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        if self._connection is not None:
            try:
                self._call(self._connection.close(), 5.0)
            except Exception:  # the connection is gone either way
                pass
        loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=5.0)
        if not loop.is_running():
            loop.close()

    # Event loop thread

    async def _open(self) -> ClientConnection:
        return await connect(
            self.url,
            open_timeout=self._open_timeout_s,
            max_size=MAX_FRAME_BYTES,
            user_agent_header="scenegems-worker-node",
            proxy=None,  # the control node is dialled directly, never through a proxy from the environment
        )

    async def _read(self) -> None:
        try:
            async for message in self._connection:
                self._received.put(message)
        except ConnectionClosed as error:
            self._mark_closed(str(error))
        except Exception as error:  # a broken connection ends the link, whatever broke it
            self._mark_closed(f"{type(error).__name__}: {error}")
        else:
            self._mark_closed("the control node closed the connection")

    def _mark_closed(self, reason: str) -> None:
        if not self._closed.is_set():
            self._close_reason = reason
            self._closed.set()
            self._received.put(_CLOSED)

    def _call(self, coroutine, timeout_s: float):
        if threading.current_thread() is self._thread:
            raise RuntimeError("ControlLink methods must not be called from its event loop")
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result(timeout=timeout_s)
