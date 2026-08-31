from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TrajectoryGenerationParams:
    """Tuning values forwarded from the frontend advanced-parameters panel.

    ``None`` means "use the MonitorDrivenRRTSearch / TrajectoryGenerator default".
    """

    time_step: Optional[int] = None
    timeout: Optional[float] = None
    max_iterations: Optional[int] = None
    goal_sample_rate: Optional[int] = None
    best_leaf_sample_rate: Optional[int] = None
    max_leafs: Optional[int] = None
    direction_threshold: Optional[float] = None
    best_random_nodes_k: Optional[int] = None
    preview_interval: Optional[int] = None

    @staticmethod
    def from_wire(params: dict) -> "TrajectoryGenerationParams":
        def _int(key: str) -> Optional[int]:
            value = params.get(key)
            return int(value) if value is not None else None

        def _float(key: str) -> Optional[float]:
            value = params.get(key)
            return float(value) if value is not None else None

        return TrajectoryGenerationParams(
            time_step=_int("timeStep"),
            timeout=_float("timeout"),
            max_iterations=_int("maxIterations"),
            goal_sample_rate=_int("goalSampleRate"),
            best_leaf_sample_rate=_int("bestLeafSampleRate"),
            max_leafs=_int("maxLeafs"),
            direction_threshold=_float("directionThreshold"),
            best_random_nodes_k=_int("bestRandomNodesK"),
            preview_interval=_int("previewInterval"),
        )

    def to_wire(self) -> dict:
        return {
            "time-step": self.time_step,
            "timeout": self.timeout,
            "max-iterations": self.max_iterations,
            "goal-sample-rate": self.goal_sample_rate,
            "best-leaf-sample-rate": self.best_leaf_sample_rate,
            "max-leafs": self.max_leafs,
            "direction-threshold": self.direction_threshold,
            "best-random-nodes-k": self.best_random_nodes_k,
            "preview-interval": self.preview_interval,
        }

    @staticmethod
    def from_task_params(params: dict) -> "TrajectoryGenerationParams":
        return TrajectoryGenerationParams(
            time_step=params.get("time-step"),
            timeout=params.get("timeout"),
            max_iterations=params.get("max-iterations"),
            goal_sample_rate=params.get("goal-sample-rate"),
            best_leaf_sample_rate=params.get("best-leaf-sample-rate"),
            max_leafs=params.get("max-leafs"),
            direction_threshold=params.get("direction-threshold"),
            best_random_nodes_k=params.get("best-random-nodes-k"),
            preview_interval=params.get("preview-interval"),
        )


@dataclass(frozen=True)
class MqttTrajectoryGenerationTask:
    sender: str
    task_uuid: str
    request_id: str
    scenario_content: str
    colregs_constraints_content: str
    params: TrajectoryGenerationParams
