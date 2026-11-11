"""The layout of agent topics: the one of the WARA-PS agent API, under the first level of the broker.

    <root>/<agent type>/<domain>/<real or simulation>/<name>/<channel>

On a WARA-PS broker, or any other external one, the root is `waraps`. On a control node's own broker
it is `scenegems`: there the topics belong to the cluster, and the name in a topic tells its agents
apart, not a level for the control node, the worker node or the workbench. A subsystem is a service
agent (`service/virtual/real`); the channels below its name are the agent API's (heartbeat,
exec/command, sensor/<name>).

Standard library only, so the control node reads a topic's layout without loading an MQTT client.
"""

WARAPS_TOPIC_ROOT = "waraps"  # the first topic level of WARA-PS, on its brokers and any other external one
CLUSTER_TOPIC_ROOT = "scenegems"  # the first topic level on a control node's own broker
SERVICE_TOPIC_LEVELS = 5  # <root>/service/virtual/real/<name>


def require_topic_root(topic_root: str) -> str:
    """A first topic level: one plain level, so no '/', no wildcard and not empty."""
    if not topic_root or any(character in topic_root for character in "/+#"):
        raise ValueError(f"A topic root is one topic level without wildcards: {topic_root!r}")
    return topic_root


def service_topic(topic_root: str, name: str) -> str:
    """The base topic of a service agent: <root>/service/virtual/real/<name>."""
    if not name or any(character in name for character in "/+#"):
        raise ValueError(f"A service name is one topic level without wildcards: {name!r}")
    return f"{require_topic_root(topic_root)}/service/virtual/real/{name}"
