from dataclasses import dataclass
from enum import Enum
from typing import Optional

# Deliberately one worker in the workbench: planning trajectories is a single long run
# and the subsystem is scoped to one request at a time (see project spec). A node sizes
# its pool by its slots. Kept apart from the service module, which imports the search.
MAX_TRAJECTORY_GENERATION_WORKERS = 1
TRAJECTORY_GENERATION_SERVICE_NAME = "trajectory_generation_service"
TRAJECTORY_GENERATION_SERVICE_TOPIC = f"waraps/service/virtual/real/{TRAJECTORY_GENERATION_SERVICE_NAME}"


class TrajectoryGeneratorId(str, Enum):
    MONITOR_DRIVEN_RRT = "monitor_driven_rrt"  # the monitor-guided planner (MonitorGuidedPlanner); the id predates the name and is stored, so it stays
    STRAIGHT = "straight"  # every vessel straight on from the initial scene up to the timespan


@dataclass(frozen=True)
class TrajectoryGenerationParams:
    """Tuning values forwarded from the frontend advanced-parameters panel.

    ``None`` means "use the MonitorGuidedPlanner / TrajectoryGenerator default".
    """

    time_step: Optional[int] = None
    timeout: Optional[float] = None
    max_iterations: Optional[int] = None
    direction_threshold: Optional[float] = None
    best_random_nodes_k: Optional[int] = None
    preview_interval: Optional[int] = None
    # Whether previews and results carry the monitor output the planner recorded for
    # each scene. Off keeps the payload small on long runs with many encounters.
    include_monitor_results: Optional[bool] = None
    generator: Optional[TrajectoryGeneratorId] = None  # monitor_driven_rrt when None
    timespan: Optional[float] = None  # seconds, straight only; one hour when None

    def __post_init__(self) -> None:
        if self.timespan is not None and not self.timespan > 0:
            raise ValueError(f"timespan must be positive, got {self.timespan}")

    @property
    def generator_id(self) -> TrajectoryGeneratorId:
        return self.generator or TrajectoryGeneratorId.MONITOR_DRIVEN_RRT

    @property
    def monitor_results_enabled(self) -> bool:
        """Default is on; only an explicit ``False`` from the client turns it off."""
        return self.include_monitor_results is not False

    @staticmethod
    def from_wire(params: dict) -> "TrajectoryGenerationParams":
        def _int(key: str) -> Optional[int]:
            value = params.get(key)
            return int(value) if value is not None else None

        def _float(key: str) -> Optional[float]:
            value = params.get(key)
            return float(value) if value is not None else None

        def _bool(key: str) -> Optional[bool]:
            value = params.get(key)
            return bool(value) if value is not None else None

        def _generator(key: str) -> Optional[TrajectoryGeneratorId]:
            value = params.get(key)
            return TrajectoryGeneratorId(value) if value is not None else None

        return TrajectoryGenerationParams(
            time_step=_int("timeStep"),
            timeout=_float("timeout"),
            max_iterations=_int("maxIterations"),
            direction_threshold=_float("directionThreshold"),
            best_random_nodes_k=_int("bestRandomNodesK"),
            preview_interval=_int("previewInterval"),
            include_monitor_results=_bool("includeMonitorResults"),
            generator=_generator("generator"),
            timespan=_float("timespan"),
        )

    def to_wire(self) -> dict:
        return {
            "time-step": self.time_step,
            "timeout": self.timeout,
            "max-iterations": self.max_iterations,
            "direction-threshold": self.direction_threshold,
            "best-random-nodes-k": self.best_random_nodes_k,
            "preview-interval": self.preview_interval,
            "include-monitor-results": self.include_monitor_results,
            "generator": self.generator.value if self.generator is not None else None,
            "timespan": self.timespan,
        }

    @staticmethod
    def from_task_params(params: dict) -> "TrajectoryGenerationParams":
        return TrajectoryGenerationParams(
            time_step=params.get("time-step"),
            timeout=params.get("timeout"),
            max_iterations=params.get("max-iterations"),
            direction_threshold=params.get("direction-threshold"),
            best_random_nodes_k=params.get("best-random-nodes-k"),
            preview_interval=params.get("preview-interval"),
            include_monitor_results=params.get("include-monitor-results"),
            generator=TrajectoryGeneratorId(params["generator"]) if params.get("generator") is not None else None,
            timespan=params.get("timespan"),
        )


@dataclass(frozen=True)
class MqttTrajectoryGenerationTask:
    sender: str
    task_uuid: str
    request_id: str
    scenario_content: str
    colregs_constraints_content: str
    params: TrajectoryGenerationParams
    seed: Optional[int] = None  # seeds random and numpy at task start; the fixed default seed when None
