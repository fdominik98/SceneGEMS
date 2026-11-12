"""The worker of a monitoring task: a series judged batch by batch gives what one monitor over the whole series gives, and a series that cannot be judged fails."""

import os
from typing import Any, List, Optional

import pytest

from scenegems_tool.gateway.serialization import serialize_monitored_frame
from scenegems_tool.subsystems.monitoring import monitoring_worker
from scenegems_tool.subsystems.monitoring.monitoring_types import CLOSE_SIGNAL, MONITOR_RESULT_STREAM, MONITORED_SCENE_STREAM, SCENES_SIGNAL, MonitorScenarioTask
from scenegems_tool.subsystems.monitoring.monitoring_worker import SeriesError, SeriesMonitor, monitor_series
from scenegems_tool.subsystems.monitoring.rule_outcomes import RuleOutcomes
from scenegems_tool.subsystems.pool.pool_task import TaskSignal
from tests.concrete_level.colregs_monitoring.monitor_runs import monitored_run
from tests.scenegems_tool.subsystems.pool.pool_fakes import RecordingChannel
from utils.file_system_utils import COLREGS_CONSTANTS_FOLDER

TARGET_START = (200.0, -200.0)
STEPS = 7
CANCEL = "cancel"  # in a channel's script: the task is cancelled at this point


def constants_text() -> str:
    with open(os.path.join(COLREGS_CONSTANTS_FOLDER, "general_maritime_constants.yaml"), encoding="utf-8") as file:
        return file.read()


def reference():
    """The run judged by one monitor over all its scenes: what a series in batches has to give."""
    return monitored_run(TARGET_START, STEPS)


def scenes() -> List[dict]:
    return [result.scene.to_dict() for result in reference()]


def task(include_frames: bool = False, time_step: int = 1) -> MonitorScenarioTask:
    return MonitorScenarioTask(
        sender="monitoring-subsystem",
        task_uuid="u1",
        request_id="r1",
        seed=4,
        scenario_id="case-1#run0",
        time_step=time_step,
        colregs_constraints_content=constants_text(),
        include_frames=include_frames,
    )


def batch(index: int, first: int, last: int, **changes: Any) -> TaskSignal:
    return TaskSignal(SCENES_SIGNAL, {"index": index, "first-timestamp": first, "scenes": scenes()[first:last], **changes})


def close(batches: Optional[int] = None) -> TaskSignal:
    return TaskSignal(CLOSE_SIGNAL, None if batches is None else {"batches": batches})


class ScriptedChannel(RecordingChannel):
    """A channel whose signals are scripted. Waiting for a signal that is not there moves the test's clock (waited) instead of the wall clock."""

    def __init__(self, script: List[Any]):
        super().__init__()
        self.script = list(script)
        self.waited = 0.0
        self.details: List[Any] = []

    def next_signal(self, timeout_s: float) -> Optional[TaskSignal]:
        if self.script:
            step = self.script.pop(0)
            if step == CANCEL:
                self.cancelled = True
                return None
            return step
        self.waited += timeout_s
        return None

    def progress(self, message: str, fraction: Optional[float] = None, detail: Any = None) -> None:
        super().progress(message, fraction, detail)
        self.details.append(detail)


def run(script: List[Any], **options: Any) -> ScriptedChannel:
    channel = ScriptedChannel(script)
    monitor_series(task(**options), channel, idle_limit_s=1.0, clock=lambda: channel.waited)
    return channel


def test_a_series_in_batches_gives_the_verdict_of_one_monitor_over_all_its_scenes():
    channel = run([batch(0, 0, 3), batch(1, 3, 5), batch(2, 5, STEPS), close(3)])
    expected = RuleOutcomes()
    for result in reference():
        expected.add(result)
    [(verdict, final)] = channel.of(MONITOR_RESULT_STREAM)
    assert final, "the verdict is the task's result"
    assert verdict == {"scenes": STEPS, "monitored-scenes": STEPS, "time-step": 1, "batches": 3, "summary": expected.summary()}
    judged = [payload for payload, final in channel.of(MONITORED_SCENE_STREAM)]
    assert [(message["index"], message["monitored-scenes"], message["monitored-frames"]) for message in judged] == [
        (0, 3, []),
        (1, 5, []),
        (2, STEPS, []),
    ], "no frames unless the request asks for them"


def test_the_frames_of_every_batch_are_published_on_request_under_the_scenarios_id():
    channel = run([batch(0, 0, 4), batch(1, 4, STEPS), close()], include_frames=True)
    frames = [frame for payload, _ in channel.of(MONITORED_SCENE_STREAM) for frame in payload["monitored-frames"]]
    assert frames == [serialize_monitored_frame(scenario_id="case-1#run0", monitored_scene=result, timestamp=result.timestamp, time_step=1) for result in reference()]
    assert [frame["timestamp"] for frame in frames] == list(range(STEPS)) and {frame["scenarioId"] for frame in frames} == {"case-1#run0"}


def test_a_batch_delivered_twice_is_judged_once():
    channel = run([batch(0, 0, 3), batch(0, 0, 3), batch(1, 3, STEPS), batch(0, 0, 3), close(2)])
    [(verdict, _)] = channel.of(MONITOR_RESULT_STREAM)
    assert (verdict["scenes"], verdict["batches"]) == (STEPS, 2)
    assert [payload["index"] for payload, _ in channel.of(MONITORED_SCENE_STREAM)] == [0, 1]


@pytest.mark.parametrize(
    "script, reason",
    [
        ([batch(0, 0, 3), batch(2, 5, STEPS)], "batch 2 arrived before batch 1"),
        ([batch(0, 0, 3), batch(1, 3, 5, **{"first-timestamp": 4})], "batch 1 starts at 4, but the series is at 3"),
        ([batch(0, 0, 3), close(2)], "the series was closed after 1 of its 2 batches"),
    ],
    ids=["a_gap", "a_wrong_time", "closed_early"],
)
def test_a_series_out_of_order_fails_with_the_reason(script, reason):
    with pytest.raises(SeriesError, match=reason):
        run(script)


def test_the_timestamps_follow_the_series_time_step():
    channel = run([batch(0, 0, 3), TaskSignal(SCENES_SIGNAL, {"index": 1, "first-timestamp": 6, "scenes": scenes()[3:5]}), close(2)], include_frames=True, time_step=2)
    frames = [frame for payload, _ in channel.of(MONITORED_SCENE_STREAM) for frame in payload["monitored-frames"]]
    assert [frame["timestamp"] for frame in frames] == [0, 2, 4, 6, 8]
    assert channel.of(MONITOR_RESULT_STREAM)[0][0]["time-step"] == 2


def test_a_series_nobody_closes_fails_after_the_idle_limit():
    """The requester is gone: the task ends instead of holding its place in the pool."""
    with pytest.raises(SeriesError, match="got no scenes for 1 s and was not closed"):
        run([batch(0, 0, 3)])


def test_a_cancelled_series_ends_without_a_verdict():
    channel = run([batch(0, 0, 3), CANCEL, batch(1, 3, STEPS), close(2)])
    assert channel.of(MONITOR_RESULT_STREAM) == [] and len(channel.of(MONITORED_SCENE_STREAM)) == 1


def test_stopping_is_advised_once_when_every_rule_is_decided(monkeypatch):
    monkeypatch.setattr(RuleOutcomes, "every_rule_decided", lambda self: self.monitored_scenes >= 5)
    channel = run([batch(0, 0, 3), batch(1, 3, 5), batch(2, 5, STEPS), close(3)])
    assert channel.progressed == [("every rule is decided", None)], "said once, with the batch that decided the last rule"
    assert channel.details == [{"stop-advised": True, "decided-at": 4}]
    assert len(channel.of(MONITOR_RESULT_STREAM)) == 1, "the series goes on until its requester closes it"


def test_a_series_without_constants_is_judged_by_the_general_maritime_defaults():
    explicit = SeriesMonitor("s", 1, constants_text())
    default = SeriesMonitor("s", 1)
    for monitor in (explicit, default):
        monitor.add([result.scene for result in reference()])
    assert default.summary() == explicit.summary() and (default.scenes, default.monitored_scenes, default.next_timestamp) == (STEPS, STEPS, STEPS)


def test_the_pools_worker_judges_the_series_of_its_task(monkeypatch):
    seen = []
    monkeypatch.setattr(monitoring_worker, "monitor_series", lambda task, channel: seen.append((task.request_id, channel)))
    monitoring_worker.run_monitoring_worker(task(), "channel")
    assert seen == [("r1", "channel")]


def test_a_batch_that_asks_for_its_frames_gets_them_and_one_that_declines_does_not():
    asking = TaskSignal(SCENES_SIGNAL, {"index": 0, "first-timestamp": 0, "scenes": scenes()[:3], "frames": True})
    channel = run([asking, batch(1, 3, STEPS), close(2)])
    first, second = [payload for payload, _ in channel.of(MONITORED_SCENE_STREAM)]
    assert [frame["timestamp"] for frame in first["monitored-frames"]] == [0, 1, 2] and second["monitored-frames"] == []
    declining = TaskSignal(SCENES_SIGNAL, {"index": 0, "first-timestamp": 0, "scenes": scenes()[:3], "frames": False})
    channel = run([declining, batch(1, 3, STEPS), close(2)], include_frames=True)
    first, second = [payload for payload, _ in channel.of(MONITORED_SCENE_STREAM)]
    assert first["monitored-frames"] == [] and len(second["monitored-frames"]) == STEPS - 3, "the request's choice holds for a batch that says nothing"


def test_every_batch_message_says_whether_every_rule_is_decided(monkeypatch):
    monkeypatch.setattr(RuleOutcomes, "every_rule_decided", lambda self: self.monitored_scenes >= 5)
    channel = run([batch(0, 0, 3), batch(1, 3, 5), batch(2, 5, STEPS), close(3)])
    assert [payload["every-rule-decided"] for payload, _ in channel.of(MONITORED_SCENE_STREAM)] == [False, True, True]


def test_the_monitoring_subsystem_is_named_to_a_requester_in_one_variable():
    from scenegems_tool.subsystems.monitoring.monitoring_types import live_series_request_id, monitoring_pool_environment, monitoring_pool_from_environment

    environment = monitoring_pool_environment("monitoring-subsystem-3", {"MQTT_BROKER": "broker.lab", "MQTT_PORT": "1883"}, (57.7, 11.9, 2000.0))
    assert set(environment) == {"SCENEGEMS_MONITORING_POOL"}
    assert monitoring_pool_from_environment(environment) == ("monitoring-subsystem-3", {"MQTT_BROKER": "broker.lab", "MQTT_PORT": "1883"}, (57.7, 11.9, 2000.0))
    assert monitoring_pool_from_environment({}) is None and monitoring_pool_from_environment({"SCENEGEMS_MONITORING_POOL": " "}) is None
    assert live_series_request_id("job-1-2") == "job-1-2-live"
