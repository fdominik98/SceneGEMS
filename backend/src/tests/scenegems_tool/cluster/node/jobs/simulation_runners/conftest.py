import pytest

from scenegems_tool.cluster.node import instance_scope


@pytest.fixture
def instances_folder(monkeypatch, tmp_path):
    """The folder the node keeps its job stacks in, and the default scenario execution image."""
    monkeypatch.setattr(instance_scope, "INSTANCES_FOLDER", str(tmp_path).replace("\\", "/"))
    monkeypatch.delenv("SCENARIO_EXECUTION_IMAGE", raising=False)
    return tmp_path
