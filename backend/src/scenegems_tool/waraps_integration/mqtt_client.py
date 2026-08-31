from asyncio import Event
import json
import os
import ssl
import traceback
import uuid
from abc import ABC, abstractmethod
from typing import Any, List, Set
import paho.mqtt.client as mqtt
from scenegems_tool.waraps_integration.sim_utils import Geofence

_HOST_ALIASES = frozenset({"localhost", "127.0.0.1", "host.docker.internal"})


def resolve_mqtt_broker_endpoints(
    agent_broker: str,
    client_broker: str,
    port: int,
    *,
    tls_connection: bool,
) -> tuple[str, str, int]:
    """Map host-local broker presets to the in-compose MQTT service when containerized."""
    docker_host = os.environ.get("MQTT_BROKER_HOST", "broker").strip()
    docker_port = int(os.environ.get("MQTT_BROKER_PORT", "1883"))

    def normalize_host(host: str) -> str:
        trimmed = host.strip()
        if tls_connection or not docker_host:
            return trimmed
        if trimmed.lower() in _HOST_ALIASES:
            return docker_host
        return trimmed

    agent = normalize_host(agent_broker)
    client = normalize_host(client_broker)
    resolved_port = docker_port if not tls_connection and port == 1882 and client == docker_host else port
    return agent, client, resolved_port


class MQttConnectionInfo:
    def __init__(self, user: str, password: str, agent_broker: str, client_broker: str, port: int, tls_connection: bool, allow_certificates: bool):
        self.user = user
        self.password = password
        self.agent_broker = agent_broker
        self.client_broker = client_broker
        self.port = port
        self.tls_connection = tls_connection
        self.allow_certificates = allow_certificates

class MqttClient(ABC):
    def __init__(self, name: str, topic: str, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence):
        self.name = name
        self.topic = topic
        self.uuid = str(uuid.uuid4())
        self.running_tasks: Set[str] = set()
        self.mqtt_connection = mqtt_connection
        self.reference_geofence = reference_geofence
        self.connected_event = Event()
        self.client = mqtt.Client(client_id=self.name + "_" + self.uuid)
        self.client.user_data_set("waraps")
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

    def connect(self):
        """Connect to the broker using the mqtt client"""
        if self.mqtt_connection.tls_connection:
            self.client.username_pw_set(self.mqtt_connection.user, self.mqtt_connection.password)
            self.client.tls_set(
                cert_reqs=(ssl.CERT_NONE if self.mqtt_connection.allow_certificates else ssl.CERT_REQUIRED),
            )
            self.client.tls_insecure_set(True)
        try:
            res = None
            while res is None or res != mqtt.MQTTErrorCode.MQTT_ERR_SUCCESS:
                res: mqtt.MQTTErrorCode = self.client.connect(self.mqtt_connection.client_broker, self.mqtt_connection.port, 60)
                print(f"{self.name} connection result: {res}")
            self.client.loop_start()
        except Exception as exc:
            print(f"{self.name} failed to connect to broker {self.mqtt_connection.client_broker}:{self.mqtt_connection.port}")
            print(exc)
            raise RuntimeError(
                f"{self.name} could not connect to broker "
                f"{self.mqtt_connection.client_broker}:{self.mqtt_connection.port}"
            ) from exc
            
    def _parse_message(self, msg: mqtt.MQTTMessage) -> Any:
        try:
            msg_str = msg.payload.decode("utf-8")
            return json.loads(msg_str)
        except json.JSONDecodeError:
            if msg_str.lower() == 'true':
                return True
            elif msg_str.lower() == 'false':
                return False
            return None

    def on_connect(self, client, userdata, flags, rc):
        """Callback triggered when the client connects to the broker"""
        try:
            if rc == 0:
                print(f"{self.name} connected to MQTT Broker: {self.mqtt_connection.client_broker}:{self.mqtt_connection.port}")
                for listen_topic in self.listen_topics:
                    self.client.subscribe(listen_topic)
                    print(f"Subscribing to {listen_topic}")
                self.connected_event.set()
            else:
                print(f"Error to connect : {rc}")
        except Exception:
            print(traceback.format_exc())

    def on_disconnect(self, client, userdata, rc):
        """Is triggered when the client gets disconnected from the broker"""
        print(f"{self.name} got disconnected from the broker {userdata} with code {rc}")
        if rc == 1:
            print("Connection Refused - incorrect protocol version")
        elif rc == 2:
            print("Connection Refused - invalid client identifier")
        elif rc == 3:
            print("Connection Refused - server unavailable")
        elif rc == 4:
            print("Connection Refused - bad username or password")
        elif rc == 5:
            print("Connection Refused - not authorised")
        elif rc == 6:
            print("Connection Refused - unknown error code")
        elif rc == 7:
            print("Connection Refused - MQTT_ERR_NO_CONN")
        elif rc == 8:
            print("Connection Refused - MQTT_ERR_CONN_LOST")
        elif rc == 9:
            print("Connection Refused - MQTT_ERR_NOMEM")
        elif rc == 10:
            print("Connection Refused - MQTT_ERR_GARBAGE")
        elif rc == 11:
            print("Connection Refused - MQTT_ERR_FAIL")

    def on_message(self, client, userdata, msg: mqtt.MQTTMessage):
        """Is triggered when a message is published on topics agent subscribes to"""
        try:
            payload = self._parse_message(msg)
            if payload is not None and (msg.topic == self.exec_feedback_topic or msg.topic == self.exec_response_topic):
                if "status" in payload:
                    if payload["status"] in {"running", "started", "planning"}:
                        self.running_tasks.add(payload["task-uuid"])
                    if payload["status"] in {"failed", "finished", "aborted"}:
                        self.running_tasks.discard(payload["task-uuid"])
                    print(f"Received on {self.name}: {payload['status']}")
                elif "response" in payload:
                    if payload["response"] in {"running", "started", "planning"}:
                        self.running_tasks.add(payload["task-uuid"])
                    if payload["response"] in {"failed", "finished", "aborted"}:
                        self.running_tasks.discard(payload["task-uuid"])
                    print(f"Received on {self.name}: {payload['response']}, fail-reason: {payload.get('fail-reason')}")
            self._on_message(msg, payload)
        except Exception:
            print(traceback.format_exc())

    @property
    @abstractmethod
    def listen_topics(self) -> List[str]:
        pass

    def disconnect(self):
        self.client.disconnect()
        
    @property
    def is_connected(self) -> bool:
        return self.client.is_connected() and self.connected_event.is_set()
    
    @property
    def heartbeat_topic(self) -> str:
        return f"{self.topic}/heartbeat"
        
    @property
    def sensor_topic(self) -> str:
        return f"{self.topic}/sensor"
        
    @property
    def direct_execution_topic(self) -> str:
        return f"{self.topic}/direct_execution"
        
    @property
    def sensor_info_topic(self) -> str:
        return f"{self.sensor_topic}/sensor_info"
    
    @property
    def exec_topic(self) -> str:
        return f"{self.topic}/exec"
    
    @property
    def exec_response_topic(self) -> str:
        return f"{self.exec_topic}/response"
    
    @property
    def exec_feedback_topic(self) -> str:
        return f"{self.exec_topic}/feedback"
    
    @property
    def exec_command_topic(self) -> str:
        return f"{self.exec_topic}/command"
    
    @property
    def position_topic(self) -> str:
        return f"{self.sensor_topic}/position"
    
    @property
    def heading_topic(self) -> str:
        return f"{self.sensor_topic}/heading"
    
    @property
    def clock_topic(self) -> str:
        return f"{self.sensor_topic}/clock"
    
    @property
    def speed_topic(self) -> str:
        return f"{self.sensor_topic}/speed"
    
    @property
    def mode_topic(self) -> str:
        return f"{self.sensor_topic}/mode"
    
    @property
    def state_topic(self) -> str:
        return f"{self.sensor_topic}/state"
    
    @property
    def waypoints_topic(self) -> str:
        return f"{self.sensor_topic}/waypoints"
    
    @property
    def energy_level_topic(self) -> str:
        return f"{self.sensor_topic}/energy_level"
    
    @property
    def battery_status_topic(self) -> str:
        return f"{self.sensor_topic}/battery_status"
    
    @property
    def cargo_topic(self) -> str:
        return f"{self.sensor_topic}/cargo"
    
    @property
    def control_system_version_topic(self) -> str:
        return f"{self.sensor_topic}/control_system_version"
    
    @property
    def course_topic(self) -> str:
        return f"{self.sensor_topic}/course"
    
    @property
    def videoserver_url_topic(self) -> str:
        return f"{self.sensor_topic}/videoserver_url"
    
    @property
    def ip_address_topic(self) -> str:
        return f"{self.sensor_topic}/ip_address"
    
    @property
    def armable_topic(self) -> str:
        return f"{self.sensor_topic}/armable"
    
    @property
    def generated_scene_topic(self) -> str:
        return f"{self.sensor_topic}/generated_scene"

    @property
    def planned_trajectory_topic(self) -> str:
        return f"{self.sensor_topic}/planned_trajectory"

    @property
    def planned_trajectory_preview_topic(self) -> str:
        return f"{self.sensor_topic}/planned_trajectory_preview"
    
    @property
    def obstacle_distances_topic(self) -> str:
        return f"{self.sensor_topic}/obstacle_distances"
    
    @property
    def rc_override_topic(self) -> str:
        return f"{self.sensor_topic}/rc_override"
    
    @abstractmethod
    def _on_message(self, msg: mqtt.MQTTMessage, payload: Any):
        pass
        
