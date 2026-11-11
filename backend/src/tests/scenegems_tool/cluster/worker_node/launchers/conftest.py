import pytest

from scenegems_tool.cluster.worker_node.launchers.pooled.monitor_service import MonitorService
from scenegems_tool.cluster.worker_node.launchers.pooled.pooled_service import PooledService
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence


@pytest.fixture
def no_docker(monkeypatch):
    """Build launchers without starting containers: the startup thread does nothing."""
    for launcher in (PooledService, MonitorService):
        monkeypatch.setattr(launcher, "_run_container_lifecycle_startup", lambda self, compose: None)
    monkeypatch.delenv("SCENEGEMS_DOCKER_NETWORK", raising=False)
    for variable in ("SCENE_GENERATION_IMAGE", "TRAJECTORY_GENERATION_IMAGE", "MONITORING_IMAGE", "SIMULATION_IMAGE"):
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture
def mqtt_connection() -> MQttConnectionInfo:
    return MQttConnectionInfo("user", "secret", "broker", "localhost", 1883, False, False)


@pytest.fixture
def geofence() -> Geofence:
    return Geofence(57.7, 11.9, 2000.0)
