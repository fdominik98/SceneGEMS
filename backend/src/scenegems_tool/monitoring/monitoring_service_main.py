import base64
import os

from scenegems_tool.monitoring.monitoring_worker import MonitoringWorker
from scenegems_tool.waraps_integration.mqtt_client import MQttConnectionInfo
from scenegems_tool.waraps_integration.sim_utils import Geofence
from utils.colregs_approximations import COLREGSConstraints


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes"}


def main() -> None:
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
    agent_name = os.environ["MONITOR_AGENT_NAME"]
    topic = os.environ["MONITOR_TOPIC"]
    constraints_yaml = base64.b64decode(os.environ["COLREGS_CONSTRAINTS_YAML_B64"]).decode("utf-8")
    colregs_constants = COLREGSConstraints.from_file_content(constraints_yaml)

    worker = MonitoringWorker(
        mqtt_connection=mqtt_connection,
        topic=topic,
        agent_name=agent_name,
        reference_geofence=reference_geofence,
        colregs_constants=colregs_constants,
    )
    try:
        worker.run()
    except KeyboardInterrupt:
        worker.stop()


if __name__ == "__main__":
    main()
