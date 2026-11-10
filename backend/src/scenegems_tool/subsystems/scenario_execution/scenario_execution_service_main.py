from scenegems_tool.cluster.worker_node.launchers.container_environment import geofence_from_environment
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.subsystems.scenario_execution.scenario_execution_worker import ScenarioExecutionWorker


def main() -> None:
    mqtt_connection = MQttConnectionInfo.from_environment()
    reference_geofence = geofence_from_environment()
    worker = ScenarioExecutionWorker.from_environment(mqtt_connection, reference_geofence)
    try:
        worker.run()
    except KeyboardInterrupt:
        worker.stop()


if __name__ == "__main__":
    main()
