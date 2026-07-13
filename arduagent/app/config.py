import os
import random
import ssl
import string
import uuid
from dataclasses import dataclass


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

    BASE_TOPIC: str = f"waraps/unit/{DOMAIN}/{REAL_SIM}/{NAME}"
    COMMAND_TOPIC: str = f"{BASE_TOPIC}/exec/command"
    POSITION_TOPIC: str = f"{BASE_TOPIC}/sensor/position"
    OBSTACLE_DISTANCES_TOPIC: str = f"{BASE_TOPIC}/sensor/obstacle_distances"
    OTHER_POSITIONS_TOPIC: str = f"waraps/unit/+/+/+/sensor/position"
    RC_OVERRIDE_TOPIC: str = f"{BASE_TOPIC}/sensor/rc_override"

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

    os_BASE_TOPIC = os.getenv("BASE_TOPIC")
    os_OTHER_POSITIONS_TOPIC = os.getenv("OTHER_POSITIONS_TOPIC")
    os_UUID = os.getenv("UUID")

    # Replace values from .env if
    if os_BASE_TOPIC:
        BASE_TOPIC = str(os_BASE_TOPIC)

    if os_OTHER_POSITIONS_TOPIC:
        OTHER_POSITIONS_TOPIC = str(os_OTHER_POSITIONS_TOPIC)

    if os_UUID:
        UUID = str(os_UUID)
