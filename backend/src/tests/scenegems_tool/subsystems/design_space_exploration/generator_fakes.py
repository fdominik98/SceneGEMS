"""The stand-in for the Refinery model generator (data/stand_in_generator.py) as a command, a task for it, and a result as the generator leaves it."""

import sys
from pathlib import Path
from typing import Any, Optional, Tuple

from scenegems_tool.subsystems.design_space_exploration.design_space_exploration_types import ExploreDesignSpaceTask
from tests.scenegems_tool.subsystems.pool.pool_fakes import RecordingChannel

DATA = Path(__file__).parent / "data"
# In place of ("generate-models", "job", "-folder"): the same arguments, to a program that needs no Java
STAND_IN_COMMAND: Tuple[str, ...] = (sys.executable, str(DATA / "stand_in_generator.py"), "job", "-folder")
MODEL = (DATA / "generated_model.problem").read_text(encoding="utf-8")
# The model as the subsystem publishes it: the objects the generator named with the catalog's names
_SPECIFICATION, _GENERATED = MODEL.split("declare", 1)
NAMED_MODEL = _SPECIFICATION + "declare" + _GENERATED.replace("tS1", "ts1").replace("tS2", "ts2").replace("staticObstacle1", "obst1")


def exploration(problem: str = "class A.", seed: int = 7, **fields: Any) -> ExploreDesignSpaceTask:
    return ExploreDesignSpaceTask(sender="design-space-exploration-subsystem", task_uuid="u1", request_id="r1", seed=seed, problem=problem, **fields)


class ExplorationChannel(RecordingChannel):
    """A worker's channel that also keeps the progress details, and cancels the task after a number of progress messages when asked to."""

    def __init__(self, cancel_after: Optional[int] = None):
        super().__init__()
        self.details = []
        self.cancel_after = cancel_after

    def progress(self, message: str, fraction: Optional[float] = None, detail: Any = None) -> None:
        super().progress(message, fraction, detail)
        self.details.append(detail)
        if self.cancel_after is not None and len(self.progressed) >= self.cancel_after:
            self.cancelled = True


def generated(models, **summary):
    """A result of the generator with these model sources."""
    result = {"stop_reason": "exhausted", "complete": True, "models_found": len(models), "max_models": None, "random_seed": 1, "elapsed_s": 1.5, "message": None}
    result.update(summary)
    result["models"] = [{"index": index, "file": f"models/model_{index:05d}.problem", "source": source} for index, source in enumerate(models)]
    return result
