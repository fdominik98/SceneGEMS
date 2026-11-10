"""Clock contract: one authoritative simulated clock per simulation instance.

The simulation layer owns the clock. For every step it publishes a request to step to the
target time, every participant (ASV system, control layer) computes its command for the
step and acknowledges it, and only then does the simulation advance. Nothing in this
contract reads the wall clock, so pace is limited by compute alone. Simulated time is
derived from the integer step index, never accumulated, so it is exact for a fixed dt.
"""

import hashlib
from dataclasses import dataclass
from typing import Iterable, Protocol, Tuple

from scenegems_tool.vessel_stack.contracts.ports import HeadingSpeedCommand, VesselStateObservation


@dataclass(frozen=True)
class StepRequest:
    index: int
    time: float  # simulated time of the observation the participants act on
    target_time: float  # simulated time the simulation advances to once every participant acknowledged


@dataclass(frozen=True)
class StepAck:
    participant_id: str
    index: int


class LockstepViolation(RuntimeError):
    pass


class LockstepParticipant(Protocol):
    """An adapter that is stepped by the simulation clock instead of its own timer."""

    participant_id: str

    def start(self, seed: int) -> None:
        """Called once before step 0 with the participant's seed derived from the run seed."""

    def on_step(self, request: StepRequest, observation: VesselStateObservation) -> HeadingSpeedCommand:
        """Compute the command for the interval from request.time to request.target_time."""


class LockstepClock:
    def __init__(self, dt: float, participant_ids: Iterable[str]):
        if dt <= 0:
            raise ValueError(f"dt must be positive, got {dt}")
        self.dt = dt
        self.participant_ids: Tuple[str, ...] = tuple(sorted(set(participant_ids)))
        self.index = 0

    @property
    def time(self) -> float:
        return self.index * self.dt

    def request(self) -> StepRequest:
        return StepRequest(index=self.index, time=self.index * self.dt, target_time=(self.index + 1) * self.dt)

    def advance(self, acks: Iterable[StepAck]) -> float:
        """Advance one step once every participant acknowledged the current request; return the new time."""
        acked = set()
        for ack in acks:
            if ack.index != self.index:
                raise LockstepViolation(f"{ack.participant_id} acknowledged step {ack.index} while the clock is at step {self.index}")
            if ack.participant_id not in self.participant_ids:
                raise LockstepViolation(f"{ack.participant_id} is not a participant of this clock")
            acked.add(ack.participant_id)
        missing = [participant_id for participant_id in self.participant_ids if participant_id not in acked]
        if missing:
            raise LockstepViolation(f"step {self.index} is missing acknowledgements from {', '.join(missing)}")
        self.index += 1
        return self.time


def derive_seed(run_seed: int, component: str) -> int:
    """Per-component seed from the run seed. Stable across processes, unlike hash()."""
    digest = hashlib.sha256(f"{run_seed}:{component}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")
