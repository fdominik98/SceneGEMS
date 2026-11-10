"""A browser on the live channel of a control node's test client, with a receive timeout."""

import json
from contextlib import ExitStack
from typing import Any, Dict, List

from starlette.testclient import TestClient

from scenegems_tool.cluster.protocol.routes import LIVE_PATH
from tests.scenegems_tool.cluster.control_node.fake_worker_node import RECEIVE_TIMEOUT_S, _receive_within


class LiveBrowser:
    def __init__(self, client: TestClient):
        self._stack = ExitStack()
        self.socket = self._stack.enter_context(client.websocket_connect(LIVE_PATH))

    def send(self, message: Dict[str, Any]) -> None:
        self.socket.send_text(json.dumps({"version": 1, **message}))

    def receive(self) -> Dict[str, Any]:
        message = self.socket.portal.call(_receive_within, self.socket._send_rx, RECEIVE_TIMEOUT_S)
        assert message["type"] == "websocket.send", f"expected a message, the control node sent {message}"
        return json.loads(message["text"])

    def subscribe(self, topic: str) -> Any:
        """Subscribes and returns the snapshot."""
        self.send({"type": "subscribe", "topic": topic})
        message = self.receive()
        assert message["type"] == "subscribed" and message["topic"] == topic, message
        return message["snapshot"]

    def expect_update(self, topic: str) -> Dict[str, Any]:
        message = self.receive()
        assert message["type"] == "update" and message["topic"] == topic, message
        return message["data"]

    def drain(self) -> List[Dict[str, Any]]:
        """Every message sent before a ping's pong: the channel keeps a connection's messages in order."""
        self.send({"type": "ping"})
        messages = []
        while True:
            message = self.receive()
            if message["type"] == "pong":
                return messages
            messages.append(message)

    def close(self) -> None:
        self._stack.close()
