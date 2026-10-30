"""The live COLREGS monitor: a long-lived monitoring container that judges scene batches sent over MQTT.

This is the live monitor binding (design doc 4.4): the workbench starts one per monitor
agent, and a node starts one per pool. Post-hoc monitoring of a finished state log is a
job of its own (cluster/node/jobs/monitoring_post_hoc_job.py) and does not use it.
"""

import base64
import logging
import os
import re
import shutil
import threading
import uuid
from typing import Optional

from scenegems_tool.cluster.node.instance_scope import InstanceScope
from scenegems_tool.cluster.node.launchers.container_environment import subsystem_environment
from scenegems_tool.cluster.node.launchers.docker_cli import container_names_and_ids, force_remove_containers, is_container_running
from scenegems_tool.cluster.node.launchers.pooled.pooled_service import SERVICE_CPUS, PooledService, PoolNames
from scenegems_tool.cluster.node.subsystem import Subsystem, subsystem_image
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from utils.docker_compose_network import attach_broker_network_to_compose
from utils.file_system_utils import MONITORING_GEN_FOLDER

_logger = logging.getLogger(__name__)
WORKBENCH_COMPOSE_PROJECT_PREFIX = "scenegems-monitoring-subsystem"
_SERVICE_KEY = "monitoring"


def _sanitize_docker_name(name: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "_", name)
    sanitized = sanitized.strip("_.-") or "monitor"
    return sanitized[:63]


def workbench_monitor_names(agent_name: str, topic_prefix: str = "") -> PoolNames:
    """Names of one workbench monitor container: unique per start, prefixed by the agent name.

    topic_prefix is the live session's on the master's broker (empty elsewhere); the container
    name then starts with the session's scope name instead, so an unscoped monitor of the same
    agent never takes it for a leftover of its own.
    """
    instance_id = uuid.uuid4().hex[:8]
    owner = _sanitize_docker_name(topic_prefix.replace("/", "-")) if topic_prefix else _sanitize_docker_name(agent_name)[:54]
    return PoolNames(
        compose_project=f"{WORKBENCH_COMPOSE_PROJECT_PREFIX}-{instance_id}",
        service_key=_SERVICE_KEY,
        container_name=f"{owner[:54]}-{instance_id}",
        network_key="",
        network_name="",
        folder=f"{MONITORING_GEN_FOLDER}/{instance_id}",
        topic_prefix=topic_prefix,
        scoped=False,
    )


class MonitorService(PooledService):
    subsystem = Subsystem.MONITORING

    def __init__(
        self,
        names: PoolNames,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        agent_name: str,
        topic: str,
        colregs_constraints_content: str,
        broker_network: Optional[str] = None,
    ):
        self.agent_name = agent_name
        self.topic = topic
        self.colregs_constraints_content = colregs_constraints_content
        self.container_name = names.container_name
        self.compose_folder = names.folder
        self._startup_complete = threading.Event()
        super().__init__(names, mqtt_connection, reference_geofence, cpus=SERVICE_CPUS, broker_network=broker_network)

    @classmethod
    def for_workbench(cls, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence, agent_name: str, topic: str, colregs_constraints_content: str) -> "MonitorService":
        """A live session's monitor, under the session's topic prefix when it has one."""
        return cls(workbench_monitor_names(agent_name, mqtt_connection.topic_prefix), mqtt_connection, reference_geofence, agent_name, topic, colregs_constraints_content)

    @classmethod
    def for_scope(
        cls,
        scope: InstanceScope,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        agent_name: str,
        topic: str,
        colregs_constraints_content: str,
        broker_network: Optional[str] = None,
    ) -> "MonitorService":
        return cls(PoolNames.for_scope(scope, _SERVICE_KEY), mqtt_connection, reference_geofence, agent_name, topic, colregs_constraints_content, broker_network)

    def build_compose(self) -> dict:
        constraints_b64 = base64.b64encode(self.colregs_constraints_content.encode("utf-8")).decode("ascii")
        environment = {
            **subsystem_environment(self.mqtt_connection, self.reference_geofence),
            "MONITOR_AGENT_NAME": self.agent_name,
            "MONITOR_TOPIC": self.topic,
            "COLREGS_CONSTRAINTS_YAML_B64": constraints_b64,
            "PYTHONUNBUFFERED": "1",
        }
        service = {
            "image": subsystem_image(self.subsystem),
            "container_name": self.container_name,
            "hostname": self.container_name,
            "environment": environment,
            "cpus": self.cpus,
            "networks": [],
        }

        # Only the SceneGEMS compose network. A per-instance bridge becomes the default
        # route on Docker Desktop and TLS to broker.waraps.org then flaps (connection lost).
        return attach_broker_network_to_compose(
            {
                "services": {
                    _SERVICE_KEY: service,
                },
            },
            self.broker_network,
        )

    def _run_container_lifecycle_startup(self, docker_compose: dict) -> None:
        try:
            if self._shutdown.is_set():
                return
            if not self.names.scoped and not self.names.topic_prefix:
                self._reap_same_agent_containers()
            if self._shutdown.is_set():
                return
            os.makedirs(self.compose_folder, exist_ok=True)
            if self._shutdown.is_set():
                return
            self.project.write(docker_compose)
            if self._shutdown.is_set():
                return
            self.project.up()
            if self._shutdown.is_set():
                self._remove_owned_container()
                return
            self._startup_complete.set()
        except BaseException:
            _logger.exception("MonitoringContainer container lifecycle startup failed")

    def _reap_same_agent_containers(self) -> None:
        """Drop leftover workers that share this WARA-PS agent name.

        Unique compose projects no longer remove peers, so a previous live-broker
        container can keep publishing as `scenario_monitor` and the live broker
        drops the new session. Scoped instances never share a name, and neither do
        the monitors of live sessions with a topic prefix, so only an unscoped
        workbench monitor reaps, and only containers named as it names them.
        """
        own_kind = re.compile(rf"^{re.escape(_sanitize_docker_name(self.agent_name)[:54])}-[0-9a-f]{{8}}$")
        force_remove_containers([container_id for container_id, name in container_names_and_ids() if own_kind.match(name) and name != self.container_name])

    def _remove_owned_container(self) -> None:
        force_remove_containers([self.container_name])
        if os.path.isdir(self.compose_folder):
            shutil.rmtree(self.compose_folder, ignore_errors=True)

    @property
    def is_ready(self) -> bool:
        return self._startup_complete.is_set() and is_container_running(self.container_name)

    def destroy(self) -> None:
        self._shutdown.set()
        if self._lifecycle_thread is not None:
            self._lifecycle_thread.join(timeout=120.0)
            self._lifecycle_thread = None
        self._remove_owned_container()
