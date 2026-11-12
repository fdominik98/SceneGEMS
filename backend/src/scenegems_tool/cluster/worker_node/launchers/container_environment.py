"""Environment variables between a launcher and the subsystem main it starts.

The launcher writes them into the compose service and the main reads them back. The broker
connection pair lives in messaging/mqtt_client.py next to MQttConnectionInfo.
"""

import os
from typing import Dict, Optional

from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo, mqtt_container_environment
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

WORKER_COUNT_VARIABLE = "WORKER_COUNT"


def subsystem_environment(mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence, workers: Optional[int] = None) -> Dict[str, str]:
    """Broker connection, reference geofence and, for a sized pool, its worker count."""
    environment = {
        **mqtt_container_environment(mqtt_connection),
        "GEOFENCE_LATITUDE": str(reference_geofence.latitude),
        "GEOFENCE_LONGITUDE": str(reference_geofence.longitude),
        "GEOFENCE_RADIUS": str(reference_geofence.radius_meters),
    }
    if workers is not None:
        environment[WORKER_COUNT_VARIABLE] = str(workers)
    return environment


def geofence_from_environment() -> Geofence:
    return Geofence(
        latitude=float(os.environ["GEOFENCE_LATITUDE"]),
        longitude=float(os.environ["GEOFENCE_LONGITUDE"]),
        radius_meters=float(os.environ["GEOFENCE_RADIUS"]),
    )


def worker_count_from_environment(default: int) -> int:
    """The pool size the launcher chose from the worker node's slots, or the subsystem's own default when it was started without one."""
    value = os.environ.get(WORKER_COUNT_VARIABLE, "").strip()
    if not value:
        return default
    count = int(value)
    if count < 1:
        raise ValueError(f"{WORKER_COUNT_VARIABLE} must be at least 1, got {count}")
    return count
