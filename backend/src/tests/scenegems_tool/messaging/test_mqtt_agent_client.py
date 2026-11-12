"""The ArduAgent client: the planned path it draws on a WARA-PS map."""

from scenegems_tool.messaging.mqtt_agent_client import MqttAgentClient
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, encounter_trajectories


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
