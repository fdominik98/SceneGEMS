import multiprocessing
import os
import time

from scenegems_tool.waraps_integration.mqtt_client import MQttConnectionInfo
from scenegems_tool.waraps_integration.mqtt_trajectory_generation_service import MqttTrajectoryGenerationService
from scenegems_tool.waraps_integration.sim_utils import Geofence
from utils.file_system_utils import ensure_directories


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes"}


def main() -> None:
    ensure_directories()
    mqtt_connection = MQttConnectionInfo(
        user=os.environ["MQTT_USER"],
        password=os.environ["MQTT_PASSWORD"],
        agent_broker=os.environ["MQTT_BROKER"],
        client_broker=os.environ["MQTT_BROKER"],
        port=int(os.environ["MQTT_PORT"]),
        tls_connection=_env_bool("MQTT_TLS"),
        allow_certificates=_env_bool("MQTT_ALLOW_CERTIFICATES"),
    )
    reference_geofence = Geofence(
        latitude=float(os.environ["GEOFENCE_LATITUDE"]),
        longitude=float(os.environ["GEOFENCE_LONGITUDE"]),
        radius_meters=float(os.environ["GEOFENCE_RADIUS"]),
    )
    service = MqttTrajectoryGenerationService(mqtt_connection, reference_geofence)
    service.connect()
    service.start_runtime()
    tick_interval_sec = 1.0 / service.info_update_rate
    try:
        while True:
            time.sleep(tick_interval_sec)
            if service.is_connected:
                service.publish_heartbeat_and_sensor_info()
    except KeyboardInterrupt:
        service.stop_runtime()
        service.disconnect()


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn")
    main()
