import pytest

from scenegems_tool.cluster.worker_node.daemon.control.reconnect_backoff import ReconnectBackoff


def test_delays_double_up_to_the_maximum_and_reset():
    backoff = ReconnectBackoff(initial_s=1.0, maximum_s=10.0, jitter=0.0)
    assert [backoff.next_delay_s() for _ in range(6)] == [1.0, 2.0, 4.0, 8.0, 10.0, 10.0]
    backoff.reset()
    assert backoff.next_delay_s() == 1.0


def test_jitter_spreads_the_delay_around_its_base():
    low = ReconnectBackoff(initial_s=10.0, maximum_s=10.0, jitter=0.2, random_unit=lambda: 0.0)
    high = ReconnectBackoff(initial_s=10.0, maximum_s=10.0, jitter=0.2, random_unit=lambda: 1.0)
    assert low.next_delay_s() == pytest.approx(8.0) and high.next_delay_s() == pytest.approx(12.0)


def test_many_failures_stay_at_the_maximum():
    backoff = ReconnectBackoff(initial_s=1.0, maximum_s=30.0, jitter=0.0)
    for _ in range(5000):
        delay = backoff.next_delay_s()
    assert delay == 30.0


@pytest.mark.parametrize("options", [{"initial_s": 0}, {"initial_s": 5, "maximum_s": 1}, {"factor": 0.5}, {"jitter": 1.0}])
def test_invalid_settings_fail(options):
    with pytest.raises(ValueError):
        ReconnectBackoff(**options)
