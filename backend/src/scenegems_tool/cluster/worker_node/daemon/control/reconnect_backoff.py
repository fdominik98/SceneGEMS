"""Waiting between connection attempts: exponential, capped, with jitter, reset after a successful handshake.

The jitter spreads the reconnects of many worker nodes after a control node restart, so they do not
all arrive in the same second.
"""

import random
from typing import Callable


class ReconnectBackoff:
    def __init__(self, initial_s: float = 1.0, maximum_s: float = 30.0, factor: float = 2.0, jitter: float = 0.2, random_unit: Callable[[], float] = random.random):
        if initial_s <= 0 or maximum_s < initial_s or factor < 1 or not 0 <= jitter < 1:
            raise ValueError("Backoff needs 0 < initial <= maximum, factor >= 1 and 0 <= jitter < 1")
        self.initial_s = initial_s
        self.maximum_s = maximum_s
        self.factor = factor
        self.jitter = jitter
        self._random_unit = random_unit
        self._attempt = 0

    def next_delay_s(self) -> float:
        """The wait before the next attempt; each call counts one failed attempt."""
        base = min(self.maximum_s, self.initial_s * self.factor ** min(self._attempt, 64))
        self._attempt += 1
        return base * (1.0 - self.jitter + 2.0 * self.jitter * self._random_unit())

    def reset(self) -> None:
        self._attempt = 0
