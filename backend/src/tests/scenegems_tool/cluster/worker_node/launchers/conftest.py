import pytest

from scenegems_tool.cluster.worker_node.subsystem import IMAGE_ENVIRONMENT_VARIABLES
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence


@pytest.fixture
def release_images(monkeypatch):
    """The pools run the release's images: no image override and no image tag from the test's environment."""
    for variable in [*IMAGE_ENVIRONMENT_VARIABLES.values(), "SITL_IMAGE", "GAZEBO_IMAGE", "SCENEGEMS_IMAGE_TAG"]:
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture
def mqtt_connection() -> MQttConnectionInfo:
    return MQttConnectionInfo("user", "secret", "broker", "localhost", 1883, False, False)


@pytest.fixture
def geofence() -> Geofence:
    return Geofence(57.7, 11.9, 2000.0)
