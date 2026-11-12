"""The MQTT topics of one ArduAgent, derived from its environment.

Every topic comes from the effective base topic, which is the WARA-PS layout under the broker's
first level (<MQTT_TOPIC_ROOT>/unit/<DOMAIN>/<REAL_SIM>/<NAME>, the root being waraps unless set)
or the BASE_TOPIC override.

The positions of other agents come from every unit under the root, or, with
OTHER_POSITIONS_TOPICS (the position topics themselves, separated by commas), only from the
agents named there: the vessels of the agent's own run, so two runs on one broker never see each
other. Without any of these every topic is the WARA-PS topic that real vessels, the WARA-PS map
and external monitors use.

Standard library only: the backend tests import this module without the image's packages.
"""

from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

DEFAULT_TOPIC_ROOT = "waraps"
UNIT_TOPIC_ROOT = f"{DEFAULT_TOPIC_ROOT}/unit/"
POSITION_SUFFIX = "/sensor/position"
DEFAULT_OTHER_POSITIONS_TOPIC = f"{UNIT_TOPIC_ROOT}+/+/+{POSITION_SUFFIX}"


def _topic_root(root: Optional[str]) -> str:
    root = (root or "").strip() or DEFAULT_TOPIC_ROOT
    if any(character in root for character in "/+#"):
        raise ValueError(f"MQTT_TOPIC_ROOT must be one topic level without wildcards: {root!r}")
    return root


def _listed_topics(topics: Optional[str]) -> Tuple[str, ...]:
    """The position topics of OTHER_POSITIONS_TOPICS: plain topics, each ending in the position channel."""
    listed = tuple(topic.strip() for topic in (topics or "").split(",") if topic.strip())
    for topic in listed:
        if "+" in topic or "#" in topic or not topic.endswith(POSITION_SUFFIX):
            raise ValueError(f"OTHER_POSITIONS_TOPICS names position topics without wildcards: {topic!r}")
    return listed


@dataclass(frozen=True)
class AgentTopics:
    base: str
    other_positions: str  # the first filter the agent subscribes for other agents' positions (all of them in other_position_filters)
    positions_root: str  # where other agents' positions start; filters incoming positions
    collision_avoidance_root: str  # positions of agents in this agent's domain and context
    other_position_filters: Tuple[str, ...] = ()  # every filter the agent subscribes for other agents' positions
    listed_positions: bool = False  # the filters are the position topics of named agents, and no other position is taken

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
        """A position this agent takes: one of the named agents', or, when none is named, any unit's under the root."""
        if self.listed_positions:
            return topic in self.other_position_filters
        return topic.startswith(self.positions_root) and topic.endswith(POSITION_SUFFIX)

    def is_collision_avoidance(self, topic: str) -> bool:
        """A position this agent avoids: one it takes, of an agent in its own domain and context."""
        return self.is_position(topic) and topic.startswith(self.collision_avoidance_root)

    @classmethod
    def derive(
        cls,
        domain: str,
        real_sim: str,
        name: str,
        *,
        base_topic: Optional[str] = None,
        other_positions_topic: Optional[str] = None,
        root: Optional[str] = None,
        other_positions_topics: Optional[str] = None,
    ) -> "AgentTopics":
        """The topics after the overrides: base_topic and other_positions_topic replace the defaults.

        other_positions_topics names the agents whose positions are taken and wins over other_positions_topic.
        """
        unit_root = f"{_topic_root(root)}/unit/"
        listed = _listed_topics(other_positions_topics)
        filters = listed or (other_positions_topic or f"{unit_root}+/+/+{POSITION_SUFFIX}",)
        return cls(
            base=base_topic or f"{unit_root}{domain}/{real_sim}/{name}",
            other_positions=filters[0],
            positions_root=unit_root,
            collision_avoidance_root=f"{unit_root}{domain}/{real_sim}/",
            other_position_filters=filters,
            listed_positions=bool(listed),
        )

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> "AgentTopics":
        """From DOMAIN, REAL_SIM, NAME and the optional MQTT_TOPIC_ROOT, BASE_TOPIC, OTHER_POSITIONS_TOPIC and OTHER_POSITIONS_TOPICS."""
        return cls.derive(
            str(environ.get("DOMAIN")),
            str(environ.get("REAL_SIM")),
            str(environ.get("NAME")),
            base_topic=environ.get("BASE_TOPIC") or None,
            other_positions_topic=environ.get("OTHER_POSITIONS_TOPIC") or None,
            root=environ.get("MQTT_TOPIC_ROOT") or None,
            other_positions_topics=environ.get("OTHER_POSITIONS_TOPICS") or None,
        )
