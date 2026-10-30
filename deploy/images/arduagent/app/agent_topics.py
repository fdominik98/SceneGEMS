"""The MQTT topics of one ArduAgent, derived from its environment.

Every topic comes from the effective base topic, which is the WARA-PS default
(waraps/unit/<DOMAIN>/<REAL_SIM>/<NAME>) or the BASE_TOPIC override. An optional
MQTT_TOPIC_PREFIX (ending in '/') scopes the agent on a shared broker: it publishes
and subscribes under the prefix, other agents' positions included, so two simulations
on one broker never see each other. Without the prefix every topic is the unscoped
WARA-PS topic that real vessels, the WARA-PS map and external monitors use.

Standard library only: the backend tests import this module without the image's packages.
"""

from dataclasses import dataclass
from typing import Mapping, Optional

UNIT_TOPIC_ROOT = "waraps/unit/"
POSITION_SUFFIX = "/sensor/position"
DEFAULT_OTHER_POSITIONS_TOPIC = f"{UNIT_TOPIC_ROOT}+/+/+{POSITION_SUFFIX}"


def _topic_prefix(prefix: Optional[str]) -> str:
    prefix = (prefix or "").strip()
    if not prefix:
        return ""
    if not prefix.endswith("/"):
        raise ValueError(f"MQTT_TOPIC_PREFIX must end with '/': {prefix!r}")
    if prefix.startswith("/") or "+" in prefix or "#" in prefix:
        raise ValueError(f"MQTT_TOPIC_PREFIX must be a plain topic path without wildcards: {prefix!r}")
    return prefix


@dataclass(frozen=True)
class AgentTopics:
    prefix: str
    base: str
    other_positions: str
    positions_root: str  # where other agents' positions start; filters incoming positions
    collision_avoidance_root: str  # positions of agents in this agent's domain and context

    @property
    def command(self) -> str:
        return f"{self.base}/exec/command"

    @property
    def position(self) -> str:
        return f"{self.base}{POSITION_SUFFIX}"

    @property
    def obstacle_distances(self) -> str:
        return f"{self.base}/sensor/obstacle_distances"

    @property
    def rc_override(self) -> str:
        return f"{self.base}/sensor/rc_override"

    def is_own(self, topic: str) -> bool:
        """A topic under this agent's base (another agent whose name extends this one's is not)."""
        return topic == self.base or topic.startswith(f"{self.base}/")

    def is_position(self, topic: str) -> bool:
        return topic.startswith(self.positions_root) and topic.endswith(POSITION_SUFFIX)

    @classmethod
    def derive(
        cls,
        domain: str,
        real_sim: str,
        name: str,
        *,
        prefix: Optional[str] = None,
        base_topic: Optional[str] = None,
        other_positions_topic: Optional[str] = None,
    ) -> "AgentTopics":
        """The topics after the overrides: base_topic and other_positions_topic replace the defaults, the prefix goes in front of all."""
        prefix = _topic_prefix(prefix)
        base = base_topic or f"{UNIT_TOPIC_ROOT}{domain}/{real_sim}/{name}"
        return cls(
            prefix=prefix,
            base=f"{prefix}{base}",
            other_positions=f"{prefix}{other_positions_topic or DEFAULT_OTHER_POSITIONS_TOPIC}",
            positions_root=f"{prefix}{UNIT_TOPIC_ROOT}",
            collision_avoidance_root=f"{prefix}{UNIT_TOPIC_ROOT}{domain}/{real_sim}/",
        )

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> "AgentTopics":
        """From DOMAIN, REAL_SIM, NAME and the optional BASE_TOPIC, OTHER_POSITIONS_TOPIC and MQTT_TOPIC_PREFIX."""
        return cls.derive(
            str(environ.get("DOMAIN")),
            str(environ.get("REAL_SIM")),
            str(environ.get("NAME")),
            prefix=environ.get("MQTT_TOPIC_PREFIX"),
            base_topic=environ.get("BASE_TOPIC") or None,
            other_positions_topic=environ.get("OTHER_POSITIONS_TOPIC") or None,
        )
