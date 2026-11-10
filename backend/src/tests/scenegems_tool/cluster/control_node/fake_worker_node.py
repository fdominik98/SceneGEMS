"""A scripted worker node on the control node's control WebSocket, speaking through the protocol codec."""

from contextlib import ExitStack
from typing import List, Optional, Type, TypeVar

import anyio
from starlette.testclient import TestClient

from scenegems_tool.cluster.protocol.codec import decode_control_node_message, encode
from scenegems_tool.cluster.protocol.jobs import JobOutcome
from scenegems_tool.cluster.protocol.messages import (
    ControlNodeMessage,
    Heartbeat,
    Hello,
    JobResult,
    LeaseAccept,
    LeaseOffer,
    LeaseReject,
    LeaseRenew,
    LeaseRenewed,
    ProtocolError,
    ProtocolErrorCode,
    Welcome,
)
from scenegems_tool.cluster.protocol.model_base import ProtocolFrame
from scenegems_tool.cluster.protocol.routes import WORKER_NODE_CONTROL_PATH
from tests.scenegems_tool.persistence.stores.builders import make_resources

RECEIVE_TIMEOUT_S = 10.0  # a guard against a test that waits for a frame that never comes; never reached when the test passes

Frame = TypeVar("Frame")


async def _receive_within(stream, timeout_s: float):
    with anyio.fail_after(timeout_s):
        return await stream.receive()


class FakeWorkerNode:
    def __init__(self, client: TestClient, hello: Hello):
        self.client = client
        self.hello_frame = hello
        self.worker_node_id = hello.worker_node_id
        self._stack = ExitStack()
        self.socket = None

    def open(self) -> "FakeWorkerNode":
        self.socket = self._stack.enter_context(self.client.websocket_connect(WORKER_NODE_CONTROL_PATH))
        return self

    def connect(self, running_lease_ids: List[str] = ()) -> Welcome:
        """Opens the socket, sends Hello and returns the Welcome."""
        self.open()
        self.send(self.hello_frame.model_copy(update={"running_lease_ids": list(running_lease_ids)}))
        return self.expect(Welcome)

    def close(self) -> None:
        self._stack.close()
        self.socket = None

    def send(self, frame: ProtocolFrame) -> None:
        self.socket.send_text(encode(frame))

    def send_text(self, text: str) -> None:
        self.socket.send_text(text)

    def receive_message(self) -> dict:
        # The test session's receive has no timeout; this reads its stream with one.
        return self.socket.portal.call(_receive_within, self.socket._send_rx, RECEIVE_TIMEOUT_S)

    def receive(self) -> ControlNodeMessage:
        message = self.receive_message()
        assert message["type"] == "websocket.send", f"expected a frame, the control node sent {message}"
        return decode_control_node_message(message["text"])

    def expect(self, frame_type: Type[Frame]) -> Frame:
        frame = self.receive()
        assert isinstance(frame, frame_type), f"expected {frame_type.__name__}, got {frame!r}"
        return frame

    def expect_close(self) -> int:
        message = self.receive_message()
        assert message["type"] == "websocket.close", f"expected the control node to close, got {message}"
        return message["code"]

    def sync(self) -> None:
        """Returns once the control node has handled every frame sent before.

        The control node handles a worker node's frames one after the other and answers a malformed one
        with ProtocolError, so that answer is a barrier for frames that get none.
        """
        self.send_text("barrier")
        error = self.expect(ProtocolError)
        assert error.code == ProtocolErrorCode.MALFORMED_FRAME, error

    # Steps of a worker node's life; each returns once the control node has handled it

    def send_and_sync(self, frame: ProtocolFrame) -> None:
        self.send(frame)
        self.sync()

    def heartbeat(self, running_lease_ids: List[str] = (), free_memory_mb: int = 12000, load_average: float = 0.1) -> None:
        self.send_and_sync(Heartbeat(resources=make_resources(free_memory_mb=free_memory_mb).model_copy(update={"load_average": load_average}), running_lease_ids=list(running_lease_ids)))

    def accept(self, offer: LeaseOffer) -> LeaseRenewed:
        self.send(LeaseAccept(lease_id=offer.lease_id))
        return self.expect(LeaseRenewed)

    def reject(self, offer: LeaseOffer, reason: str = "busy") -> None:
        self.send_and_sync(LeaseReject(lease_id=offer.lease_id, reason=reason))

    def renew(self, lease_id: str) -> ControlNodeMessage:
        self.send(LeaseRenew(lease_id=lease_id))
        return self.receive()

    def succeed(self, offer: LeaseOffer, result: Optional[dict] = None) -> None:
        self.send_and_sync(self.result(offer, JobOutcome.SUCCEEDED, result=result or {"done_by": self.worker_node_id}))

    def result(self, offer: LeaseOffer, outcome: JobOutcome, result: Optional[dict] = None, error: Optional[str] = None, retryable: bool = False) -> JobResult:
        job = offer.job
        return JobResult(lease_id=offer.lease_id, job_id=job.job_id, idempotency_key=job.idempotency_key, outcome=outcome, result=result or {}, error=error, retryable=retryable)
