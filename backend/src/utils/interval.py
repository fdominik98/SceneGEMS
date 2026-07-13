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

    def sample_from_all(self) -> List[float]:
        return [random.uniform(interval.lower, interval.upper) for interval in self._intervals]
