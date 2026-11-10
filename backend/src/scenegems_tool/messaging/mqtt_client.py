import copy
import json
import os
import socket
import ssl
import traceback
import uuid
from abc import ABC, abstractmethod
from threading import Event
from typing import Any, Dict, List, Mapping, Optional, Set

import paho.mqtt.client as mqtt

from scenegems_tool.messaging.topic_scope import ScopedPahoClient, TopicScope
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

_LOOPBACK_ALIASES = frozenset({"localhost", "127.0.0.1", "::1"})
_DOCKER_HOST_GATEWAY = "host.docker.internal"

_CONNACK_REASONS = {
    1: "broker refused the connection: incorrect protocol version",
    2: "broker refused the connection: invalid client identifier",
    3: "broker refused the connection: server unavailable",
    4: "broker refused the connection: bad username or password",
    5: "broker refused the connection: not authorised",
}


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
    """Resolve a broker address the user typed into one control-node-api's container can dial.

    A loopback address means "the control node's machine", which from inside the container is the
    Docker host gateway, not the container itself. Rewriting it to `host.docker.internal`
    keeps brokers published on that machine's ports reachable, such as the OTG stack's. A
    TLS broker keeps its name, which its certificate is checked against. The port is
    returned as typed.
    """

    def normalize_host(host: str) -> str:
        trimmed = host.strip()
        if not tls_connection and _running_in_container() and trimmed.lower() in _LOOPBACK_ALIASES:
            return _DOCKER_HOST_GATEWAY
        return trimmed

    return normalize_host(agent_broker), normalize_host(client_broker), port


class MQttConnectionInfo:
    """How a client reaches its broker.

    Plain MQTT is the default (the workbench). With `tls_connection` and a
    `ca_certificate_path`, the broker's certificate and host name are verified against that
    CA, which is how cluster clients reach the control node's broker. TLS without a CA keeps the
    workbench's behaviour for external brokers such as WARA-PS: the system trust store, or
    no verification when `allow_certificates` is set.

    `topic_prefix` is the instance scope on a shared broker (cluster/worker_node/instance_scope.py);
    it is empty for the workbench.
    """

    def __init__(
        self,
        user: str,
        password: str,
        agent_broker: str,
        client_broker: str,
        port: int,
        tls_connection: bool,
        allow_certificates: bool,
        ca_certificate_path: Optional[str] = None,
        topic_prefix: str = "",
    ):
        self.user = user
        self.password = password
        self.agent_broker = agent_broker
        self.client_broker = client_broker
        self.port = port
        self.tls_connection = tls_connection
        self.allow_certificates = allow_certificates
        self.ca_certificate_path = ca_certificate_path
        self.topic_prefix = topic_prefix

    def __repr__(self) -> str:
        return (
            f"MQttConnectionInfo(user={self.user!r}, password=<hidden>, client_broker={self.client_broker!r}, port={self.port}, "
            f"tls_connection={self.tls_connection}, ca_certificate_path={self.ca_certificate_path!r}, topic_prefix={self.topic_prefix!r})"
        )

    def with_topic_prefix(self, topic_prefix: str) -> "MQttConnectionInfo":
        """The same connection for the clients of one instance."""
        scoped = copy.copy(self)
        scoped.topic_prefix = topic_prefix
        return scoped

    @classmethod
    def from_environment(cls, environ: Optional[Mapping[str, str]] = None) -> "MQttConnectionInfo":
        """The broker connection of a subsystem container, from the variables of mqtt_container_environment:
        MQTT_BROKER, MQTT_PORT, MQTT_USER, MQTT_PASSWORD, MQTT_TLS, MQTT_ALLOW_CERTIFICATES and, for the
        cluster broker, MQTT_CA_CERTIFICATE and MQTT_TOPIC_PREFIX."""
        environ = os.environ if environ is None else environ
        return cls(
            user=environ.get("MQTT_USER", ""),
            password=environ.get("MQTT_PASSWORD", ""),
            agent_broker=environ["MQTT_BROKER"],
            client_broker=environ["MQTT_BROKER"],
            port=int(environ["MQTT_PORT"]),
            tls_connection=_env_flag(environ, "MQTT_TLS"),
            allow_certificates=_env_flag(environ, "MQTT_ALLOW_CERTIFICATES"),
            ca_certificate_path=environ.get("MQTT_CA_CERTIFICATE", "").strip() or None,
            topic_prefix=environ.get("MQTT_TOPIC_PREFIX", ""),
        )

    def apply_to(self, client: mqtt.Client) -> None:
        """Set credentials and TLS on a paho client before it connects."""
        if self.user or self.password:
            client.username_pw_set(self.user, self.password)
        if not self.tls_connection:
            return
        if self.ca_certificate_path:
            client.tls_set(ca_certs=self.ca_certificate_path, cert_reqs=ssl.CERT_REQUIRED)
            return
        client.tls_set(cert_reqs=(ssl.CERT_NONE if self.allow_certificates else ssl.CERT_REQUIRED))
        client.tls_insecure_set(True)


def _env_flag(environ: Mapping[str, str], name: str) -> bool:
    return environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def mqtt_container_environment(mqtt_connection: MQttConnectionInfo) -> Dict[str, str]:
    """Environment that hands a broker connection to a subsystem container (read by MQttConnectionInfo.from_environment).

    The container dials the agent broker. The CA certificate path and the topic prefix are set
    only when there is one, so workbench containers get exactly the variables they got before.
    The CA path must be valid inside the container: the launcher mounts the file there.
    """
    environment = {
        "MQTT_USER": mqtt_connection.user,
        "MQTT_PASSWORD": mqtt_connection.password,
        "MQTT_BROKER": mqtt_connection.agent_broker,
        "MQTT_PORT": str(mqtt_connection.port),
        "MQTT_TLS": "1" if mqtt_connection.tls_connection else "0",
        "MQTT_ALLOW_CERTIFICATES": "1" if mqtt_connection.allow_certificates else "0",
    }
    if mqtt_connection.ca_certificate_path:
        environment["MQTT_CA_CERTIFICATE"] = mqtt_connection.ca_certificate_path
    if mqtt_connection.topic_prefix:
        environment["MQTT_TOPIC_PREFIX"] = mqtt_connection.topic_prefix
    return environment


class MqttClient(ABC):
    def __init__(self, name: str, topic: str, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence):
        self.name = name
        self.topic = topic
        self.uuid = str(uuid.uuid4())
        self.running_tasks: Set[str] = set()
        self.mqtt_connection = mqtt_connection
        self.reference_geofence = reference_geofence
        self.connected_event = Event()
        # Topics stay relative to the instance: the client adds the prefix on publish and
        # subscribe and removes it from incoming messages.
        self.topic_scope = TopicScope(mqtt_connection.topic_prefix)
        self.client = ScopedPahoClient(self.topic_scope, mqtt.CallbackAPIVersion.VERSION1, client_id=self.name + "_" + self.uuid)
        self.client.user_data_set("waraps")
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self._on_scoped_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.last_broker_refusal: str | None = None

    def connect(self):
        """Connect to the broker using the mqtt client"""
        self.mqtt_connection.apply_to(self.client)
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
            if msg_str.lower() == "true":
                return True
            elif msg_str.lower() == "false":
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
        self.connected_event.clear()
        if rc != mqtt.MQTTErrorCode.MQTT_ERR_SUCCESS:
            # `rc` here is a paho error code (CONN_LOST, NO_CONN, ...), not a CONNACK code.
            self.last_broker_refusal = mqtt.error_string(rc)
            print(f"{self.name} got disconnected from {self.endpoint} with code {rc}: {self.last_broker_refusal}")
            return
        print(f"{self.name} got disconnected from {self.endpoint} with code {rc}: clean disconnect")

    def _on_scoped_message(self, client, userdata, msg: mqtt.MQTTMessage):
        """Hand an incoming message to on_message with the instance prefix removed from its topic."""
        scoped = self.topic_scope.strip_message(msg)
        if scoped is not None:
            self.on_message(client, userdata, scoped)

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
