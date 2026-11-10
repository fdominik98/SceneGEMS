"""The live channel: browser connections, their topic subscriptions and the updates the control node pushes.

Each WebSocket on LIVE_PATH (api/live_routes.py) is one LiveConnection. A topic's subscribers
are counted across connections: the first one activates the topic at its source (topics.py,
observation_hub.py), the last one to leave deactivates it, and a connection that closes
leaves every topic it held. Producers publish only to topics somebody subscribed to, and
LiveChannel.has_subscribers is the check that keeps their hooks free otherwise.

Ordering. A subscribe first queues a placeholder for its `subscribed` message, registers the
subscriber and then asks the source for the snapshot. Updates published meanwhile queue
behind the placeholder, so the snapshot always arrives first. A source reads its in-memory
state (job progress, log lines) before its first await, which runs in the same step as the
registration, so nothing kept in memory is missed or repeated; state read from the database
afterwards may repeat in an update, which replaces it.

Delivery. Each connection has a bounded outbox. State updates are never dropped: a connection
whose outbox is full is closed (code 1013), and its client resubscribes and gets snapshots.
Rated updates (previews, frames) go through a RateLimiter per topic and stream, which sends
at most one per interval and merges what arrives in between; in a connection's outbox an
unsent rated update of the same stream is merged as well, and one that finds the outbox
full is dropped.

Options. A subscribe may carry options and a configure message changes them while subscribed;
the topic's source takes them (TopicSource.configure, which only job instance topics have) before
the subscriber is registered, so the activation already sees them.

Everything here runs on the control node's event loop; the observation hub hands broker messages
over with call_soon_threadsafe.
"""

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Callable, Deque, Dict, Mapping, Optional, Protocol, Set, Tuple

import anyio
from pydantic import BaseModel
from starlette.websockets import WebSocket, WebSocketDisconnect

from scenegems_tool.cluster.protocol.live import (
    LIVE_VERSION,
    Configure,
    InvalidLiveMessage,
    InvalidTopic,
    Ping,
    Subscribe,
    Topic,
    TopicKind,
    TopicOptions,
    Unsubscribe,
    decode_client_message,
    parse_topic,
)

logger = logging.getLogger(__name__)

CLOSE_TOO_SLOW = 1013  # "try again later": the connection could not keep up with its state updates

Merge = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]


class UnknownTopic(LookupError):
    """The topic names nothing this control node knows (no such campaign, job, worker node or instance), or it cannot be served."""


class InvalidOptions(ValueError):
    """The topic takes no options, or not these."""


class TopicSource(Protocol):
    """What serves one kind of topic: its snapshot, and its producers' start and stop."""

    async def snapshot(self, topic: Topic) -> Any:
        """The topic's current state, JSON-ready; raises UnknownTopic. Reads in-memory state before its first await."""

    def activate(self, topic: Topic) -> None:
        """The topic got its first subscriber."""

    def deactivate(self, topic: Topic) -> None:
        """The topic's last subscriber left."""

    # Optional: def configure(self, topic: Topic, options: TopicOptions) -> None, raising InvalidOptions.
    # A source without it takes no options.


@dataclass(frozen=True)
class LiveSettings:
    queue_limit: int = 2000  # messages waiting for one connection; a state update past it closes the connection
    max_subscriptions: int = 256  # per connection
    preview_interval_s: float = 0.25  # scene samples and trajectory previews: at most 4 per second and topic
    frames_interval_s: float = 0.1  # simulation frames: at most 10 updates per second and topic
    max_frames_per_update: int = 200  # coalesced frames beyond this drop the oldest


@dataclass(frozen=True)
class RateLimit:
    interval_s: float
    merge: Merge


def latest(_older: Dict[str, Any], newer: Dict[str, Any]) -> Dict[str, Any]:
    """Merge of previews: the newer one replaces the unsent one."""
    return newer


def joined_frames(max_frames: int) -> Merge:
    """Merge of frame batches: the frames joined in order, the newest max_frames kept."""

    def merge(older: Dict[str, Any], newer: Dict[str, Any]) -> Dict[str, Any]:
        frames = list(older.get("frames", [])) + list(newer.get("frames", []))
        return {**newer, "frames": frames[-max_frames:]}

    return merge


class RateLimiter:
    """At most one update per interval for one stream of a topic; what arrives in between is merged and sent when due."""

    def __init__(self, limit: RateLimit):
        self.limit = limit
        self.pending: Optional[Dict[str, Any]] = None
        self.last_sent: Optional[float] = None

    def offer(self, now: float, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The update to send now, or None when it waits (merged into the pending one)."""
        if self.pending is None and (self.last_sent is None or now - self.last_sent >= self.limit.interval_s):
            self.last_sent = now
            return data
        self.pending = data if self.pending is None else self.limit.merge(self.pending, data)
        return None

    @property
    def due_at(self) -> Optional[float]:
        if self.pending is None:
            return None
        return (self.last_sent or 0.0) + self.limit.interval_s

    def flush(self, now: float) -> Optional[Dict[str, Any]]:
        """The pending update once it is due; None before."""
        due = self.due_at
        if due is None or now < due:
            return None
        data, self.pending, self.last_sent = self.pending, None, now
        return data


def to_json(message: Mapping[str, Any]) -> str:
    return json.dumps(message, default=_jsonable, separators=(",", ":"))


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


# One connection


class _Entry:
    """One queued message. A placeholder waits for its content (a subscribed message whose snapshot is being read)."""

    __slots__ = ("topic", "kind", "payload", "stream", "merge", "ready", "cancelled")

    def __init__(self, topic: Optional[str], kind: str, payload: Any = None, stream: str = "", merge: Optional[Merge] = None, ready: Optional[asyncio.Event] = None):
        self.topic = topic
        self.kind = kind  # message, update, rated or placeholder
        self.payload = payload
        self.stream = stream
        self.merge = merge
        self.ready = ready
        self.cancelled = False

    def fill(self, message: Dict[str, Any]) -> None:
        self.payload = message
        if self.ready is not None:
            self.ready.set()

    def cancel(self) -> None:
        self.cancelled = True
        if self.ready is not None:
            self.ready.set()


class Outbox:
    """A connection's queue: bounded, with rated updates merged per (topic, stream) while unsent."""

    def __init__(self, limit: int):
        self.limit = limit
        self.overflowed = False
        self._entries: Deque[_Entry] = deque()
        self._rated: Dict[Tuple[str, str], _Entry] = {}
        self._wake = asyncio.Event()

    def __len__(self) -> int:
        return len(self._entries)

    def put(self, entry: _Entry) -> bool:
        """Queues a message that must not be dropped; False (and overflowed) when the outbox is full."""
        if self.overflowed:
            return False
        if len(self._entries) >= self.limit:
            self.overflowed = True
            self._wake.set()
            return False
        self._entries.append(entry)
        self._wake.set()
        return True

    def put_rated(self, topic: str, stream: str, data: Dict[str, Any], merge: Merge) -> None:
        """Queues a rated update, merged into an unsent one of the same stream; dropped when the outbox is full."""
        if self.overflowed:
            return
        waiting = self._rated.get((topic, stream))
        if waiting is not None:
            waiting.payload = merge(waiting.payload, data)
            return
        if len(self._entries) >= self.limit:
            return
        entry = _Entry(topic, "rated", data, stream, merge)
        self._rated[(topic, stream)] = entry
        self._entries.append(entry)
        self._wake.set()

    def discard(self, topic: str) -> None:
        """Drops every unsent message of the topic; a waiting placeholder is cancelled."""
        kept: Deque[_Entry] = deque()
        for entry in self._entries:
            if entry.topic == topic:
                entry.cancel()
            else:
                kept.append(entry)
        self._entries = kept
        for key in [key for key in self._rated if key[0] == topic]:
            del self._rated[key]

    async def next(self) -> Optional[_Entry]:
        """The next message, waiting for one; None once the outbox overflowed."""
        while not self._entries:
            if self.overflowed:
                return None
            self._wake.clear()
            await self._wake.wait()
        if self.overflowed:
            return None
        entry = self._entries.popleft()
        if entry.kind == "rated":
            self._rated.pop((entry.topic, entry.stream), None)
        return entry


class LiveConnection:
    def __init__(self, websocket: WebSocket, settings: LiveSettings):
        self.websocket = websocket
        self.settings = settings
        self.topics: Set[str] = set()  # subscribed, by name
        self.outbox = Outbox(settings.queue_limit)
        self._seq: Dict[str, int] = {}
        self._placeholders: Dict[str, _Entry] = {}

    # Queueing (on the event loop)

    def message(self, message: Dict[str, Any], topic: Optional[str] = None) -> None:
        self.outbox.put(_Entry(topic, "message", message))

    def error(self, message: str, topic: Optional[str] = None) -> None:
        error: Dict[str, Any] = {"version": LIVE_VERSION, "type": "error", "message": message}
        if topic is not None:
            error["topic"] = topic
        self.message(error)

    def update(self, topic: str, data: Dict[str, Any]) -> None:
        if topic in self.topics:
            self.outbox.put(_Entry(topic, "update", data))

    def rated(self, topic: str, stream: str, data: Dict[str, Any], merge: Merge) -> None:
        if topic in self.topics:
            self.outbox.put_rated(topic, stream, data, merge)

    def begin_subscription(self, topic: str) -> _Entry:
        """Queues the placeholder of the topic's subscribed message; older unsent messages of the topic go, its seq restarts."""
        self._cancel_placeholder(topic)
        self.outbox.discard(topic)
        self._seq[topic] = 0
        entry = _Entry(topic, "placeholder", ready=asyncio.Event())
        self._placeholders[topic] = entry
        self.outbox.put(entry)
        return entry

    def end_subscription(self, topic: str) -> None:
        self.topics.discard(topic)
        self._cancel_placeholder(topic)
        self.outbox.discard(topic)
        self._seq.pop(topic, None)

    def _cancel_placeholder(self, topic: str) -> None:
        """A placeholder may already be with the sender, which waits for it: cancelling releases it."""
        placeholder = self._placeholders.pop(topic, None)
        if placeholder is not None:
            placeholder.cancel()

    def current_placeholder(self, topic: str) -> Optional[_Entry]:
        return self._placeholders.get(topic)

    # Sending

    async def send_loop(self) -> None:
        """Sends queued messages in order until the outbox overflows or the socket fails."""
        while True:
            entry = await self.outbox.next()
            if entry is None:
                return
            if entry.ready is not None and not entry.ready.is_set():
                await entry.ready.wait()
            if entry.cancelled:
                continue
            await self.websocket.send_text(to_json(self._message_of(entry)))

    def _message_of(self, entry: _Entry) -> Dict[str, Any]:
        if entry.kind in ("update", "rated"):
            seq = self._seq.get(entry.topic, 0) + 1
            self._seq[entry.topic] = seq
            return {"version": LIVE_VERSION, "type": "update", "topic": entry.topic, "seq": seq, "data": entry.payload}
        if entry.kind == "placeholder" and self._placeholders.get(entry.topic) is entry:
            del self._placeholders[entry.topic]
        return entry.payload


# The channel


@dataclass
class _TopicState:
    topic: Topic
    connections: Set[LiveConnection] = field(default_factory=set)
    limiters: Dict[str, RateLimiter] = field(default_factory=dict)
    timer: Optional[asyncio.TimerHandle] = None


class LiveChannel:
    def __init__(self, settings: LiveSettings = LiveSettings(), clock: Callable[[], float] = time.monotonic):
        self.settings = settings
        self._clock = clock
        self._sources: Dict[TopicKind, TopicSource] = {}
        self._topics: Dict[str, _TopicState] = {}
        self._connections: Set[LiveConnection] = set()
        self.preview_rate = RateLimit(settings.preview_interval_s, latest)
        self.frames_rate = RateLimit(settings.frames_interval_s, joined_frames(settings.max_frames_per_update))
        self.producers: Any = None  # topics.LiveProducers, set by create_live_channel

    async def close(self) -> None:
        """Stops the producers' tasks and the observation hub's broker connection (the operator listener's shutdown)."""
        for state in self._topics.values():
            if state.timer is not None:
                state.timer.cancel()
        if self.producers is not None:
            await self.producers.close()

    def add_source(self, kind: TopicKind, source: TopicSource) -> None:
        self._sources[kind] = source

    def source(self, kind: TopicKind) -> Optional[TopicSource]:
        return self._sources.get(kind)

    # Queries

    def has_subscribers(self, topic: str) -> bool:
        return topic in self._topics

    def subscriber_count(self, topic: str) -> int:
        state = self._topics.get(topic)
        return 0 if state is None else len(state.connections)

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    def topics(self) -> Set[str]:
        return set(self._topics)

    # Publishing (on the event loop)

    def publish(self, topic: str, data: Dict[str, Any]) -> None:
        """A state update for every subscriber of the topic; nothing when it has none."""
        state = self._topics.get(topic)
        if state is None:
            return
        for connection in list(state.connections):
            connection.update(topic, data)

    def publish_rated(self, topic: str, stream: str, data: Dict[str, Any], limit: RateLimit) -> None:
        """A preview or frames update, at most one per interval for the topic's stream; nothing when the topic has no subscriber."""
        state = self._topics.get(topic)
        if state is None:
            return
        limiter = state.limiters.get(stream)
        if limiter is None:
            limiter = state.limiters[stream] = RateLimiter(limit)
        ready = limiter.offer(self._clock(), data)
        if ready is not None:
            self._fan_out_rated(state, stream, ready)
        else:
            self._schedule_flush(state)

    def _fan_out_rated(self, state: _TopicState, stream: str, data: Dict[str, Any]) -> None:
        merge = state.limiters[stream].limit.merge
        for connection in list(state.connections):
            connection.rated(state.topic.name, stream, data, merge)

    def _schedule_flush(self, state: _TopicState) -> None:
        if state.timer is not None:
            return
        due = [limiter.due_at for limiter in state.limiters.values() if limiter.due_at is not None]
        if not due:
            return
        delay = max(0.0, min(due) - self._clock())
        state.timer = asyncio.get_running_loop().call_later(delay, self.flush_rated, state.topic.name)

    def flush_rated(self, topic: str) -> None:
        """Sends the topic's pending rated updates that are due (the flush timer calls it)."""
        state = self._topics.get(topic)
        if state is None:
            return
        state.timer = None
        now = self._clock()
        for stream, limiter in state.limiters.items():
            data = limiter.flush(now)
            if data is not None:
                self._fan_out_rated(state, stream, data)
        self._schedule_flush(state)

    # Connections

    async def serve(self, websocket: WebSocket) -> None:
        """One browser connection, from accept to close; every subscription it held ends with it."""
        await websocket.accept()
        connection = LiveConnection(websocket, self.settings)
        self._connections.add(connection)
        try:
            async with anyio.create_task_group() as parts:
                # Whichever part ends first (the client left, the socket failed, the outbox overflowed) ends the other
                parts.start_soon(self._part, connection.send_loop(), parts.cancel_scope)
                parts.start_soon(self._part, self._receive_loop(connection), parts.cancel_scope)
        finally:
            self.drop(connection)
        if connection.outbox.overflowed:
            logger.warning("A live connection fell %d messages behind and was closed", connection.outbox.limit)
            try:
                await websocket.close(CLOSE_TOO_SLOW, "too slow: resubscribe")
            except Exception:
                pass

    @staticmethod
    async def _part(work, scope: anyio.CancelScope) -> None:
        try:
            await work
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass  # the socket is gone; RuntimeError is starlette's answer to a send after the close
        except Exception:
            logger.exception("A live connection failed")
        finally:
            scope.cancel()

    async def _receive_loop(self, connection: LiveConnection) -> None:
        while True:
            received = await connection.websocket.receive()
            if received["type"] == "websocket.disconnect":
                return
            text = received.get("text")
            if text is None:
                text = (received.get("bytes") or b"").decode("utf-8", "replace")
            try:
                message = decode_client_message(text)
            except InvalidLiveMessage as error:
                connection.error(str(error))
                continue
            if isinstance(message, Ping):
                connection.message({"version": LIVE_VERSION, "type": "pong"})
            elif isinstance(message, Subscribe):
                await self.subscribe(connection, message.topic, message.options)
            elif isinstance(message, Configure):
                self.configure(connection, message.topic, message.options)
            elif isinstance(message, Unsubscribe):
                self.unsubscribe(connection, message.topic)

    async def subscribe(self, connection: LiveConnection, name: str, options: Optional[TopicOptions] = None) -> None:
        try:
            topic = parse_topic(name)
        except InvalidTopic as error:
            connection.error(str(error), name)
            return
        source = self._sources.get(topic.kind)
        if source is None:
            connection.error(f"this control node does not serve {topic.kind.value} topics", name)
            return
        if topic.name not in connection.topics and len(connection.topics) >= self.settings.max_subscriptions:
            connection.error(f"at most {self.settings.max_subscriptions} subscriptions per connection", name)
            return
        if options is not None and not self._configure(connection, source, topic, options):
            return
        placeholder = connection.begin_subscription(topic.name)
        self._add(connection, topic, source)
        try:
            snapshot = await source.snapshot(topic)
        except UnknownTopic as error:
            self._leave(connection, topic.name)
            connection.error(str(error), topic.name)
            return
        except Exception as error:
            logger.exception("The snapshot of live topic %s failed", topic.name)
            self._leave(connection, topic.name)
            connection.error(f"the topic could not be read: {type(error).__name__}: {error}", topic.name)
            return
        if connection.current_placeholder(topic.name) is placeholder:
            placeholder.fill({"version": LIVE_VERSION, "type": "subscribed", "topic": topic.name, "snapshot": snapshot})

    def configure(self, connection: LiveConnection, name: str, options: TopicOptions) -> None:
        """Changes the options of a topic the connection subscribed to."""
        if name not in connection.topics:
            connection.error("not subscribed", name)
            return
        state = self._topics.get(name)
        source = self._sources.get(state.topic.kind) if state is not None else None
        if source is not None:
            self._configure(connection, source, state.topic, options)

    def _configure(self, connection: LiveConnection, source: TopicSource, topic: Topic, options: TopicOptions) -> bool:
        configure = getattr(source, "configure", None)
        try:
            if configure is None:
                raise InvalidOptions(f"{topic.kind.value} topics take no options")
            configure(topic, options)
        except InvalidOptions as error:
            connection.error(str(error), topic.name)
            return False
        return True

    def unsubscribe(self, connection: LiveConnection, name: str) -> None:
        if name not in connection.topics:
            connection.error("not subscribed", name)
            return
        self._leave(connection, name)
        connection.message({"version": LIVE_VERSION, "type": "unsubscribed", "topic": name})

    def drop(self, connection: LiveConnection) -> None:
        """The connection closed: it leaves every topic it held."""
        for name in list(connection.topics):
            self._leave(connection, name)
        self._connections.discard(connection)

    def _add(self, connection: LiveConnection, topic: Topic, source: TopicSource) -> None:
        connection.topics.add(topic.name)
        state = self._topics.get(topic.name)
        if state is None:
            state = self._topics[topic.name] = _TopicState(topic)
        if connection in state.connections:
            return
        state.connections.add(connection)
        if len(state.connections) == 1:
            self._call(source.activate, topic)

    def _leave(self, connection: LiveConnection, name: str) -> None:
        connection.end_subscription(name)
        state = self._topics.get(name)
        if state is None or connection not in state.connections:
            return
        state.connections.discard(connection)
        if state.connections:
            return
        del self._topics[name]
        if state.timer is not None:
            state.timer.cancel()
        source = self._sources.get(state.topic.kind)
        if source is not None:
            self._call(source.deactivate, state.topic)

    @staticmethod
    def _call(action: Callable[[Topic], None], topic: Topic) -> None:
        try:
            action(topic)
        except Exception:
            logger.exception("%s of live topic %s failed", getattr(action, "__name__", "activation"), topic.name)
