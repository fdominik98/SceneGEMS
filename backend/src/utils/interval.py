import random

import portion as P


class Interval(P.Interval):
    @staticmethod
    def closed(lower: float, upper: float) -> "Interval":
        return Interval(P.closed(lower, upper))

    def crop(self, value: float) -> float:
        """``value`` itself when it lies inside, otherwise the nearest bound of any part.

        The earlier ``min(closest lower bound, closest upper bound)`` picked the far side of
        a part for a value just above it: 2.2 against [-2, 2] gave -2, so a heading that was
        still 2.2 degrees short of its target stepped away from it and never settled.
        """
        if self.contains(value):
            return value

        if self.empty:
            raise ValueError("Interval is empty")

        bounds = [bound for part in self._intervals for bound in (part.lower, part.upper)]
        return min(bounds, key=lambda bound: abs(bound - value))

    def sample(self) -> float:
        # For simplicity, sample uniformly from each sub-interval in the union
        chosen = Interval(random.choice(self._intervals))
        low, high = chosen.lower, chosen.upper
        return random.uniform(low, high)
