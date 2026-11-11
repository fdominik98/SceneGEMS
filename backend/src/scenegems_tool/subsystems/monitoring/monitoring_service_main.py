"""The container of the monitoring subsystem: its pool on the broker (messaging/mqtt_monitor_service.py)."""

import multiprocessing

from scenegems_tool.messaging.mqtt_monitor_service import MqttMonitoringService
from scenegems_tool.subsystems.monitoring.monitoring_types import MONITORING_SERVICE_NAME
from scenegems_tool.subsystems.pool.pool_service_main import serve, service_from_environment


def main() -> None:
    serve(service_from_environment(MqttMonitoringService, MONITORING_SERVICE_NAME))


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn")
    main()
