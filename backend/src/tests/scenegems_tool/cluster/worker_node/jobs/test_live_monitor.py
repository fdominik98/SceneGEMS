"""The live COLREGS monitor of the simulation jobs, fed scene by scene."""

from scenegems_tool.cluster.worker_node.jobs.live_monitor import LiveMonitor, SimulationMonitor
from scenegems_tool.subsystems.monitoring.rule_outcomes import RuleOutcomes


def _feed(monitor: LiveMonitor, trajectories) -> int:
    """Feed every step of the trajectories; the index the monitor stopped at, or the last one."""
    columns = [trajectories.state_list(actor) for actor in monitor.actors]
    for index, states in enumerate(zip(*columns)):
        if monitor.on_step(index, states):
            return index
    return len(columns[0]) - 1


def test_the_wire_values_stay():
    assert [member.value for member in SimulationMonitor] == ["none", "live"]


def test_every_step_is_judged_in_the_post_hoc_shape(head_on_trajectories):
    monitor = LiveMonitor(head_on_trajectories.initial_scene.actors, 1, None, early_stop=False)
    assert _feed(monitor, head_on_trajectories) == 120
    result = monitor.result(stopped_early=False)
    assert result["scenes"] == 121 and result["monitored_scenes"] == 121 and result["time_step"] == 1
    assert {"rules", "failed_rules", "passed"} <= set(result) and result["stopped_early_at"] is None
    assert monitor.last_monitored_index == 120 and monitor.last_monitored is not None


def test_early_stop_ends_the_feed_once_every_rule_is_decided(head_on_trajectories, monkeypatch):
    monkeypatch.setattr(RuleOutcomes, "every_rule_decided", lambda outcomes: outcomes.monitored_scenes == 11)
    monitor = LiveMonitor(head_on_trajectories.initial_scene.actors, 1, None, early_stop=True)
    assert _feed(monitor, head_on_trajectories) == 10
    assert monitor.result(stopped_early=True)["stopped_early_at"] == 10
