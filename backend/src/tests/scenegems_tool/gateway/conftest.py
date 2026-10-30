import asyncio
from typing import List

import pytest

from scenegems_tool.subsystems.scenario_execution import empty_simulation_session


class FakeWebSocket:
    """The part of a Starlette WebSocket that SocketSession uses."""

    def __init__(self) -> None:
        self.sent: List[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def no_docker_teardown(monkeypatch):
    """An empty simulation session schedules a Docker teardown of its session's stack or of leftover stacks; keep both off the engine."""
    monkeypatch.setattr(empty_simulation_session, "schedule_force_destroy_session_stack", lambda *_, **__: None)
    monkeypatch.setattr(empty_simulation_session, "schedule_leftover_sweep", lambda *_, **__: None)


@pytest.fixture
def websocket() -> FakeWebSocket:
    return FakeWebSocket()


async def settle(cycles: int = 25) -> None:
    """Let queued tasks run: yields to the event loop without waiting on the wall clock."""
    for _ in range(cycles):
        await asyncio.sleep(0)
