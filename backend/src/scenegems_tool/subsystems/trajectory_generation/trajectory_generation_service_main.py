"""The container of the trajectory generation subsystem: its pool on the broker (messaging/mqtt_trajectory_generation_service.py)."""

import multiprocessing

from scenegems_tool.messaging.mqtt_trajectory_generation_service import MqttTrajectoryGenerationService
from scenegems_tool.subsystems.pool.pool_service_main import serve, service_from_environment
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_types import TRAJECTORY_GENERATION_SERVICE_NAME


def main() -> None:
    serve(service_from_environment(MqttTrajectoryGenerationService, TRAJECTORY_GENERATION_SERVICE_NAME))


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn")
    main()
