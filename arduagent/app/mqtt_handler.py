import json
import time
import uuid
from enum import Enum

from config import AgentConfig
from connections import MqttConnection


class TaskStatus(str, Enum):
    STARTING = "starting"
    PLANNING = "planning"
    RUNNING = "running"
    FAILED = "failed"
    FINISHED = "finished"
    ABORTED = "aborted"
    PAUSED = "paused"
    ENOUGH = "enough"
    CONTINUE = "continue"
    PILOT_TAKEOVER = "takeover by pilot"
    PING = "ping"
    PONG = "pong"


class Mqtt:
    def __init__(self) -> None:
        self.mqtt_connection: MqttConnection = MqttConnection()
        self.client = self.mqtt_connection.client

    def send_heartbeat(self, rate: float) -> None:
        payload = {
            "name": AgentConfig.NAME,
            "agent-uuid": AgentConfig.UUID,
            "agent-type": AgentConfig.DOMAIN,
            "agent-description": AgentConfig.AGENT_DESCRIPTION,
            "agent-model": AgentConfig.AGENT_MODEL,
            "levels": ["sensor", "direct execution", "tst execution"],
            "rate": round(rate, 1),
            "stamp": round(time.time(), 3),
            "type": "HeartBeat",
        }
        self.client.publish(
            f"{AgentConfig.BASE_TOPIC}/heartbeat", json.dumps(payload)
        )

    def send_sensor_info(self, rate: float) -> None:
        payload = {
            "sensor-data-provided": [
                "position",
                "speed",
                "course",
                "heading",
                "mode",
                "state",
                "waypoints",
                "energy_level",
                "battery_status",
                "cargo",
                "control_system_version",
                "clock",
            ],
            "name": AgentConfig.NAME,
            "rate": round(rate, 1),
            "stamp": time.time(),
            "type": "SensorInfo",
        }

        if AgentConfig.VIDEO_SERVER:
            payload["sensor-data-provided"].append("videoserver_url")

        self.client.publish(
            f"{AgentConfig.BASE_TOPIC}/sensor_info", json.dumps(payload)
        )

    def send_direct_execution_info(self, rate: float) -> None:
        payload = {
            "tasks-available": [
                {
                    "name": "move-to",
                    "signals": ["$abort", "$enough", "$continue", "$pause"],
                },
                {
                    "name": "move-path",
                    "signals": ["$abort", "$enough", "$continue", "$pause"],
                },
                {
                    "name": "go-home",
                    "signals": ["$abort", "$enough", "$continue", "$pause"],
                },
                {
                    "name": "search-area",
                    "signals": ["$abort", "$enough", "$continue", "$pause"],
                },
                {
                    "name": "set-heading-thrust",
                    "signals": ["$abort", "$enough", "$continue", "$pause"],
                },
                {"name": "collect", "signals": ["$abort"]},
                {"name": "release", "signals": ["$abort"]},
                {
                    "name": "follow-lead",
                    "signals": ["$abort", "$enough", "$continue", "$pause"],
                },
                {"name": "set-geofence", "signals": []},
                {"name": "add-no-go-zone", "signals": []},
            ],
            "tasks-executing": [],
            "name": AgentConfig.NAME,
            "rate": round(rate, 1),
            "stamp": time.time(),
            "type": "DirectExecutionInfo",
        }
        self.client.publish(
            f"{AgentConfig.BASE_TOPIC}/direct_execution_info",
            json.dumps(payload),
        )
        
    def send_clock(self, val: float) -> None:
        self.client.publish(f"{AgentConfig.BASE_TOPIC}/sensor/clock", val)

    def send_position(self, val: list) -> None:
        if not val or len(val) != 3:
            return

        # Defaults
        lat: float = 0.0
        lon: float = 0.0
        alt: float = 0.0

        try:
            # Attempt to convert each value to a float
            lat = round(float(val[0]), 7)
            lon = round(float(val[1]), 7)
            alt = round(float(val[2]), 3)
        except (ValueError, TypeError):
            pass  # Using defaults

        payload = {
            "latitude": lat,
            "longitude": lon,
            "altitude": alt,
        }

        self.client.publish(
            f"{AgentConfig.BASE_TOPIC}/sensor/position", json.dumps(payload)
        )

    def send_speed(self, val: float) -> None:
        if not val:
            return

        payload = round(val, 1)
        self.client.publish(f"{AgentConfig.BASE_TOPIC}/sensor/speed", payload)

    def send_course(self, val: float) -> None:
        if not val:
            return

        payload = round(val, 1)
        self.client.publish(f"{AgentConfig.BASE_TOPIC}/sensor/course", payload)

    def send_heading(self, val: float) -> None:
        if not val:
            return

        payload = round(val, 1)
        self.client.publish(f"{AgentConfig.BASE_TOPIC}/sensor/heading", payload)

    def send_waypoints(self, val: list = None) -> None:
        wps: list = []

        # print(f"{val=}")

        if isinstance(val, list) and len(val) > 1:
            wps = [
                {
                    "latitude": round(pos[0], 7),
                    "longitude": round(pos[1], 7),
                    "altitude": round(pos[2], 7),
                    "rostype": "GeoPoint",
                }
                for pos in val
                if len(pos) == 3
            ]

        # print(f"{wps=}")

        # Clean up
        if len(wps) < 2:
            wps = []

        self.client.publish(
            f"{AgentConfig.BASE_TOPIC}/sensor/waypoints", json.dumps(wps)
        )

    def send_waypoints_old(self, val: list) -> None:
        if not val or not isinstance(val, list):
            return

        # payload = val if len(val) > 1 and len(val[0]) == 3 and len(val[1]) == 3 else []
        if len(val) > 1 and len(val[0]) == 3 and len(val[1]) == 3:
            payload = {
                "waypoints": [
                    {
                        "latitude": val[0][0],
                        "longitude": val[0][1],
                        "altitude": val[0][2],
                        "rostype": "GeoPoint",
                    },
                    {
                        "latitude": val[1][0],
                        "longitude": val[1][1],
                        "altitude": val[1][2],
                        "rostype": "GeoPoint",
                    },
                ]
            }

        else:
            payload = {"waypoints": []}

        self.client.publish(
            f"{AgentConfig.BASE_TOPIC}/sensor/waypoints", json.dumps(payload)
        )

    def send_ipaddress(self, val: str = "0.0.0.0") -> None:
        """Send the IP address to the MQTT broker."""
        self.client.publish(f"{AgentConfig.BASE_TOPIC}/sensor/ipaddress", val)

    def send_energy_level(self, val: float) -> None:
        if not val:
            return

        self.client.publish(
            f"{AgentConfig.BASE_TOPIC}/sensor/energy_level", val
        )

    def send_battery_status(self, val: str) -> None:
        if not val:
            return

        self.client.publish(
            f"{AgentConfig.BASE_TOPIC}/sensor/battery_status", json.dumps(val)
        )

    def send_mode(self, val: str) -> None:
        if not val or not isinstance(val, str):
            return

        self.client.publish(
            f"{AgentConfig.BASE_TOPIC}/sensor/mode", val.lower()
        )

    def send_state(self, val: str) -> None:
        if not val or not isinstance(val, str):
            return

        self.client.publish(
            f"{AgentConfig.BASE_TOPIC}/sensor/state", val.lower()
        )

    def send_armable(self, val: bool) -> None:
        self.client.publish(
            f"{AgentConfig.BASE_TOPIC}/sensor/armable", str(val)
        )

    def send_videoserver_url(self) -> None:
        if not AgentConfig.VIDEO_SERVER:
            return

        vs_url = f"wss://{AgentConfig.VIDEO_SERVER}:3334/app/{AgentConfig.NAME}"

        self.client.publish(
            f"{AgentConfig.BASE_TOPIC}/sensor/videoserver_url", vs_url
        )

    def send_control_system_version(self, val: str) -> None:
        if not val or not isinstance(val, str):
            return

        self.client.publish(
            f"{AgentConfig.BASE_TOPIC}/sensor/control_system_version", val
        )

    def send_cargo(self, val: list) -> None:
        payload: list = []

        if val:
            for item in val:
                c_item: dict = {}
                c_item["name"] = item
                payload.append(c_item)

        self.client.publish(
            f"{AgentConfig.BASE_TOPIC}/sensor/cargo", json.dumps(payload)
        )

    def send_speed_preset(self, val: dict) -> None:
        if not val or not isinstance(val, dict):
            return

        payload: dict = val

        self.client.publish(
            f"{AgentConfig.BASE_TOPIC}/sensor/speed_preset", json.dumps(payload)
        )

    # COMMAND/RESPONSE/FEEDBACK publishers =============================================

    def send_response(
        self, val: str, tuuid: str = "", cuuid: str = "", reason: str = ""
    ) -> None:
        payload = {
            "agent-uuid": AgentConfig.UUID,
            "com-uuid": str(uuid.uuid4()),
            "fail-reason": reason,
            "response": val,
            # "response-to": cuuid,
            # "task-uuid": tuuid,
        }

        if cuuid:
            payload["response-to"] = cuuid

        if tuuid:
            payload["task-uuid"] = tuuid

        self.client.publish(
            f"{AgentConfig.BASE_TOPIC}/exec/response", json.dumps(payload)
        )
        # print(f"SENT RESPONSE! : {payload}")

    def send_feedback(self, val: str, tuuid: str = "") -> None:
        payload = {
            "agent-uuid": AgentConfig.UUID,
            "com-uuid": str(uuid.uuid4()),
            "status": val,
            # "task-uuid": tuuid,
        }

        if tuuid:
            payload["task-uuid"] = tuuid

        self.client.publish(
            f"{AgentConfig.BASE_TOPIC}/exec/feedback", json.dumps(payload)
        )
        # print(f"SENT FEEDBACK! : {payload}")

    def send_info(self, val: str) -> None:
        if not val or not isinstance(val, str):
            return

        self.client.publish(f"{AgentConfig.BASE_TOPIC}/sensor/info", val)

    def terminate(self) -> None:
        """Terminate MQTTConnection."""
        self.mqtt_connection.disconnect()
