from abc import ABC, abstractmethod
from typing import Tuple

# Length/beam ratio (LBR) = WL/B
# (WL = waterline length; B = maximum beam at the waterline)

# LENGTH-TO-BEAM RATIO (LBR) AND SHIP CATEGORIES
#
# Ratio       Description                                    Typical Ship Types
# ------------------------------------------------------------------------------------------
# 2-4         Small to midsize planing powerboats            Yachts (6-15m, 15-50 knots)
#             Provides stability and spacious deck area      Small fishing boats (9-15m, 10-25 knots)
#             relative to length, suitable for high-speed
#             recreational use.
# ------------------------------------------------------------------------------------------
# 3-4         Small to midsize sailboats, motor yachts       Yachts (15-30m, 15-50 knots)
#             Balances stability and speed, suitable         Larger fishing boats (15-30m, 10-25 knots)
#             for both sailing and powerboating.
# ------------------------------------------------------------------------------------------
# 4-6         Large, efficient long-range cruisers           Ferries (30-50m, 15-30 knots)
#             Designed for fuel efficiency and stability,    Small cargo ships (90-150m, 12-20 knots)
#             ideal for ocean passages.
# ------------------------------------------------------------------------------------------
# 6-10        Large freighters, cruising trimarans,          Ferries (50-150m, 15-30 knots)
#             cruising catamarans, and large                 Larger cargo ships (150-180m, 12-20 knots)
#             sailing monohulls                              Icebreakers (60-180m, 10-20 knots)
#             Optimized for long-distance travel, balancing
#             stability and carrying capacity.
# ------------------------------------------------------------------------------------------
# 10-16       Fast-cruising catamarans, trimarans,           Naval ships (variable length, 20-35+ knots)
#             and racing multihulls                          Specialized racing boats
#             High LBR for speed and agility, reducing
#             drag for competitive sailing.
# ------------------------------------------------------------------------------------------
# Over 16     Racing multihulls                              Specialized racing multihulls
#             Extreme ratios for ultimate speed,             (e.g., America's Cup racers)
#             lightweight, minimal beam to length for
#             high performance in racing.
# ------------------------------------------------------------------------------------------

# LENGTH AND SPEED CATEGORIES
# ------------------------------------------------------------------------------------------
# Small Ships      6-30 meters         10-50 knots         Yachts, fishing boats
# Medium Ships     30-180 meters       12-30 knots         Ferries, small cargo ships
# Large Ships      180-460+ meters     12-25 knots         Container ships, cruise ships, oil tankers
# Specialized      Variable length     10-35+ knots        Naval ships, icebreakers, racing multihulls
# ------------------------------------------------------------------------------------------


class Scenario(ABC):
    @property
    @abstractmethod
    def obstacle_number(self) -> int:
        pass

    @property
    @abstractmethod
    def vessel_number(self) -> int:
        pass

    @property
    def actor_number(self) -> int:
        return self.vessel_number + self.obstacle_number

    @property
    def actor_number_by_type(self) -> Tuple[int, int]:
        return (self.vessel_number, self.obstacle_number)

    @property
    def name(self) -> str:
        return f"{str(self.vessel_number)}vessel_{str(self.obstacle_number)}obstacle"
