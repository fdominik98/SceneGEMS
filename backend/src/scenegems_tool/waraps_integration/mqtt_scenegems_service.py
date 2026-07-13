import json
import time
from typing import Any, List

import paho.mqtt.client as mqtt

from scenegems_tool.waraps_integration.mqtt_client import MqttClient, MQttConnectionInfo
from scenegems_tool.waraps_integration.sim_utils import Geofence


class MqttSceneGEMSService(MqttClient):
    def __init__(self, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence):
        self.info_update_rate = 1.0
        name = "scenegems_service"
        super().__init__(name, f"waraps/service/virtual/real/{name}", mqtt_connection, reference_geofence)

    def _on_message(self, msg: mqtt.MQTTMessage, payload: Any):
        if payload["execution-unit"] != self.name:
            return

    @property
    def listen_topics(self) -> List[str]:
        return [
            self.exec_command_topic,
        ]

    def publish_heartbeat_and_sensor_info(self):
        heartbeat_command = {
            "name": self.name,
            "agent-type": "virtual",
            "agent-description": "Scenario Explorer Service",
            "agent-uuid": self.uuid,
            "levels": [
                "sensor",
                "direct execution",
            ],
            "rate": self.info_update_rate,
            "stamp": time.time(),
            "type": "HeartBeat",
        }
        str_heartbeat_command = json.dumps(heartbeat_command)
        self.client.publish(self.heartbeat_topic, str_heartbeat_command, qos=1)
        sensor_info_command = {
            "name": self.name,
            "rate": self.info_update_rate,
            "sensor-data-provided": [],
            "stamp": time.time(),
            "type": "SensorInfo",
        }

        str_sensor_info_command = json.dumps(sensor_info_command)
        self.client.publish(self.sensor_info_topic, str_sensor_info_command, qos=1)

        direct_execution_info_command = {
            "name": self.name,
            "rate": self.info_update_rate,
            "type": "DirectExecutionInfo",
            "stamp": time.time(),
            "tasks-available": [],
            "tasks-executing": [],
        }
        str_direct_execution_info_command = json.dumps(direct_execution_info_command)
        self.client.publish(self.direct_execution_topic, str_direct_execution_info_command, qos=1)
