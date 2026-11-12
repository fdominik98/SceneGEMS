"""The container of the design space exploration subsystem: its pool on the broker (messaging/mqtt_design_space_exploration_service.py)."""

import multiprocessing

from scenegems_tool.messaging.mqtt_design_space_exploration_service import MqttDesignSpaceExplorationService
from scenegems_tool.subsystems.design_space_exploration.design_space_exploration_types import DESIGN_SPACE_EXPLORATION_SERVICE_NAME
from scenegems_tool.subsystems.pool.pool_service_main import serve, service_from_environment


def main() -> None:
    serve(service_from_environment(MqttDesignSpaceExplorationService, DESIGN_SPACE_EXPLORATION_SERVICE_NAME))


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn")
    main()
