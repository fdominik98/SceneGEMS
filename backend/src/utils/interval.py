import random
from typing import List

import portion as P


class Interval(P.Interval):
    @staticmethod
    def closed(lower: float, upper: float) -> "Interval":
        return Interval(P.closed(lower, upper))

    def crop(self, value: float) -> float:
        # find the closest interval to that value if the current one does not contain it
        if self.contains(value):
            return value

        if self.empty:
            raise ValueError("Interval is empty")

        # find the closest interval to that value
        closest_lower_bound = min(self._intervals, key=lambda interval: abs(interval.lower - value)).lower
        closest_upper_bound = min(self._intervals, key=lambda interval: abs(interval.upper - value)).upper
        return min(closest_lower_bound, closest_upper_bound)

    def sample(self) -> float:
        # For simplicity, sample uniformly from each sub-interval in the union
        chosen = Interval(random.choice(self._intervals))
        low, high = chosen.lower, chosen.upper
        return random.uniform(low, high)

    def sample_from_all(self, k: int = 1) -> List[float]:
        """Draw ``k`` samples from every sub-interval.

        With k=1 a turn interval yields a single random magnitude, so while a rule
        narrows the suggestion to one manoeuvre type the search has a branching factor
        of one and cannot explore how hard to turn. The endpoints are included when
        k >= 2 so the extremes of each interval are always reachable.
        """
        samples: List[float] = []
        for interval in self._intervals:
            low, high = interval.lower, interval.upper
            if k <= 1 or high - low <= 0:
                samples.append(random.uniform(low, high))
                continue
            samples.append(low)
            samples.append(high)
            # The midpoint matters as much as the ends. For the symmetric
            # persisting-course band it is exactly zero, and without it "hold this
            # heading" is not in the action set at all: every step had to take some
            # non-zero value from the band, so a vessel with nothing to do still
            # wandered, and that wander eventually registered as a course change.
            if k >= 3:
                samples.append((low + high) / 2.0)
            samples.extend(random.uniform(low, high) for _ in range(k - 3))
        return samples
