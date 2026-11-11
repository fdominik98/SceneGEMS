import asyncio
from typing import List

import pytest


class FakeWebSocket:
    """The part of a Starlette WebSocket that SocketSession uses."""

    def __init__(self) -> None:
        self.sent: List[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def websocket() -> FakeWebSocket:
    return FakeWebSocket()


async def settle(cycles: int = 25) -> None:
    """Let queued tasks run: yields to the event loop without waiting on the wall clock."""
    for _ in range(cycles):
        await asyncio.sleep(0)
