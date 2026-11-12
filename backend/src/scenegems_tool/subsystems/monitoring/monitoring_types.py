import json
import os
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple

from scenegems_tool.subsystems.pool.pool_task import PoolTask

# Kept apart from the service module, which imports the monitor, so launchers and requesters
# can name the service, its task, its signals and its streams without loading it.
# The service's name on its own. A worker node's instance takes the name the cluster gave it
# (monitoring-subsystem-<number>) and the topic root of its broker (messaging/mqtt_client.py service_topic).
MONITORING_SERVICE_NAME = "monitoring-subsystem"
MONITOR_SCENARIO_TASK = "monitor-scenario"  # the start-task name of a request: judge one series of scenes

SCENES_SIGNAL = "scenes"  # the next scenes of the series: {"index", "first-timestamp", "scenes"}, and "frames" to get (or not) this batch's monitored frames
CLOSE_SIGNAL = "close"  # the series is over: {"batches"}, how many batches it had

MONITORED_SCENE_STREAM = "monitored-scene"  # sensor/monitored-scene: one message per judged batch: how far the series is, whether every rule is decided, its frames on request
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


# A run that is judged while it runs is a requester of its worker node's monitoring subsystem: the run's runner
# container is told which one, and how to reach its broker, in one variable.
MONITORING_POOL_VARIABLE = "SCENEGEMS_MONITORING_POOL"


def monitoring_pool_environment(service_name: str, broker_environment: Mapping[str, str], geofence: Tuple[float, float, float]) -> Dict[str, str]:
    """The variable that names a monitoring subsystem to a requester in another container.

    broker_environment: the broker connection as messaging/mqtt_client.py mqtt_container_environment writes it.
    geofence: latitude, longitude and radius of the reference area every broker client is given.
    """
    return {MONITORING_POOL_VARIABLE: json.dumps({"service": service_name, "broker": dict(broker_environment), "geofence": list(geofence)})}


def monitoring_pool_from_environment(environ: Optional[Mapping[str, str]] = None) -> Optional[Tuple[str, Dict[str, str], Tuple[float, float, float]]]:
    """(service name, broker environment, geofence) of the monitoring subsystem this process was given, None when it was given none."""
    text = (os.environ if environ is None else environ).get(MONITORING_POOL_VARIABLE, "").strip()
    if not text:
        return None
    document = json.loads(text)
    latitude, longitude, radius = document["geofence"]
    return str(document["service"]), {str(key): str(value) for key, value in document["broker"].items()}, (float(latitude), float(longitude), float(radius))


def live_series_request_id(run_request_id: str) -> str:
    """The request id of the series of a run that is judged while it runs: the run's own request and what it is."""
    return f"{run_request_id}-live"
