from dataclasses import dataclass
from typing import Optional

from scenegems_tool.subsystems.pool.pool_task import PoolTask

# Kept apart from the service module, which imports the monitor, so launchers and requesters
# can name the service, its task, its signals and its streams without loading it.
# The service's name on its own. A worker node's instance takes the name the cluster gave it
# (monitoring-subsystem-<number>) and the topic root of its broker (messaging/mqtt_client.py service_topic).
MONITORING_SERVICE_NAME = "monitoring-subsystem"
MONITOR_SCENARIO_TASK = "monitor-scenario"  # the start-task name of a request: judge one series of scenes

SCENES_SIGNAL = "scenes"  # the next scenes of the series: {"index", "first-timestamp", "scenes"}
CLOSE_SIGNAL = "close"  # the series is over: {"batches"}, how many batches it had

MONITORED_SCENE_STREAM = "monitored-scene"  # sensor/monitored-scene: one message per judged batch, with its frames on request
MONITOR_RESULT_STREAM = "monitor_result"  # sensor/monitor_result: the verdict of the closed series

SCENES_PER_BATCH = 100  # how many scenes a requester puts in one scenes signal
SERIES_IDLE_LIMIT_S = 300.0  # a running series that gets no signal for this long fails, so a requester that is gone holds no place in the pool


@dataclass(frozen=True)
class MonitorScenarioTask(PoolTask):
    """Judging one series of scenes of one scenario, in time order. The monitor draws nothing at random; the seed is carried for the record."""

    scenario_id: str  # the scenarioId of the frames, and what orders the series of one scenario
    time_step: int  # seconds between two scenes of the series
    colregs_constraints_content: Optional[str] = None  # COLREGS constants YAML; the general maritime defaults when None
    include_frames: bool = False  # publish every monitored frame, not only how far the series is

    @property
    def order_key(self) -> Optional[str]:
        """Two series of one scenario never run at once: the later waits for the earlier."""
        return self.scenario_id
