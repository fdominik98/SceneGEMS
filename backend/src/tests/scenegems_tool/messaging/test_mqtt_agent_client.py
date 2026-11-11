"""The ArduAgent client: the conversion of normalized thrust to RC override PWM, and the planned path it draws on a WARA-PS map."""

import pytest

from scenegems_tool.messaging.mqtt_agent_client import MqttAgentClient, normalized_to_pwm
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, encounter_trajectories


class TestNormalizedToPwm:
    @pytest.mark.parametrize("value,pwm", [(0.0, 1500), (1.0, 2000), (-1.0, 1000), (0.5, 1750), (-0.5, 1250)])
    def test_maps_to_the_standard_range(self, value, pwm):
        assert normalized_to_pwm(value) == pwm

    @pytest.mark.parametrize("value,pwm", [(2.0, 2000), (-7.5, 1000)])
    def test_values_outside_are_clamped(self, value, pwm):
        assert normalized_to_pwm(value) == pwm

    def test_result_is_an_integer(self):
        assert isinstance(normalized_to_pwm(0.123), int)


class RecordingPaho:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, qos=0):
        self.published.append(topic)


def agent_client(topic_root: str) -> MqttAgentClient:
    scene = encounter_trajectories("head_on", 10).initial_scene
    vessel = scene.get_by_id("0")
    connection = MQttConnectionInfo("user", "password", "broker", "broker", 1883, False, False, topic_root=topic_root)
    client = MqttAgentClient(vessel, connection, f"{topic_root}/unit/surface/simulation/os-1", "autonomous", "os-1", GEOFENCE, scene[vessel], "simulation-subsystem-1", [])
    client.client = RecordingPaho()
    return client


def test_the_planned_path_is_drawn_on_a_waraps_broker_only():
    on_waraps = agent_client("waraps")
    on_waraps.publish_trajectory([[57.7, 11.9]])
    assert on_waraps.client.published == ["waraps/general/generic/real/c2/target/positions/os-1_PATH"]
    on_the_cluster = agent_client("scenegems")
    on_the_cluster.publish_trajectory([[57.7, 11.9]])
    assert on_the_cluster.client.published == [], "a control node's own broker has no map to draw on"
