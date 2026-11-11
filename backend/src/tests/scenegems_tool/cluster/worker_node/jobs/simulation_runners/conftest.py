import pytest

from scenegems_tool.cluster.worker_node import instance_scope


@pytest.fixture
def instances_folder(monkeypatch, tmp_path):
    """The folder the worker node keeps its job stacks in, and the default simulation subsystem image."""
    monkeypatch.setattr(instance_scope, "INSTANCES_FOLDER", str(tmp_path).replace("\\", "/"))
    monkeypatch.delenv("SIMULATION_IMAGE", raising=False)
    return tmp_path
