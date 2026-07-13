from __future__ import annotations

import asyncio
from typing import Callable

from scenegems_tool.backend_service.protocol import ServerMessage
from scenegems_tool.scenario_generation.scenario_generation_container import ScenarioGenerationContainer
from scenegems_tool.waraps_integration.mqtt_client import MQttConnectionInfo
from scenegems_tool.waraps_integration.mqtt_scenario_generation_client import MqttScenarioGenerationClient
from scenegems_tool.waraps_integration.mqtt_scenario_generation_service import SCENARIO_GENERATION_SERVICE_NAME, SCENARIO_GENERATION_SERVICE_TOPIC
from scenegems_tool.waraps_integration.sim_utils import Geofence


class ScenarioGenerationSession:
    def __init__(self, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence, send_payload: Callable[[ServerMessage], None]):
        self.mqtt_connection = mqtt_connection
        self.reference_geofence = reference_geofence
        self.send_payload = send_payload

        self._container = ScenarioGenerationContainer(mqtt_connection, reference_geofence)

        self.client = MqttScenarioGenerationClient(
            mqtt_connection=mqtt_connection,
            topic=SCENARIO_GENERATION_SERVICE_TOPIC,
            reference_geofence=reference_geofence,
            parent_service_name=SCENARIO_GENERATION_SERVICE_NAME,
            send_payload=send_payload,
        )
        self.client.connect()

    @property
    def is_connected(self) -> bool:
        return self.client.is_connected and self.client.is_heartbeat_valid

    def publish_generate_scene_command(
        self,
        request_id: str,
        functional_scenario_content: str,
        colregs_constraints_content: str,
        vessel_types_content: str,
        obstacle_types_content: str,
        timeout: int,
    ) -> None:
        self.client.publish_generate_scene_command(
            request_id,
            functional_scenario_content,
            colregs_constraints_content,
            vessel_types_content,
            obstacle_types_content,
            timeout,
        )

    async def destroy_async(self) -> None:
        await asyncio.to_thread(self.destroy)

    def destroy(self) -> None:
        self.client.disconnect()
        self._container.destroy()
