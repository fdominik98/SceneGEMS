"""The container of the scene generation subsystem: its pool on the broker (messaging/mqtt_scene_generation_service.py)."""

import multiprocessing

from scenegems_tool.messaging.mqtt_scene_generation_service import MqttSceneGenerationService
from scenegems_tool.subsystems.pool.pool_service_main import serve, service_from_environment
from scenegems_tool.subsystems.scene_generation.scene_generation_types import SCENE_GENERATION_SERVICE_NAME


def main() -> None:
    serve(service_from_environment(MqttSceneGenerationService, SCENE_GENERATION_SERVICE_NAME))


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn")
    main()
