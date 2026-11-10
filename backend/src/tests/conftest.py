from pathlib import Path

import pytest

from tests.snapshots import SnapshotChecker


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--update-snapshots", action="store_true", default=False, help="rewrite the snapshot files under data/ folders with the generated output")


@pytest.fixture
def snapshot(request: pytest.FixtureRequest) -> SnapshotChecker:
    """Snapshots of the requesting test live in the data/ folder next to its file."""
    return SnapshotChecker(Path(request.path).parent / "data", update=bool(request.config.getoption("--update-snapshots")))


@pytest.fixture(autouse=True)
def stack_layers_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """A unit test has no stack of containers next to it, so code that runs inside a stack (a job's runner, a live session's
    driver) hosts the layers in the test's process. The tests of the containers pass a ContainerHosting themselves."""
    from scenegems_tool.vessel_stack import hosting

    monkeypatch.setattr(hosting, "in_stack_hosting", hosting.InProcessHosting)
