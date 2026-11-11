from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from scenegems_tool.subsystems.pool.pool_task import PoolTask

# Kept apart from the service module, so launchers and requesters can name the service, its task and
# its stream without loading it. Standard library only: the worker node daemon imports it.
# The service's name on its own. A worker node's instance takes the name the cluster gave it
# (design-space-exploration-subsystem-<number>) and the topic root of its broker (messaging/mqtt_client.py service_topic).
DESIGN_SPACE_EXPLORATION_SERVICE_NAME = "design-space-exploration-subsystem"
EXPLORE_DESIGN_SPACE_TASK = "explore-design-space"  # the start-task name of a request: every FEC of a specification within a scope
DESIGN_SPACE_STREAM = "design_space"  # sensor/design_space: the explored FECs, or why the generator could not explore

# The generator's own limits end an exploration with a result; only this long after them is it ended without one
STOP_MARGIN_S = 60.0
DEFAULT_LOAD_TIMEOUT_S = 120.0


@dataclass(frozen=True)
class ExploreDesignSpaceTask(PoolTask):
    """One exploration: the whole generation of the FECs of a specification. Its seed (PoolTask.seed) is the generator's random seed, which fixes the order the FECs are found in."""

    problem: str  # Refinery source: the specification, and the scope when it is not given under scopes
    scopes: Tuple[str, ...] = ()  # scope entries such as TS=2 or TS=1..3
    scope_overrides: Tuple[str, ...] = ()  # entries that replace the problem's scope of the same class
    max_models: Optional[int] = None  # the cap; None generates every model
    timeout_s: Optional[float] = None  # the generation's time limit; None for none
    load_timeout_s: float = DEFAULT_LOAD_TIMEOUT_S  # ends a parser that loops on a syntax error
    state_coder_depth: Optional[int] = None  # neighborhood depth for telling models apart; Refinery's default when None
    status_interval_s: float = 1.0

    def generator_payload(self) -> Dict[str, Any]:
        """The payload the generator reads (scenegems/README.md of the Refinery repository); it rejects every field it does not know."""
        payload: Dict[str, Any] = {
            "problem": self.problem,
            "scopes": list(self.scopes),
            "scope_overrides": list(self.scope_overrides),
            "random_seed": self.seed,
            "load_timeout_s": self.load_timeout_s,
            "status_interval_s": self.status_interval_s,
        }
        for field, value in (("max_models", self.max_models), ("timeout_s", self.timeout_s), ("state_coder_depth", self.state_coder_depth)):
            if value is not None:
                payload[field] = value
        return payload

    @property
    def run_limit_s(self) -> Optional[float]:
        """How long the generator may run before it is ended without a result; None for an exploration without a time limit."""
        return None if self.timeout_s is None else self.load_timeout_s + self.timeout_s + STOP_MARGIN_S
