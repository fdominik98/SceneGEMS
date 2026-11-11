"""A pooled service: one long-lived subsystem container that serves many requests over MQTT.

The container runs the subsystem's MQTT service with a pool of worker processes, sized by
the worker node's slots (WORKER_COUNT) or by the subsystem's own default in the workbench. The
launcher starts it on a background thread, so the caller never blocks on Docker, and
callers talk to it on `service_topic` under its `service_name`, which tells it from the
same service of every other worker node on the broker.

A worker node's pool is part of the worker node's compose project and carries its instance's
label (instance_scope.py), by which it is removed again.
"""

import logging
import os
import shutil
import threading
from dataclasses import dataclass
from typing import Dict, Optional

from scenegems_tool.cluster.worker_node.instance_scope import INSTANCE_LABEL, InstanceScope
from scenegems_tool.cluster.worker_node.launchers.compose_project import ComposeProject
from scenegems_tool.cluster.worker_node.launchers.container_environment import subsystem_environment
from scenegems_tool.cluster.worker_node.subsystem import Subsystem, subsystem_image
from scenegems_tool.messaging.mqtt_client import SERVICE_NAME_VARIABLE, MQttConnectionInfo, service_topic
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from utils.docker_compose_network import attach_broker_network_to_compose
from utils.file_system_utils import merge_compose_volumes

_logger = logging.getLogger(__name__)
SERVICE_CPUS = 1  # the MQTT service process next to the workers
STARTUP_JOIN_TIMEOUT_S = 120.0


@dataclass(frozen=True)
class PoolNames:
    compose_project: str
    service_key: str  # the service's key in the compose file
    container_name: str
    network_key: str
    network_name: str  # the instance's own bridge network, next to the broker network
    folder: str  # holds the compose file; emptied when the pool starts
    instance: Optional[str] = None  # the instance's label value in the worker node's project, which its containers and networks are found by

    @classmethod
    def for_scope(cls, scope: InstanceScope, service_key: str) -> "PoolNames":
        return cls(
            compose_project=scope.compose_project,
            service_key=scope.instance_id,  # unique in the worker node's project, which the pool shares
            container_name=scope.docker_name,
            network_key=f"{service_key}_net",
            network_name=scope.network_name("net"),
            folder=scope.folder,
            instance=scope.key,
        )


class PooledService:
    subsystem: Subsystem
    default_service_name = ""  # the service's MQTT name on its own; a subclass that is addressed by name sets it

    def __init__(
        self,
        names: PoolNames,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        *,
        cpus: float,
        workers: Optional[int] = None,
        broker_network: Optional[str] = None,
        service_name: Optional[str] = None,
    ):
        self.names = names
        # Every client of this instance, inside the container and outside, uses the same connection, name and topic.
        self.mqtt_connection = mqtt_connection
        self.service_name = service_name or self.default_service_name
        self.service_topic = service_topic(self.mqtt_connection.topic_root, self.service_name) if self.service_name else ""
        self.reference_geofence = reference_geofence
        self.cpus = cpus
        self.workers = workers
        self.broker_network = broker_network
        self.project = ComposeProject(names.compose_project, f"{names.folder}/docker-compose.yml", instance=names.instance)
        self.compose_filename = self.project.compose_filename
        self._shutdown = threading.Event()
        docker_compose = self.labelled(self.build_compose())
        self._lifecycle_thread: Optional[threading.Thread] = threading.Thread(
            target=self._run_container_lifecycle_startup,
            args=(docker_compose,),
            name=f"{names.service_key}_compose",
            daemon=True,
        )
        self._lifecycle_thread.start()

    def build_compose(self) -> dict:
        service = {
            "image": subsystem_image(self.subsystem),
            "container_name": self.names.container_name,
            "hostname": self.names.container_name,
            "environment": {**subsystem_environment(self.mqtt_connection, self.reference_geofence, self.workers), **self.service_name_environment()},
            "cpus": self.cpus,
            "networks": [self.names.network_key],
        }
        return merge_compose_volumes(
            attach_broker_network_to_compose(
                {
                    "services": {
                        self.names.service_key: service,
                    },
                    "networks": {
                        self.names.network_key: {
                            "name": self.names.network_name,
                            "driver": "bridge",
                        }
                    },
                },
                self.broker_network,
            )
        )

    def service_name_environment(self) -> Dict[str, str]:
        """The variable that tells the service its name, when the launcher chose one."""
        return {SERVICE_NAME_VARIABLE: self.service_name} if self.service_name else {}

    def labelled(self, docker_compose: dict) -> dict:
        """The compose document with the instance's label on every service and on every network of its own."""
        if self.names.instance is None:
            return docker_compose
        label = {INSTANCE_LABEL: self.names.instance}
        for service in docker_compose.get("services", {}).values():
            service["labels"] = {**service.get("labels", {}), **label}
        for definition in docker_compose.get("networks", {}).values():
            if isinstance(definition, dict) and not definition.get("external"):
                definition["labels"] = {**definition.get("labels", {}), **label}
        return docker_compose

    def _run_container_lifecycle_startup(self, docker_compose: dict) -> None:
        try:
            if self._shutdown.is_set():
                return
            self.project.force_remove()
            if self._shutdown.is_set():
                return
            if os.path.exists(self.names.folder):
                shutil.rmtree(self.names.folder)
            os.makedirs(self.names.folder, exist_ok=True)
            if self._shutdown.is_set():
                return
            self.project.write(docker_compose)
            if self._shutdown.is_set():
                return
            self.project.up()
        except BaseException:
            _logger.exception("%s container lifecycle startup failed", type(self).__name__)

    def destroy(self) -> None:
        self._shutdown.set()
        if self._lifecycle_thread is not None:
            self._lifecycle_thread.join(timeout=STARTUP_JOIN_TIMEOUT_S)
            self._lifecycle_thread = None
        self.project.force_remove(networks=True)
        shutil.rmtree(self.names.folder, ignore_errors=True)
