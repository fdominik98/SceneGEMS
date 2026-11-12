import pytest

from concrete_level.models.trajectories import Trajectories
from scenegems_tool.cluster.worker_node import instance_scope


@pytest.fixture
def instances_folder(monkeypatch, tmp_path):
    """The folder the worker node keeps its job stacks in, and the default simulation subsystem image."""
    monkeypatch.setattr(instance_scope, "INSTANCES_FOLDER", str(tmp_path).replace("\\", "/"))
    monkeypatch.delenv("SIMULATION_IMAGE", raising=False)
    return tmp_path


@pytest.fixture
def post_hoc():
    """What monitoring.post_hoc gives for a recorded run: its trajectories judged as one series by the monitor of the monitoring pool's worker, in process."""

    def judge(trajectories: dict) -> dict:
        from scenegems_tool.subsystems.monitoring.monitoring_worker import SeriesMonitor

        run = Trajectories.from_dict(trajectories)
        monitor = SeriesMonitor("post-hoc", run.time_step)
        monitor.add(run.scene_list)
        return {"scenes": monitor.scenes, "monitored_scenes": monitor.monitored_scenes, "time_step": monitor.time_step, **monitor.summary()}

    return judge
