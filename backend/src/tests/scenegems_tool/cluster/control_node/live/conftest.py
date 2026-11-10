"""Live channel tests: a scripted WebSocket, a fake topic source and a manual monotonic clock.

The channel runs on the test's own event loop (anyio, asyncio backend); settle() lets every
ready task run without waiting on the wall clock.
"""

import asyncio
import json
from typing import Any, Dict, List, Optional

import anyio
import pytest

from scenegems_tool.cluster.control_node.live.live_channel import LiveChannel, LiveSettings, UnknownTopic
from scenegems_tool.cluster.protocol.live import Topic, TopicKind
from tests.scenegems_tool.cluster.control_node.fake_worker_node import RECEIVE_TIMEOUT_S


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def settle(rounds: int = 50) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


class ManualMonotonic:
    def __init__(self, now: float = 100.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeWebSocket:
    """The browser's end: what it sends is queued for the channel, what the channel sends is kept, parsed."""

    def __init__(self) -> None:
        self.sent: List[Dict[str, Any]] = []
        self.closed: Optional[int] = None
        self.gate: Optional[asyncio.Event] = None  # while set to an unset event, sending blocks (a slow client)
        self._incoming: asyncio.Queue = asyncio.Queue()

    async def accept(self) -> None:
        pass

    async def send_text(self, text: str) -> None:
        if self.gate is not None:
            await self.gate.wait()
        self.sent.append(json.loads(text))

    async def receive(self) -> Dict[str, Any]:
        return await self._incoming.get()

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = code

    def client_sends(self, message: Dict[str, Any]) -> None:
        self._incoming.put_nowait({"type": "websocket.receive", "text": json.dumps(message)})

    def client_sends_text(self, text: str) -> None:
        self._incoming.put_nowait({"type": "websocket.receive", "text": text})

    def client_leaves(self) -> None:
        self._incoming.put_nowait({"type": "websocket.disconnect", "code": 1000})

    def subscribe(self, topic: str) -> None:
        self.client_sends({"version": 1, "type": "subscribe", "topic": topic})

    def unsubscribe(self, topic: str) -> None:
        self.client_sends({"version": 1, "type": "unsubscribe", "topic": topic})

    def take(self) -> List[Dict[str, Any]]:
        sent, self.sent = self.sent, []
        return sent


class FakeSource:
    """Serves job topics from a dict; a key in `slow` makes its snapshot wait until released."""

    def __init__(self) -> None:
        self.state: Dict[str, Any] = {}
        self.activated: List[str] = []
        self.deactivated: List[str] = []
        self.slow: Dict[str, asyncio.Event] = {}

    async def snapshot(self, topic: Topic) -> Any:
        if topic.key in self.slow:
            await self.slow[topic.key].wait()
        if topic.key not in self.state:
            raise UnknownTopic(f"no job {topic.key}")
        return self.state[topic.key]

    def activate(self, topic: Topic) -> None:
        self.activated.append(topic.name)

    def deactivate(self, topic: Topic) -> None:
        self.deactivated.append(topic.name)


@pytest.fixture
def source() -> FakeSource:
    source = FakeSource()
    source.state.update({"a": {"job_id": "a"}, "b": {"job_id": "b"}})
    return source


@pytest.fixture
def monotonic() -> ManualMonotonic:
    return ManualMonotonic()


@pytest.fixture
def make_channel(source, monotonic):
    def make(**settings) -> LiveChannel:
        channel = LiveChannel(LiveSettings(**settings), clock=monotonic)
        channel.add_source(TopicKind.JOB, source)
        return channel

    return make


class Browser:
    """One connection served by the channel in a task."""

    def __init__(self, channel: LiveChannel):
        self.socket = FakeWebSocket()
        self.task = asyncio.get_running_loop().create_task(channel.serve(self.socket))

    async def messages(self, count: int) -> List[Dict[str, Any]]:
        """Waits until `count` messages arrived (sources may read in worker threads) and takes every message sent."""
        with anyio.fail_after(RECEIVE_TIMEOUT_S):
            while len(self.socket.sent) < count:
                await asyncio.sleep(0.001)
        await settle()
        return self.socket.take()

    async def leave(self) -> None:
        self.socket.client_leaves()
        await self.task
