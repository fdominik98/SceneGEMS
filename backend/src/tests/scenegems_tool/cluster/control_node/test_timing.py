import pytest

from scenegems_tool.cluster.control_node.timing import ControlTiming


def test_defaults_and_their_relations():
    timing = ControlTiming()
    assert (timing.heartbeat_interval_s, timing.worker_node_offline_after_s, timing.lease_timeout_s, timing.offer_timeout_s) == (5.0, 15.0, 30.0, 10.0)
    assert timing.renew_interval_s == 10.0
    # a worker node lost right after renewing is requeued within the lease plus one expiry sweep
    assert timing.lease_timeout_s + timing.expiry_sweep_interval_s == 32.0


def test_offline_needs_room_for_a_missed_heartbeat():
    with pytest.raises(ValueError, match="miss at least one heartbeat"):
        ControlTiming(heartbeat_interval_s=10.0, worker_node_offline_after_s=15.0)


def test_periods_must_be_positive():
    with pytest.raises(ValueError, match="lease_timeout_s must be positive"):
        ControlTiming(lease_timeout_s=0)
