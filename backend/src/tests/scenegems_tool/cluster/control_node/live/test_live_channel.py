"""The live channel: subscriptions counted across connections, ordering, bounded outboxes and rate limits."""

import asyncio

import pytest

from scenegems_tool.cluster.control_node.live.live_channel import CLOSE_TOO_SLOW, InvalidOptions, LiveConnection, LiveSettings, Outbox, RateLimit, RateLimiter, joined_frames, latest
from scenegems_tool.cluster.protocol.live import TopicKind
from tests.scenegems_tool.cluster.control_node.live.conftest import Browser, FakeWebSocket, settle

pytestmark = pytest.mark.anyio


def _types(messages):
    return [message["type"] for message in messages]


async def test_a_subscription_gets_its_snapshot_then_numbered_updates(make_channel):
    channel = make_channel()
    browser = Browser(channel)
    browser.socket.subscribe("job:a")
    await settle()
    channel.publish("job:a", {"job": {"state": "running"}})
    channel.publish("job:a", {"logs": [{"text": "hello"}]})
    await settle()
    subscribed, first, second = browser.socket.take()
    assert subscribed == {"version": 1, "type": "subscribed", "topic": "job:a", "snapshot": {"job_id": "a"}}
    assert (first["type"], first["seq"], first["data"]) == ("update", 1, {"job": {"state": "running"}})
    assert (second["seq"], second["data"]) == (2, {"logs": [{"text": "hello"}]})
    await browser.leave()


async def test_subscribers_are_counted_across_connections(make_channel, source):
    channel = make_channel()
    first, second = Browser(channel), Browser(channel)
    first.socket.subscribe("job:a")
    second.socket.subscribe("job:a")
    await settle()
    assert source.activated == ["job:a"] and channel.subscriber_count("job:a") == 2

    first.socket.unsubscribe("job:a")
    await settle()
    assert _types(first.socket.take()) == ["subscribed", "unsubscribed"]
    assert source.deactivated == [] and channel.subscriber_count("job:a") == 1

    channel.publish("job:a", {"n": 1})
    await settle()
    assert first.socket.take() == []
    assert _types(second.socket.take()) == ["subscribed", "update"]

    await second.leave()
    assert source.deactivated == ["job:a"] and not channel.has_subscribers("job:a")
    assert channel.connection_count == 1
    await first.leave()
    assert channel.connection_count == 0


async def test_disconnecting_drops_every_subscription_of_the_connection(make_channel, source):
    channel = make_channel()
    browser = Browser(channel)
    browser.socket.subscribe("job:a")
    browser.socket.subscribe("job:b")
    await settle()
    assert channel.topics() == {"job:a", "job:b"}
    await browser.leave()
    assert channel.topics() == set() and sorted(source.deactivated) == ["job:a", "job:b"]


async def test_nothing_is_sent_or_kept_for_a_topic_nobody_subscribed_to(make_channel):
    channel = make_channel()
    browser = Browser(channel)
    browser.socket.subscribe("job:a")
    await settle()
    browser.socket.take()
    channel.publish("job:b", {"n": 1})
    channel.publish_rated("job:b", "preview", {"n": 1}, channel.preview_rate)
    await settle()
    assert browser.socket.take() == [] and channel.topics() == {"job:a"}
    await browser.leave()


async def test_an_unknown_topic_is_answered_with_an_error_and_counts_nothing(make_channel, source):
    channel = make_channel()
    browser = Browser(channel)
    browser.socket.subscribe("job:missing")
    browser.socket.subscribe("bogus")
    browser.socket.subscribe("campaign:c1")  # no campaign source on this channel
    await settle()
    errors = browser.socket.take()
    assert [(error["type"], error["topic"]) for error in errors] == [("error", "job:missing"), ("error", "bogus"), ("error", "campaign:c1")]
    assert "no job missing" in errors[0]["message"] and "not serve campaign" in errors[2]["message"]
    assert channel.topics() == set() and source.activated == ["job:missing"] and source.deactivated == ["job:missing"]
    await browser.leave()


async def test_a_snapshot_that_fails_after_the_sender_took_its_placeholder_does_not_stall_the_connection(make_channel, source):
    channel = make_channel()
    source.slow["missing"] = asyncio.Event()
    browser = Browser(channel)
    browser.socket.subscribe("job:missing")
    await settle()  # the sender now waits for the placeholder
    source.slow["missing"].set()
    browser.socket.client_sends({"version": 1, "type": "ping"})
    await settle()
    error, pong = browser.socket.take()
    assert (error["type"], error["topic"], pong["type"]) == ("error", "job:missing", "pong")
    await browser.leave()


async def test_pings_bad_messages_and_unknown_unsubscribes(make_channel):
    channel = make_channel()
    browser = Browser(channel)
    browser.socket.client_sends({"version": 1, "type": "ping"})
    browser.socket.client_sends_text("not json")
    browser.socket.client_sends({"version": 7, "type": "ping"})
    browser.socket.unsubscribe("job:a")
    await settle()
    pong, bad_json, bad_version, not_subscribed = browser.socket.take()
    assert pong == {"version": 1, "type": "pong"}
    assert bad_json["type"] == "error" and "not JSON" in bad_json["message"]
    assert "version 7" in bad_version["message"]
    assert not_subscribed == {"version": 1, "type": "error", "message": "not subscribed", "topic": "job:a"}
    await browser.leave()


async def test_updates_published_while_the_snapshot_is_read_follow_it(make_channel, source):
    channel = make_channel()
    source.slow["a"] = asyncio.Event()
    browser = Browser(channel)
    browser.socket.subscribe("job:a")
    await settle()
    assert channel.has_subscribers("job:a") and browser.socket.sent == []
    channel.publish("job:a", {"logs": [{"text": "during the snapshot"}]})
    await settle()
    assert browser.socket.sent == []  # held behind the snapshot
    source.slow["a"].set()
    await settle()
    subscribed, update = browser.socket.take()
    assert subscribed["type"] == "subscribed" and update["seq"] == 1 and update["data"]["logs"][0]["text"] == "during the snapshot"
    await browser.leave()


async def test_subscribing_again_sends_a_fresh_snapshot_and_restarts_seq(make_channel, source):
    channel = make_channel()
    browser = Browser(channel)
    browser.socket.subscribe("job:a")
    await settle()
    channel.publish("job:a", {"n": 1})
    await settle()
    source.state["a"] = {"job_id": "a", "state": "succeeded"}
    browser.socket.subscribe("job:a")
    await settle()
    channel.publish("job:a", {"n": 2})
    await settle()
    messages = browser.socket.take()
    assert _types(messages) == ["subscribed", "update", "subscribed", "update"]
    assert messages[2]["snapshot"]["state"] == "succeeded" and messages[3]["seq"] == 1
    assert source.activated == ["job:a"] and channel.subscriber_count("job:a") == 1
    await browser.leave()


async def test_a_connection_holds_a_bounded_number_of_subscriptions(make_channel):
    channel = make_channel(max_subscriptions=1)
    browser = Browser(channel)
    browser.socket.subscribe("job:a")
    browser.socket.subscribe("job:b")
    await settle()
    subscribed, refused = browser.socket.take()
    assert subscribed["type"] == "subscribed" and refused["type"] == "error" and "at most 1" in refused["message"]
    await browser.leave()


async def test_a_client_too_slow_for_its_state_updates_is_closed_and_its_subscriptions_end(make_channel, source):
    channel = make_channel(queue_limit=3)
    browser = Browser(channel)
    browser.socket.subscribe("job:a")
    await settle()
    browser.socket.take()
    browser.socket.gate = asyncio.Event()  # the client stops reading
    for index in range(6):
        channel.publish("job:a", {"n": index})
    await settle()
    browser.socket.gate.set()
    await browser.task
    assert browser.socket.closed == CLOSE_TOO_SLOW
    assert source.deactivated == ["job:a"] and channel.connection_count == 0


async def test_rated_updates_are_merged_while_unsent_and_never_close_the_connection(make_channel):
    channel = make_channel(queue_limit=2, preview_interval_s=0.0)
    browser = Browser(channel)
    browser.socket.subscribe("job:a")
    await settle()
    browser.socket.take()
    browser.socket.gate = asyncio.Event()
    channel.publish("job:a", {"state": 1})  # taken by the blocked sender
    await settle()
    for index in range(5):
        channel.publish_rated("job:a", "scene_sample", {"kind": "scene_sample", "n": index}, channel.preview_rate)
    channel.publish_rated("job:a", "frames", {"kind": "simulation_frames", "frames": [1]}, RateLimit(0.0, joined_frames(3)))
    channel.publish_rated("job:a", "frames", {"kind": "simulation_frames", "frames": [2, 3]}, RateLimit(0.0, joined_frames(3)))
    channel.publish_rated("job:a", "frames", {"kind": "simulation_frames", "frames": [4]}, RateLimit(0.0, joined_frames(3)))
    await settle()
    browser.socket.gate.set()
    await settle()
    state, sample, frames = browser.socket.take()
    assert state["data"] == {"state": 1}
    assert sample["data"] == {"kind": "scene_sample", "n": 4} and sample["seq"] == 2
    assert frames["data"]["frames"] == [2, 3, 4]
    assert browser.socket.closed is None
    await browser.leave()


async def test_the_channel_sends_at_most_one_rated_update_per_interval(make_channel, monotonic):
    channel = make_channel(preview_interval_s=0.25)
    browser = Browser(channel)
    browser.socket.subscribe("job:a")
    await settle()
    browser.socket.take()
    for index in range(3):
        channel.publish_rated("job:a", "trajectory_preview", {"n": index}, channel.preview_rate)
    await settle()
    assert [message["data"] for message in browser.socket.take()] == [{"n": 0}]
    channel.flush_rated("job:a")  # not due yet
    await settle()
    assert browser.socket.take() == []
    monotonic.advance(0.25)
    channel.flush_rated("job:a")
    await settle()
    assert [message["data"] for message in browser.socket.take()] == [{"n": 2}]
    await browser.leave()


# The parts


def test_a_rate_limiter_sends_the_first_at_once_and_merges_the_rest_until_due():
    limiter = RateLimiter(RateLimit(1.0, joined_frames(10)))
    assert limiter.offer(10.0, {"frames": [1]}) == {"frames": [1]}
    assert limiter.offer(10.2, {"frames": [2]}) is None
    assert limiter.offer(10.4, {"frames": [3]}) is None
    assert limiter.due_at == 11.0
    assert limiter.flush(10.9) is None
    assert limiter.flush(11.0) == {"frames": [2, 3]}
    assert limiter.due_at is None
    assert limiter.offer(11.5, {"frames": [4]}) is None  # within the interval of the flush
    assert limiter.offer(12.0, {"frames": [5]}) is None  # something is pending, so it waits its turn
    assert limiter.flush(12.0) == {"frames": [4, 5]}


def test_merges():
    assert latest({"n": 1}, {"n": 2}) == {"n": 2}
    assert joined_frames(2)({"job_id": "j", "frames": [1, 2]}, {"job_id": "j", "frames": [3]}) == {"job_id": "j", "frames": [2, 3]}


async def test_an_outbox_bounds_state_messages_and_drops_rated_ones_when_full():
    outbox = Outbox(limit=2)
    connection = LiveConnection(FakeWebSocket(), LiveSettings(queue_limit=2))
    connection.topics.add("t")
    connection.outbox = outbox
    connection.update("t", {"n": 1})
    connection.rated("t", "s", {"n": 2}, latest)
    connection.rated("t", "s", {"n": 3}, latest)  # merged into the waiting one
    connection.rated("t", "other", {"n": 4}, latest)  # full: dropped
    assert len(outbox) == 2 and not outbox.overflowed
    connection.update("t", {"n": 5})  # a state update past the limit
    assert outbox.overflowed
    assert await outbox.next() is None


async def test_unsubscribing_discards_unsent_updates_of_the_topic():
    connection = LiveConnection(FakeWebSocket(), LiveSettings())
    connection.topics.update({"t", "u"})
    connection.update("t", {"n": 1})
    connection.update("u", {"n": 2})
    connection.rated("t", "s", {"n": 3}, latest)
    connection.end_subscription("t")
    entry = await connection.outbox.next()
    assert entry.topic == "u" and len(connection.outbox) == 0
    connection.update("t", {"n": 4})  # no longer subscribed
    assert len(connection.outbox) == 0


class ConfigurableSource:
    """A job topic source that takes options and records when they arrive, relative to its activation."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.events = []

    async def snapshot(self, topic):
        return await self.inner.snapshot(topic)

    def activate(self, topic) -> None:
        self.events.append(("activate", topic.name))

    def deactivate(self, topic) -> None:
        self.events.append(("deactivate", topic.name))

    def configure(self, topic, options) -> None:
        if options.speed == 999:
            raise InvalidOptions("not this speed")
        self.events.append(("configure", topic.name, options.speed))


async def test_options_reach_the_source_before_its_activation_and_with_each_configure(make_channel, source):
    channel = make_channel()
    configurable = ConfigurableSource(source)
    channel.add_source(TopicKind.JOB, configurable)
    browser = Browser(channel)
    browser.socket.client_sends({"version": 1, "type": "subscribe", "topic": "job:a", "options": {"speed": 30}})
    await settle()
    browser.socket.client_sends({"version": 1, "type": "configure", "topic": "job:a", "options": {"speed": 60}})
    browser.socket.client_sends({"version": 1, "type": "configure", "topic": "job:a", "options": {"speed": 999}})
    browser.socket.client_sends({"version": 1, "type": "subscribe", "topic": "job:b", "options": {"speed": 999}})
    await settle()
    assert configurable.events == [("configure", "job:a", 30.0), ("activate", "job:a"), ("configure", "job:a", 60.0)]
    subscribed, refused_configure, refused_subscribe = browser.socket.take()
    assert subscribed["type"] == "subscribed"
    assert refused_configure == {"version": 1, "type": "error", "message": "not this speed", "topic": "job:a"}
    assert refused_subscribe == {"version": 1, "type": "error", "message": "not this speed", "topic": "job:b"}
    assert channel.topics() == {"job:a"}  # a refused option subscribes nothing
    await browser.leave()


async def test_a_source_without_configure_takes_no_options(make_channel, source):
    channel = make_channel()
    browser = Browser(channel)
    browser.socket.client_sends({"version": 1, "type": "subscribe", "topic": "job:a", "options": {"speed": 30}})
    await settle()
    (error,) = browser.socket.take()
    assert error == {"version": 1, "type": "error", "message": "job topics take no options", "topic": "job:a"}
    assert source.activated == []
    await browser.leave()
