import json
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from queue import Queue
from typing import Any, List, Optional

import numpy as np
import paho.mqtt.client as mqtt

from concrete_level.models.actor_state import ActorState
from scenegems_tool.waraps_integration.mqtt_client import MqttClient, MQttConnectionInfo
from scenegems_tool.waraps_integration.sim_utils import Geofence, to_true_north


class TaskStatus(str, Enum):
    STARTING = "starting"
    PLANNING = "planning"
    RUNNING = "running"
    FAILED = "failed"
    FINISHED = "finished"
    ABORTED = "aborted"


@dataclass()
class Task:
    uuid: str
    name: str
    status: TaskStatus
    command_uuid: str
    waypoints: List[dict]
    speed_ref: float


class MqttAgentService(MqttClient):
    def __init__(self, mqtt_connection: MQttConnectionInfo, topic: str, agent_name: str, reference_geofence: Geofence, parent_service_name: str):
        self.current_task_queue: Queue[Task] = Queue()
        self.parent_service_name = parent_service_name
        self.info_update_rate = 1.0
        self.simulation_clock = 0
        super().__init__(agent_name, topic, mqtt_connection, reference_geofence)

    @property
    def listen_topics(self) -> List[str]:
        return [self.exec_command_topic]

    def publish_task_status(self, current_task: Task):
        if current_task is not None:
            response_command = {
                "agent-uuid": self.uuid,
                "com-uuid": str(uuid.uuid4()),
                "task-uuid": current_task.uuid,
                "fail-reason": "",
                "response-to": current_task.command_uuid,
                "response": current_task.status,
            }
            str_response_command = json.dumps(response_command)
            self.client.publish(self.exec_response_topic, str_response_command, qos=1)
            feedback_command = {"agent-uuid": self.uuid, "com-uuid": str(uuid.uuid4()), "task-uuid": current_task.uuid, "status": current_task.status}
            str_feedback_command = json.dumps(feedback_command)
            self.client.publish(self.exec_feedback_topic, str_feedback_command, qos=1)

    def _on_message(self, msg: mqtt.MQTTMessage, payload: Any):
        match payload["command"]:
            case "start-task":
                if payload["execution-unit"] != self.name:
                    return
                match payload["task"]["name"]:
                    case "move-to":
                        task = Task(
                            uuid=str(payload["task-uuid"]),
                            name=str(payload["command"]),
                            status=TaskStatus.STARTING,
                            command_uuid=str(payload["com-uuid"]),
                            waypoints=[payload["task"]["params"]["waypoint"]],
                            speed_ref=float(payload["task"]["params"]["speed"]),
                        )
                    case "move-path":
                        task = Task(
                            uuid=str(payload["task-uuid"]),
                            name=str(payload["command"]),
                            status=TaskStatus.STARTING,
                            command_uuid=str(payload["com-uuid"]),
                            waypoints=payload["task"]["params"]["waypoints"],
                            speed_ref=float(payload["task"]["params"]["speed"]),
                        )
                self.current_task_queue.put(task)
                self.publish_task_status(task)
            case "signal-task":
                signal = payload["signal"]
                uuid = payload["task-uuid"]
                if signal == "$abort":
                    task = Task(uuid=uuid, name=signal, status=TaskStatus.ABORTED, command_uuid=str(payload["com-uuid"]), waypoints=[], speed_ref=0.0)
                    self.current_task_queue.put(task)
                    self.publish_task_status(task)

    def publish_state(self, current_agent_state: ActorState, waypoints: List[dict], current_task: Optional[Task]):
        heartbeat_command = {
            "name": self.name,
            "agent-type": "surface",
            "agent-description": "surface vessel",
            "agent-uuid": self.uuid,
            "levels": ["sensor", "direct execution", "tst execution"],
            "rate": self.info_update_rate,
            "stamp": time.time(),
            "type": "HeartBeat",
        }
        str_heartbeat_command = json.dumps(heartbeat_command)
        self.client.publish(self.heartbeat_topic, str_heartbeat_command, qos=1)

        sensor_info_command = {
            "name": self.name,
            "rate": self.info_update_rate,
            "sensor-data-provided": [
                "position",
                "speed",
                "course",
                "heading",
                "clock",
                "mode",
                "state",
                "waypoints",
                "energy_level",
                "battery_status",
                "cargo",
                "control_system_version",
                "videoserver_url",
            ],
            "stamp": time.time(),
            "type": "SensorInfo",
        }
        str_sensor_info_command = json.dumps(sensor_info_command)
        self.client.publish(self.sensor_info_topic, str_sensor_info_command, qos=1)

        tasks_executing: List[dict] = []
        if current_task is not None:
            tasks_executing.append(
                {
                    "name": current_task.name,
                    "uuid": current_task.uuid,
                }
            )
        direct_execution_info_command = {
            "name": self.name,
            "rate": self.info_update_rate,
            "type": "DirectExecutionInfo",
            "stamp": time.time(),
            "tasks-available": [
                {"name": "move-to", "signals": ["$abort", "$enough", "$continue", "$pause"]},
                {"name": "move-path", "signals": ["$abort", "$enough", "$continue", "$pause"]},
            ],
            "tasks-executing": tasks_executing,
        }
        str_direct_execution_info_command = json.dumps(direct_execution_info_command)
        self.client.publish(self.direct_execution_topic, str_direct_execution_info_command, qos=1)

        lat_long = self.reference_geofence.to_lat_long(current_agent_state.p)
        position_command = {
            "latitude": lat_long[0],
            "longitude": lat_long[1],
            "altitude": 0.0,
        }
        battery_status_command = {"voltage": 12.487, "current": 8, "level": 0}
        heading = np.degrees(to_true_north(current_agent_state.heading))
        str_position_command = json.dumps(position_command)
        self.client.publish(self.position_topic, str_position_command, qos=1)
        self.client.publish(self.speed_topic, current_agent_state.speed, qos=1)
        self.client.publish(self.heading_topic, heading, qos=1)
        self.client.publish(self.course_topic, heading, qos=1)
        self.client.publish(self.mode_topic, "auto", qos=1)
        self.client.publish(self.state_topic, "armed", qos=1)
        self.client.publish(self.energy_level_topic, 1, qos=1)
        self.client.publish(self.battery_status_topic, json.dumps(battery_status_command), qos=1)
        self.client.publish(self.cargo_topic, json.dumps([]), qos=1)
        self.client.publish(self.control_system_version_topic, "APM:UnknownVehicleType11-4.5.7", qos=1)
        self.client.publish(self.videoserver_url_topic, "", qos=1)
        self.client.publish(self.waypoints_topic, json.dumps(waypoints), qos=1)
        self.client.publish(self.ip_address_topic, "localhost", qos=1)
        self.client.publish(self.armable_topic, True, qos=1)
        self.client.publish(self.clock_topic, self.simulation_clock, qos=1)
