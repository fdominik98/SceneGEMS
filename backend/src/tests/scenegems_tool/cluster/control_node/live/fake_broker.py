"""A stand-in for the observation hub's broker client: it records subscriptions and delivers messages from its own thread."""

import json
import threading
from typing import Callable, List, Optional


class FakeBroker:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0
        self.calls: List[tuple] = []
        self.filters: List[str] = []
        self.on_message: Optional[Callable[[str, bytes], None]] = None

    def start(self, on_message: Callable[[str, bytes], None]) -> None:
        self.started += 1
        self.on_message = on_message

    def subscribe(self, topic_filter: str) -> None:
        self.calls.append(("subscribe", topic_filter))
        self.filters.append(topic_filter)

    def unsubscribe(self, topic_filter: str) -> None:
        self.calls.append(("unsubscribe", topic_filter))
        self.filters.remove(topic_filter)

    def stop(self) -> None:
        self.stopped += 1

    def publish_from_its_thread(self, topic: str, message: dict) -> None:
        """A message as the broker client's network thread hands it over."""
        thread = threading.Thread(target=self.on_message, args=(topic, json.dumps(message).encode("utf-8")))
        thread.start()
        thread.join()
