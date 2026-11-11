"""The live COLREGS monitor: a long-lived monitoring container that judges scene batches sent over MQTT.

This is the monitoring service of a worker node: one long-lived container in the worker node's
compose project, as the scene and trajectory generation pools are. Post-hoc monitoring of a
finished state log is still a job of its own (cluster/worker_node/jobs/monitoring_post_hoc_job.py)
and does not use it yet.
"""

import base64
import logging
import os
import shutil
import threading
from typing import Optional

from scenegems_tool.cluster.worker_node.instance_scope import InstanceScope
from scenegems_tool.cluster.worker_node.launchers.container_environment import subsystem_environment
from scenegems_tool.cluster.worker_node.launchers.docker_cli import force_remove_containers, is_container_running
from scenegems_tool.cluster.worker_node.launchers.pooled.pooled_service import SERVICE_CPUS, PooledService, PoolNames
from scenegems_tool.cluster.worker_node.subsystem import Subsystem, subsystem_image
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from utils.docker_compose_network import attach_broker_network_to_compose

_logger = logging.getLogger(__name__)
_SERVICE_KEY = "monitoring"


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
