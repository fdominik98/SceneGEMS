"""The design space exploration subsystem on the broker: an explore-design-space request is one task, the whole exploration.

The pool, the task states and the channels are the ones every subsystem has (messaging/mqtt_pool_service.py).
An exploration cannot be split, so a request is one task; different requests run side by side, as many as the
pool has places. The request's seed is the generator's random seed.

A task publishes its progress on exec/feedback, a line a second while the generator works (message, progress,
and under detail the generator's phase and how many FECs it found), and one message on sensor/design_space:

    design-space   the explored FECs (subsystems/design_space_exploration/design_space.py explored_fecs), or null
    error          why the generator could not explore (a specification that does not parse, a bad scope), or null
    retryable      whether another attempt could end differently

A request names its fields in the broker's spelling (max-models, load-timeout); a field the generator does not
know is refused, as the generator itself would, so a misspelled limit is never ignored.
"""

from typing import Any, Dict, List, Mapping, Optional, Tuple

from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.messaging.mqtt_pool_service import PoolService
from scenegems_tool.subsystems.design_space_exploration.design_space_exploration_types import (
    DEFAULT_LOAD_TIMEOUT_S,
    DESIGN_SPACE_EXPLORATION_SERVICE_NAME,
    DESIGN_SPACE_STREAM,
    EXPLORE_DESIGN_SPACE_TASK,
    ExploreDesignSpaceTask,
)
from scenegems_tool.subsystems.design_space_exploration.design_space_exploration_worker import run_design_space_exploration_worker
from scenegems_tool.subsystems.pool.pool_task import PoolTask
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

REQUEST_FIELDS = frozenset({"problem", "scopes", "scope-overrides", "max-models", "timeout", "load-timeout", "state-coder-depth", "status-interval"})
_ENVELOPE_FIELDS = frozenset({"request-id", "seed"})  # what every request carries next to its own fields


def _entries(params: Mapping[str, Any], field: str) -> Tuple[str, ...]:
    value = params.get(field) or []
    if not isinstance(value, (list, tuple)) or not all(isinstance(entry, str) for entry in value):
        raise TypeError(f"{field} is a list of scope entries")
    return tuple(value)


def _positive(params: Mapping[str, Any], field: str, default: Optional[float]) -> Optional[float]:
    value = params.get(field)
    if value is None:
        return default
    number = float(value)
    if number <= 0:
        raise ValueError(f"{field} is positive, got {value}")
    return number


def _count(params: Mapping[str, Any], field: str) -> Optional[int]:
    value = params.get(field)
    if value is None:
        return None
    if int(value) < 1:
        raise ValueError(f"{field} is at least 1, got {value}")
    return int(value)


class MqttDesignSpaceExplorationService(PoolService):
    description = "Design Space Exploration Subsystem"
    task_name = EXPLORE_DESIGN_SPACE_TASK
    streams = (DESIGN_SPACE_STREAM,)
    worker = staticmethod(run_design_space_exploration_worker)

    def __init__(self, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence, max_workers: int = 1, name: str = DESIGN_SPACE_EXPLORATION_SERVICE_NAME, **options: Any):
        super().__init__(mqtt_connection, reference_geofence, max_workers, name, **options)

    def make_tasks(self, task_uuid: str, request_id: str, seed: int, params: Mapping[str, Any]) -> List[PoolTask]:
        unknown = sorted(set(params) - REQUEST_FIELDS - _ENVELOPE_FIELDS)
        if unknown:
            raise ValueError(f"the generator knows no {', '.join(unknown)}")
        problem = params["problem"]
        if not isinstance(problem, str) or not problem.strip():
            raise ValueError("the problem is empty")
        return [
            ExploreDesignSpaceTask(
                sender=self.name,
                task_uuid=task_uuid,
                request_id=request_id,
                seed=seed,
                problem=problem,
                scopes=_entries(params, "scopes"),
                scope_overrides=_entries(params, "scope-overrides"),
                max_models=_count(params, "max-models"),
                timeout_s=_positive(params, "timeout", None),
                load_timeout_s=_positive(params, "load-timeout", DEFAULT_LOAD_TIMEOUT_S) or DEFAULT_LOAD_TIMEOUT_S,
                state_coder_depth=_count(params, "state-coder-depth"),
                status_interval_s=_positive(params, "status-interval", 1.0) or 1.0,
            )
        ]

    def stream_message(self, task: PoolTask, stream: str, payload: Mapping[str, Any], final: bool) -> Dict[str, Any]:
        return {**payload, "final": bool(final)}
