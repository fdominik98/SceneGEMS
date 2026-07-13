#!/usr/bin/env python3
"""
Passive Gazebo Transport listener.

Subscribes to every advertised topic on the partition. **ArduPilotPlugin**-related
topics (by default any transport name containing ``cmd_thrust``, plus optional
``GZ_BRIDGE_ARDUPLUGIN_TOPIC_SUBSTR`` needles) are logged with a
``[ArduPilotPlugin]`` prefix and, for ``gz.msgs.Double``, a decoded **data**
field (thrust command as published by the plugin). Other topics use ``[gz]``.

Environment:

  ``GZ_PARTITION``: must match the running Gazebo sim (same as compose).

  ``GZ_BRIDGE_TOPIC_POLL_SEC``: how often to scan for new topics (default ``2``).

  ``GZ_BRIDGE_LOG_INTERVAL_SEC``: minimum seconds between log lines **per topic**
  for **non**-ArduPilotPlugin topics (default ``0`` = every message).

  ``GZ_BRIDGE_ARDUPLUGIN_LOG_INTERVAL_SEC``: same, but only for
  ArduPilotPlugin-related topics (default ``0``).

  ``GZ_BRIDGE_ARDUPLUGIN_TOPIC_SUBSTR``: extra comma-separated case-insensitive
  substrings; if any appear in the topic name, the topic is treated as plugin-related.

  ``GZ_BRIDGE_HEX_PREVIEW``: max bytes to append as hex (default ``48``; ``0`` = off).
  Hex is omitted for successfully decoded ``gz.msgs.Double`` on plugin topics unless
  preview is forced positive and you want both (we skip hex when ``Double.data`` is printed).
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections import defaultdict

import gz.transport13 as gz
from gz.msgs10.double_pb2 import Double


def _float_env(name: str, default: str) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


def _int_env(name: str, default: str) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return int(default)


PARTITION = os.environ.get("GZ_PARTITION", "").strip()
POLL_INTERVAL = _float_env("GZ_BRIDGE_TOPIC_POLL_SEC", "2")
LOG_INTERVAL = _float_env("GZ_BRIDGE_LOG_INTERVAL_SEC", "0")
ARDU_LOG_INTERVAL = _float_env("GZ_BRIDGE_ARDUPLUGIN_LOG_INTERVAL_SEC", "0")
HEX_PREVIEW = max(0, _int_env("GZ_BRIDGE_HEX_PREVIEW", "48"))

_ARDU_EXTRA_SUBSTR = os.environ.get("GZ_BRIDGE_ARDUPLUGIN_TOPIC_SUBSTR", "").strip()


def _arduplugin_topic(topic: str) -> bool:
    """Heuristic: topics the ArduPilot Gazebo plugin typically advertises (e.g. cmd_thrust)."""
    t = topic.lower()
    if "cmd_thrust" in t:
        return True
    if not _ARDU_EXTRA_SUBSTR:
        return False
    for needle in _ARDU_EXTRA_SUBSTR.split(","):
        n = needle.strip().lower()
        if n and n in t:
            return True
    return False


def main() -> None:
    opts = gz.NodeOptions()
    if PARTITION:
        opts.partition = PARTITION

    node = gz.Node(opts)
    subscribed: set[str] = set()
    last_log: dict[str, float] = defaultdict(float)
    log_lock = threading.Lock()

    def make_cb(topic_name: str, msg_type_name: str):
        is_ardu = _arduplugin_topic(topic_name)
        interval = ARDU_LOG_INTERVAL if is_ardu else LOG_INTERVAL
        log_key = f"ardu:{topic_name}" if is_ardu else topic_name
        prefix = "[ArduPilotPlugin]" if is_ardu else "[gz]"

        def _cb(data: bytes | memoryview, _info: object) -> None:
            raw = data if isinstance(data, bytes) else bytes(data)
            n = len(raw)
            now = time.monotonic()
            if interval > 0.0:
                with log_lock:
                    prev = last_log[log_key]
                    if now - prev < interval:
                        return
                    last_log[log_key] = now

            decoded = ""
            show_hex = HEX_PREVIEW > 0
            if is_ardu and msg_type_name == "gz.msgs.Double" and n:
                try:
                    d = Double()
                    d.ParseFromString(raw)
                    decoded = f" Double.data={d.data:.6g}"
                    show_hex = False
                except Exception as exc:
                    decoded = f" Double.parse_error={exc!r}"

            hx = ""
            if show_hex and n:
                hx = f" hex={raw[:HEX_PREVIEW].hex()}"

            print(f"{prefix} topic={topic_name!r} msg_type={msg_type_name!r} len={n}{decoded}{hx}", flush=True)

        return _cb

    print(
        "Gazebo transport sniffer: subscribe_raw on all advertised topics; "
        "ArduPilotPlugin-related topics logged with [ArduPilotPlugin]. "
        f"GZ_PARTITION={PARTITION!r} poll_s={POLL_INTERVAL} "
        f"log_interval_s={LOG_INTERVAL} ardu_log_interval_s={ARDU_LOG_INTERVAL} "
        f"hex_preview={HEX_PREVIEW} ardu_substr_extra={_ARDU_EXTRA_SUBSTR!r}",
        flush=True,
    )

    while True:
        try:
            topics = node.topic_list()
        except Exception as exc:
            print(f"[gz] topic_list error: {exc}", file=sys.stderr, flush=True)
            time.sleep(POLL_INTERVAL)
            continue

        for topic in topics:
            if topic in subscribed:
                continue
            try:
                pubs, _subs = node.topic_info(topic)
            except Exception as exc:
                print(f"[gz] topic_info({topic!r}) error: {exc}", file=sys.stderr, flush=True)
                continue
            if not pubs:
                continue
            msg_type = pubs[0].msg_type_name
            if not msg_type:
                continue
            cb = make_cb(topic, msg_type)
            ok = node.subscribe_raw(topic, cb, msg_type, gz.SubscribeOptions())
            if ok:
                subscribed.add(topic)
                tag = "[ArduPilotPlugin]" if _arduplugin_topic(topic) else "[gz]"
                print(f"{tag} subscribed topic={topic!r} msg_type={msg_type!r}", flush=True)
            else:
                print(
                    f"[gz] subscribe_raw failed topic={topic!r} msg_type={msg_type!r}",
                    file=sys.stderr,
                    flush=True,
                )

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("exit", flush=True)
