import json
import uuid
from enum import Enum
from typing import Any, List, Optional, Tuple

import numpy as np
import paho.mqtt.client as mqtt
from haversine import Unit

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.waraps_integration.mqtt_client import MqttClient, MQttConnectionInfo
from scenegems_tool.waraps_integration.sim_utils import Geofence, from_true_north, normalized_to_pwm


class ExecutionState(Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    MOVING_TO_START_POINT = "moving_to_start_point"


class MqttAgentClient(MqttClient):
    def __init__(
        self,
        vessel: ConcreteVessel,
        mqtt_connection: MQttConnectionInfo,
        topic: str,
        control_mode: str,
        agent_name: str,
        reference_geofence: Geofence,
        initial_state: ActorState,
        parent_service_name: str,
        mission_waypoints: List[dict],
    ):
        self.actor = vessel
        self.initial_state = initial_state
        self.execution_state = ExecutionState.STOPPED
        self.current_agent_state = ActorState(x=initial_state.x, y=initial_state.y, speed=initial_state.speed, heading=initial_state.heading)
        self.parent_service_name = parent_service_name
        self.is_armable = False
        self.current_task_uuid = ""
        self.current_task_name = ""
        self.mission_waypoints = mission_waypoints
        self.control_mode = control_mode
        self.position_received = False
        self.clock = 0.0
        super().__init__(agent_name, topic, mqtt_connection, reference_geofence)

    @property
    def external_control_mode(self) -> bool:
        return self.control_mode == "external"

    @property
    def autonomous_control_mode(self) -> bool:
        return self.control_mode == "autonomous"

    @property
    def listen_topics(self) -> List[str]:
        return [
            self.exec_response_topic,
            self.exec_feedback_topic,
            self.position_topic,
            self.heading_topic,
            self.speed_topic,
            self.armable_topic,
            self.clock_topic,
        ]

    def _on_message(self, msg: mqtt.MQTTMessage, payload: Any):
        if msg.topic == self.position_topic:
            if payload["latitude"] is None or payload["longitude"] is None:
                return
            self.position_received = True
            # print(f"{self.vessel_name} latitude: {payload['latitude']}, longitude: {payload['longitude']}")
            p = self.reference_geofence.to_coord(payload["latitude"], payload["longitude"])
            self.current_agent_state = ActorState.modify_copy(self.current_agent_state, x=p[0], y=p[1])
            # print(f"{self.vessel_name} Position: {self.current_vessel_state.p}")
        elif msg.topic == self.heading_topic:
            heading = np.radians(from_true_north(float(payload), unit=Unit.DEGREES))
            self.current_agent_state = ActorState.modify_copy(self.current_agent_state, heading=heading)
        elif msg.topic == self.speed_topic:
            speed = float(payload)
            self.current_agent_state = ActorState.modify_copy(self.current_agent_state, speed=speed)
        elif msg.topic == self.armable_topic:
            self.is_armable = bool(payload)
        elif msg.topic == self.clock_topic:
            if payload is not None:
                self.clock = float(payload)
        elif msg.topic == self.exec_response_topic:
            if payload["task-uuid"] == self.current_task_uuid:
                if payload["response"] in ["finished", "aborted", "failed"]:
                    self.execution_state = ExecutionState.STOPPED
                elif payload["response"] == "running":
                    if self.current_task_name in ["move-path", "move-to"]:
                        self.execution_state = ExecutionState.RUNNING

    @property
    def base_topic(self) -> str:
        return self.topic

    @property
    def trajectory_topic(self) -> str:
        return f"waraps/general/generic/real/c2/target/positions/{self.trajectory_name}"

    @property
    def trajectory_name(self) -> str:
        return f"{self.name}_PATH"

    def publish_follow_path(self, waypoints: List[dict], speed):
        command = {
            "com-uuid": str(uuid.uuid4()),
            "command": "start-task",
            "execution-unit": self.name,
            "sender": self.parent_service_name,
            "task": {
                "name": "move-path",
                "params": {
                    "speed": str(speed),
                    "waypoints": waypoints,
                    "loop": False,
                },
            },
            "task-uuid": str(uuid.uuid4()),
            "time_added": 0,
        }
        str_command = json.dumps(command)
        self.current_task_uuid = command["task-uuid"]
        self.current_task_name = command["task"]["name"]
        self.client.publish(self.exec_command_topic, str_command, qos=1)

    def publish_abort_all(self):
        for task in self.running_tasks:
            command = {
                "com-uuid": str(uuid.uuid4()),
                "command": "signal-task",
                "sender": self.parent_service_name,
                "signal": "$abort",
                "task-uuid": task,
            }
            str_command = json.dumps(command)
            self.current_task_uuid = command["task-uuid"]
            self.current_task_name = "abort"
            self.client.publish(self.exec_command_topic, str_command, qos=1)

    def publish_loiter_all(self):
        pass
        # command = {
        #     'com-uuid': str(uuid.uuid4()),
        #     'command': 'signal-task',
        #     'sender': self.name,
        #     'signal': '$abort',
        #     'task-uuid': task
        # }
        # str_command = json.dumps(command)
        # self.client.publish(self.base_topic, str_command)

    def publish_go_to(self, waypoint: np.ndarray, speed):
        command = {
            "com-uuid": str(uuid.uuid4()),
            "command": "start-task",
            "execution-unit": self.name,
            "sender": self.parent_service_name,
            "task": {
                "name": "move-to",
                "params": {
                    "speed": str(speed),
                    "waypoint": {
                        "altitude": 0,
                        "latitude": waypoint[0],
                        "longitude": waypoint[1],
                        "rostype": "GeoPoint",
                    },
                },
            },
            "task-uuid": str(uuid.uuid4()),
            "time_added": 0,
        }
        self.current_task_uuid = command["task-uuid"]
        self.current_task_name = command["task"]["name"]
        str_command = json.dumps(command)
        self.client.publish(self.exec_command_topic, str_command, qos=1)

    def publish_trajectory(self, waypoints: List[list[float]]):
        command = {"name": self.trajectory_name, "type": "polyline", "line": waypoints, "color": "#FFFFFF"}
        str_command = json.dumps(command)
        self.client.publish(self.trajectory_topic, str_command, qos=1)

    def at_start_point(self) -> bool:
        error = float(np.linalg.norm(self.current_agent_state.p - self.initial_state.p))
        # print(f"{self.vessel_name} at start point error: {error}")
        return error < self.actor.waypoint_radius
    
    def publish_obstacle_distances(self, distances: List[float], increment: int, min_distance: float, max_distance: float):
        
        if increment <= 0 or 360 / increment != len(distances) or any(distance < min_distance or distance > max_distance for distance in distances):
            raise ValueError("Invalid obstacle distances")
        
        command = {
            "distances": distances,
            "increment": increment,
            "min_distance": min_distance,
            "max_distance": max_distance,
        }
        self.client.publish(self.obstacle_distances_topic, json.dumps(command), qos=1)
        
        
    def publish_rc_override(self, pwms: Optional[Tuple[float, float]] = None):
        # left_pwm and right_pwm are normalized values between -1.0 and 1.0
        left_pwm = None
        right_pwm = None
        if pwms is not None:
            left_pwm, right_pwm = normalized_to_pwm(pwms[0]), normalized_to_pwm(pwms[1])
        
        command = {
            "left_pwm": left_pwm,
            "right_pwm": right_pwm,
        }
        self.client.publish(self.rc_override_topic, json.dumps(command), qos=1)
