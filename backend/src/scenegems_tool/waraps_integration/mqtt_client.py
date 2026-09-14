from asyncio import Event
import json
import os
import socket
import ssl
import traceback
import uuid
from abc import ABC, abstractmethod
from typing import Any, List, Set
import paho.mqtt.client as mqtt
from scenegems_tool.waraps_integration.sim_utils import Geofence

_LOOPBACK_ALIASES = frozenset({"localhost", "127.0.0.1", "::1"})
_DOCKER_HOST_GATEWAY = "host.docker.internal"

_CONNACK_REASONS = {
    1: "broker refused the connection: incorrect protocol version",
    2: "broker refused the connection: invalid client identifier",
    3: "broker refused the connection: server unavailable",
    4: "broker refused the connection: bad username or password",
    5: "broker refused the connection: not authorised",
}


def _host_resolves(host: str) -> bool:
    """Whether the given name can be resolved from this process."""
    try:
        socket.getaddrinfo(host, None)
        return True
    except socket.gaierror:
        return False


def _running_in_container() -> bool:
    return os.path.exists("/.dockerenv")


def describe_connect_exception(exc: Exception) -> str:
    """Turn a socket or TLS failure into something a user can act on."""
    if isinstance(exc, socket.gaierror):
        return f"host name could not be resolved ({exc})"
    if isinstance(exc, ConnectionRefusedError):
        return "connection refused: nothing is listening on that port"
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "connection timed out: the host is unreachable or a firewall dropped the packets"
    if isinstance(exc, ssl.SSLError):
        return f"TLS handshake failed ({exc}). Check the TLS toggle and the certificate settings"
    if isinstance(exc, OSError):
        return f"network error ({exc.__class__.__name__}: {exc})"
    return f"{exc.__class__.__name__}: {exc}"


def resolve_mqtt_broker_endpoints(
    agent_broker: str,
    client_broker: str,
    port: int,
    *,
    tls_connection: bool,
) -> tuple[str, str, int]:
    """Resolve a broker address the user typed into one this container can dial.

    A loopback address means "the machine running the browser", which from inside a
    container is the Docker host gateway, not the container itself. Rewriting it to
    `host.docker.internal` keeps host-published brokers reachable, including ones
    started by another compose project such as the OTG stack. The in-compose broker
    service is substituted only when the typed port is the one it listens on internally
    and its name actually resolves, so an absent compose broker never hides a working
    address. The port the user typed is always preserved.
    """
    compose_host = os.environ.get("MQTT_BROKER_HOST", "").strip()
    compose_port = os.environ.get("MQTT_BROKER_PORT", "").strip()
    prefer_compose = bool(compose_host) and compose_port.isdigit() and int(compose_port) == port and _host_resolves(compose_host)

    def normalize_host(host: str) -> str:
        trimmed = host.strip()
        if tls_connection or not _running_in_container():
            return trimmed
        if trimmed.lower() not in _LOOPBACK_ALIASES:
            return trimmed
        return compose_host if prefer_compose else _DOCKER_HOST_GATEWAY

    return normalize_host(agent_broker), normalize_host(client_broker), port


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
        self.last_broker_refusal: str | None = None

    def connect(self):
        """Connect to the broker using the mqtt client"""
        if self.mqtt_connection.tls_connection:
            self.client.username_pw_set(self.mqtt_connection.user, self.mqtt_connection.password)
            self.client.tls_set(
                cert_reqs=(ssl.CERT_NONE if self.mqtt_connection.allow_certificates else ssl.CERT_REQUIRED),
            )
            self.client.tls_insecure_set(True)
        try:
            res: mqtt.MQTTErrorCode = self.client.connect(self.mqtt_connection.client_broker, self.mqtt_connection.port, 60)
        except Exception as exc:
            detail = describe_connect_exception(exc)
            print(f"{self.name} failed to reach broker {self.endpoint}: {detail}")
            raise RuntimeError(f"{self.name} could not reach broker {self.endpoint}: {detail}") from exc
        if res != mqtt.MQTTErrorCode.MQTT_ERR_SUCCESS:
            detail = mqtt.error_string(res)
            print(f"{self.name} failed to reach broker {self.endpoint}: {detail}")
            raise RuntimeError(f"{self.name} could not reach broker {self.endpoint}: {detail}")
        self.client.loop_start()

    @property
    def endpoint(self) -> str:
        """The broker address this client dials, formatted for error messages."""
        scheme = "mqtts" if self.mqtt_connection.tls_connection else "mqtt"
        return f"{scheme}://{self.mqtt_connection.client_broker}:{self.mqtt_connection.port}"

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
                self.last_broker_refusal = _CONNACK_REASONS.get(rc, f"broker refused the connection with code {rc}")
                print(f"{self.name} rejected by {self.endpoint}: {self.last_broker_refusal}")
        except Exception:
            print(traceback.format_exc())

    def on_disconnect(self, client, userdata, rc):
        """Is triggered when the client gets disconnected from the broker"""
        if rc != mqtt.MQTTErrorCode.MQTT_ERR_SUCCESS:
            self.last_broker_refusal = _CONNACK_REASONS.get(rc, mqtt.error_string(rc))
        print(f"{self.name} got disconnected from {self.endpoint} with code {rc}: {self.last_broker_refusal or 'clean disconnect'}")

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
        
