"""The loop of a subsystem's container: connect, start the pool, heartbeat until the container is stopped."""

import threading
from typing import Any, Callable, Optional

from scenegems_tool.cluster.worker_node.launchers.container_environment import geofence_from_environment, worker_count_from_environment
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo, service_name_from_environment
from utils.file_system_utils import ensure_directories

DEFAULT_POOL_SIZE = 1  # a subsystem started without WORKER_COUNT; a worker node sets it to its slots for the kind


def service_from_environment(service_class: Callable[..., Any], default_name: str) -> Any:
    """The subsystem's service as its launcher configured the container: broker, reference area, pool size and name."""
    ensure_directories()
    return service_class(MQttConnectionInfo.from_environment(), geofence_from_environment(), worker_count_from_environment(DEFAULT_POOL_SIZE), service_name_from_environment(default_name))


def serve(service: Any, stop: Optional[threading.Event] = None) -> None:
    """Run the service until stop is set (or the process is interrupted): its pool works on its own thread, this one heartbeats."""
    stop = stop or threading.Event()
    service.connect()
    service.start_runtime()
    try:
        while not stop.wait(1.0 / service.info_update_rate):
            if service.is_connected:
                service.publish_heartbeat_and_sensor_info()
    except KeyboardInterrupt:
        pass
    finally:
        service.stop_runtime()
        service.disconnect()
