"""Topic prefix of one subsystem instance on a shared broker.

A scoped client publishes and subscribes under its prefix and sees incoming topics with
the prefix removed, so subsystem code keeps the topic names it uses on its own broker.
The empty prefix (the workbench) leaves every topic unchanged. Who owns which prefix is
decided by the cluster (`cluster/worker_node/instance_scope.py`); this module only applies it.
"""

from typing import Any, Optional

import paho.mqtt.client as mqtt

_WILDCARDS = ("+", "#")


class TopicScope:
    def __init__(self, prefix: str = ""):
        if prefix and not prefix.endswith("/"):
            raise ValueError(f"A topic prefix must end with '/': {prefix!r}")
        if any(wildcard in prefix for wildcard in _WILDCARDS) or prefix.startswith("/"):
            raise ValueError(f"A topic prefix must be a plain topic path without wildcards: {prefix!r}")
        self.prefix = prefix

    @property
    def is_empty(self) -> bool:
        return not self.prefix

    def apply(self, topic: str) -> str:
        return f"{self.prefix}{topic}"

    def strip(self, topic: str) -> Optional[str]:
        """The topic as the subsystem names it, or None when it lies outside the scope."""
        if not topic.startswith(self.prefix):
            return None
        return topic[len(self.prefix) :]

    def apply_subscription(self, topic: Any) -> Any:
        """Prefix every topic of a paho subscribe or unsubscribe argument (a topic, a pair or a list of either)."""
        if isinstance(topic, str):
            return self.apply(topic)
        if isinstance(topic, tuple):
            return (self.apply(topic[0]), *topic[1:])
        if isinstance(topic, list):
            return [self.apply_subscription(item) for item in topic]
        raise TypeError(f"Unsupported topic argument: {topic!r}")

    def strip_message(self, message: mqtt.MQTTMessage) -> Optional[mqtt.MQTTMessage]:
        """A copy of an incoming message with the scope removed from its topic, or None outside the scope."""
        if self.is_empty:
            return message
        topic = self.strip(message.topic)
        if topic is None:
            return None
        scoped = mqtt.MQTTMessage(mid=message.mid, topic=topic.encode("utf-8"))
        scoped.payload = message.payload
        scoped.qos = message.qos
        scoped.retain = message.retain
        scoped.timestamp = message.timestamp
        scoped.properties = message.properties
        return scoped


class ScopedPahoClient(mqtt.Client):
    """paho client that adds the instance prefix to every topic it publishes or subscribes to."""

    def __init__(self, scope: TopicScope, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scope = scope

    def publish(self, topic: str, payload=None, qos: int = 0, retain: bool = False, properties=None):
        return super().publish(self.scope.apply(topic), payload, qos, retain, properties)

    def subscribe(self, topic, qos: int = 0, options=None, properties=None):
        return super().subscribe(self.scope.apply_subscription(topic), qos, options, properties)

    def unsubscribe(self, topic, properties=None):
        return super().unsubscribe(self.scope.apply_subscription(topic), properties)
