"""The layout of agent topics: the one of the WARA-PS agent API, under the first level of the broker.

    <root>/<agent type>/<domain>/<real or simulation>/<name>/<channel>

On a WARA-PS broker, or any other external one, the root is `waraps`. On a control node's own broker
it is `scenegems`: there the topics belong to the cluster, and the name in a topic tells its agents
apart, not a level for the control node, the worker node or the workbench. A subsystem is a service
agent (`service/virtual/real`); the channels below its name are the agent API's (heartbeat,
exec/command, sensor/<name>). A vessel's agent is a unit agent (`unit/surface/simulation` or
`unit/surface/real`).

Standard library only, so the control node reads a topic's layout without loading an MQTT client.
"""

from typing import NamedTuple, Optional

WARAPS_TOPIC_ROOT = "waraps"  # the first topic level of WARA-PS, on its brokers and any other external one
CLUSTER_TOPIC_ROOT = "scenegems"  # the first topic level on a control node's own broker
SERVICE_TOPIC_LEVELS = 5  # <root>/service/virtual/real/<name>
UNIT_TOPIC_LEVELS = 5  # <root>/unit/<domain>/<real or simulation>/<name>
SURFACE_DOMAIN = "surface"
SIMULATION_CONTEXT = "simulation"
REAL_CONTEXT = "real"
UNIT_CONTEXTS = (SIMULATION_CONTEXT, REAL_CONTEXT)


def require_topic_root(topic_root: str) -> str:
    """A first topic level: one plain level, so no '/', no wildcard and not empty."""
    if not topic_root or any(character in topic_root for character in "/+#"):
        raise ValueError(f"A topic root is one topic level without wildcards: {topic_root!r}")
    return topic_root


def _require_level(value: str, what: str) -> str:
    if not value or any(character in value for character in "/+#"):
        raise ValueError(f"{what} is one topic level without wildcards: {value!r}")
    return value


def service_topic(topic_root: str, name: str) -> str:
    """The base topic of a service agent: <root>/service/virtual/real/<name>."""
    return f"{require_topic_root(topic_root)}/service/virtual/real/{_require_level(name, 'A service name')}"


class UnitTopic(NamedTuple):
    """The levels of a unit agent's base topic: <root>/unit/<domain>/<context>/<name>."""

    root: str
    domain: str
    context: str  # real or simulation
    name: str


def unit_topic(topic_root: str, context: str, name: str, domain: str = SURFACE_DOMAIN) -> str:
    """The base topic of a vessel's agent: <root>/unit/<domain>/<real or simulation>/<name>."""
    if context not in UNIT_CONTEXTS:
        raise ValueError(f"A unit is {' or '.join(UNIT_CONTEXTS)}: {context!r}")
    return f"{require_topic_root(topic_root)}/unit/{_require_level(domain, 'A domain')}/{context}/{_require_level(name, 'A unit name')}"


def parse_unit_topic(topic: str) -> Optional[UnitTopic]:
    """The levels of a unit agent's base topic; None for a topic that is not in the layout."""
    levels = topic.split("/")
    if len(levels) != UNIT_TOPIC_LEVELS or levels[1] != "unit" or levels[3] not in UNIT_CONTEXTS:
        return None
    if any(not level or "+" in level or "#" in level for level in levels):
        return None
    return UnitTopic(root=levels[0], domain=levels[2], context=levels[3], name=levels[4])
