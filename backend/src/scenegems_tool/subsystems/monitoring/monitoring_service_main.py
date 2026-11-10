import base64
import os

from scenegems_tool.cluster.worker_node.launchers.container_environment import geofence_from_environment
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.subsystems.monitoring.monitoring_worker import MonitoringWorker
from utils.colregs_approximations import COLREGSConstraints


def main() -> None:
    mqtt_connection = MQttConnectionInfo.from_environment()
    reference_geofence = geofence_from_environment()
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
