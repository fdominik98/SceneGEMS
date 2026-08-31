from __future__ import annotations

import asyncio
from typing import Callable

from scenegems_tool.backend_service.protocol import ServerMessage
from scenegems_tool.trajectory_generation.trajectory_generation_container import TrajectoryGenerationContainer
from scenegems_tool.trajectory_generation.trajectory_generation_types import TrajectoryGenerationParams
from scenegems_tool.waraps_integration.mqtt_client import MQttConnectionInfo
from scenegems_tool.waraps_integration.mqtt_trajectory_generation_client import MqttTrajectoryGenerationClient
from scenegems_tool.waraps_integration.mqtt_trajectory_generation_service import TRAJECTORY_GENERATION_SERVICE_NAME, TRAJECTORY_GENERATION_SERVICE_TOPIC
from scenegems_tool.waraps_integration.sim_utils import Geofence


class TrajectoryGenerationSession:
    def __init__(self, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence, send_payload: Callable[[ServerMessage], None]):
        self.mqtt_connection = mqtt_connection
        self.reference_geofence = reference_geofence
        self.send_payload = send_payload

        self._container = TrajectoryGenerationContainer(mqtt_connection, reference_geofence)

        self.client = MqttTrajectoryGenerationClient(
            mqtt_connection=mqtt_connection,
            topic=TRAJECTORY_GENERATION_SERVICE_TOPIC,
            reference_geofence=reference_geofence,
            parent_service_name=TRAJECTORY_GENERATION_SERVICE_NAME,
            send_payload=send_payload,
        )
        self.client.connect()

    @property
    def is_connected(self) -> bool:
        return self.client.is_connected and self.client.is_heartbeat_valid

    def publish_generate_trajectories_command(
        self,
        request_id: str,
        scenario_content: str,
        colregs_constraints_content: str,
        params: TrajectoryGenerationParams,
    ) -> None:
        self.client.publish_generate_trajectories_command(
            request_id,
            scenario_content,
            colregs_constraints_content,
            params,
        )

    def publish_cancel_command(self) -> None:
        self.client.publish_cancel_command()

    async def destroy_async(self) -> None:
        await asyncio.to_thread(self.destroy)

    def destroy(self) -> None:
        self.client.disconnect()
        self._container.destroy()
