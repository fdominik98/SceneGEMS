import os
import random
import ssl
import string
import uuid
from dataclasses import dataclass

from agent_topics import AgentTopics


def id_generator(size=3, chars=string.ascii_lowercase + string.digits):
    return "".join(random.choice(chars) for _ in range(size))


three_last_mac_adress = hex(uuid.getnode())[-3:]

# CONFIG IS DONE IN THE .env file in the root folder


@dataclass
class MqttConfig:
    BROKER: str = str(os.getenv("BROKER"))
    PORT: int = int(os.getenv("PORT"))
    TLS_CERTIFICE: ssl.VerifyMode = ssl.VerifyMode(
        int(os.getenv("TLS_CERTIFICE"))
    )
    MQTT_USER: str = str(os.getenv("MQTT_USER"))
    MQTT_PASSWORD: str = str(os.getenv("MQTT_PASSWORD"))


@dataclass
class PixhawkConfig:
    CONNECTION_STRING: str = str(os.getenv("CONNECTION_STRING"))
    BAUD_RATE: int = int(os.getenv("BAUD_RATE"))


@dataclass
class AgentConfig:
    DOMAIN: str = str(os.getenv("DOMAIN"))
    REAL_SIM: str = str(os.getenv("REAL_SIM"))
    NAME: str = str(os.getenv("NAME"))
    AGENT_DESCRIPTION: str = str(os.getenv("AGENT_DESCRIPTION"))
    AGENT_MODEL: str = str(os.getenv("AGENT_MODEL"))

    # Every topic from the effective base after the BASE_TOPIC and OTHER_POSITIONS_TOPIC
    # overrides, under MQTT_TOPIC_PREFIX when the agent is scoped (agent_topics.py).
    TOPICS: AgentTopics = AgentTopics.from_environment(os.environ)
    TOPIC_PREFIX: str = TOPICS.prefix
    BASE_TOPIC: str = TOPICS.base
    COMMAND_TOPIC: str = TOPICS.command
    POSITION_TOPIC: str = TOPICS.position
    OBSTACLE_DISTANCES_TOPIC: str = TOPICS.obstacle_distances
    OTHER_POSITIONS_TOPIC: str = TOPICS.other_positions
    RC_OVERRIDE_TOPIC: str = TOPICS.rc_override

    UUID: str = str(uuid.uuid4())

    VEHICLE: str = str(os.getenv("VEHICLE"))
    VIDEO_SERVER: str = str(os.getenv("VIDEO_SERVER"))

    LEVELS: str = str(os.getenv("LEVELS"))

    MINIMUM_TAKEOFF_ALTITUDE_RELATIVE: float = float(
        str(os.getenv("MINIMUM_TAKEOFF_ALTITUDE_RELATIVE", "10.0"))
    )
    MINIMUM_MISSION_ALTITUDE_RELATIVE: float = float(
        str(os.getenv("MINIMUM_MISSION_ALTITUDE_RELATIVE", "10.0"))
    )

    # Per-waypoint acceptance radius (meters) written into NAV_WAYPOINT param2.
    # 0.0 keeps the flight controller default (its WP_RADIUS parameter).
    WAYPOINT_ACCEPTANCE_RADIUS_M: float = float(
        str(os.getenv("WAYPOINT_ACCEPTANCE_RADIUS_M", "0.0"))
    )

    os_UUID = os.getenv("UUID")

    if os_UUID:
        UUID = str(os_UUID)
