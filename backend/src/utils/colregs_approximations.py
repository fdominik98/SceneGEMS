"""
Abbreviations: ACA, automatic collision avoidance;
CA, collision avoidance;
COLREG, International Regulations for Preventing Collisions at Sea 1972;
CPA, closest point of approach;
CR, risk of collision;
CS, close-quarters situation;
DCPA, distance to the closest point of approach;
FTCS, first time-in-point of close-quarters situation;
FTID, first time-in-point of immediate danger;
ID, immediate danger;
MMG, mathematical modeling group;
OS, own ship;
PCR, potential risk of collision;
RPM, Revolutions Per Minute;
SD, ship domain;
TCPA, time to the closest point of approach;
TCS, time to close-quarters situation;
TID, time to immediate danger;
TS, target ship
"""

import os
from dataclasses import dataclass

import yaml

from utils.file_system_utils import COLREGS_CONSTANTS_FOLDER
from utils.global_constants import VISIBILITY_DIST_2, VISIBILITY_DIST_3, VISIBILITY_DIST_5, VISIBILITY_DIST_6


@dataclass(frozen=True)
class COLREGSConstraints:
    READILY_APPARENT_COURSE_CHANGE_TIME: int
    READILY_APPARENT_HEADING_CHANGE: float
    UNDETECTABLE_HEADING_CHANGE: float
    HEADING_PERSISTENCE_TIME: int
    IMMEDIATE_HEADING_CHANGE_TIME: int
    UNDETECTABLE_HEADING_PERSISTENCE_TIME: int
    READILY_APPARENT_SPEED_CHANGE: float
    UNDETECTABLE_SPEED_CHANGE: float
    SAFE_TEMPORAL_DISTANCE: int

    @property
    def undetectable_heading_rate(self) -> float:
        """Smallest heading rate (rad/s) an observer is taken to notice.

        UNDETECTABLE_HEADING_CHANGE is an angle, and comparing it against a single
        sample's heading difference makes detection depend on the sampling rate: the
        implied rate floor is the angle divided by the time step, which differed by 15x
        between the planner at 15 s and the console at 1 s, so the same physical turn
        was classified differently at each. Reading it as an angle accumulated over
        UNDETECTABLE_HEADING_PERSISTENCE_TIME makes it a rate and removes that
        dependence, without changing any configured value.
        """
        if self.UNDETECTABLE_HEADING_PERSISTENCE_TIME <= 0:
            return self.UNDETECTABLE_HEADING_CHANGE
        return self.UNDETECTABLE_HEADING_CHANGE / self.UNDETECTABLE_HEADING_PERSISTENCE_TIME

    def undetectable_heading_change(self, time_step: float) -> float:
        """The undetectable heading band for a step of ``time_step`` seconds."""
        if time_step <= 0:
            return self.UNDETECTABLE_HEADING_CHANGE
        return self.undetectable_heading_rate * time_step

    @property
    def readily_apparent_heading_rate(self) -> float:
        """Turn rate (rad/s) a course change must sustain to become readily apparent."""
        if self.READILY_APPARENT_COURSE_CHANGE_TIME <= 0:
            return 0.0
        return self.READILY_APPARENT_HEADING_CHANGE / self.READILY_APPARENT_COURSE_CHANGE_TIME

    def readily_apparent_heading_change(self, time_step: float) -> float:
        """Heading change per step needed to keep a course change readily apparent."""
        return self.readily_apparent_heading_rate * max(time_step, 0.0)

    @property
    def undetectable_speed_rate(self) -> float:
        if self.UNDETECTABLE_HEADING_PERSISTENCE_TIME <= 0:
            return self.UNDETECTABLE_SPEED_CHANGE
        return self.UNDETECTABLE_SPEED_CHANGE / self.UNDETECTABLE_HEADING_PERSISTENCE_TIME

    def undetectable_speed_change(self, time_step: float) -> float:
        if time_step <= 0:
            return self.UNDETECTABLE_SPEED_CHANGE
        return self.undetectable_speed_rate * time_step

    @staticmethod
    def from_yaml(file_path: str) -> "COLREGSConstraints":
        with open(file_path, "r") as f:
            colregs_constants = yaml.safe_load(f) or {}
        return COLREGSConstraints(**colregs_constants)

    @staticmethod
    def default_general_maritime() -> "COLREGSConstraints":
        return COLREGSConstraints.from_yaml(os.path.join(COLREGS_CONSTANTS_FOLDER, "general_maritime_constants.yaml"))

    @staticmethod
    def default_wara_ps() -> "COLREGSConstraints":
        return COLREGSConstraints.from_yaml(os.path.join(COLREGS_CONSTANTS_FOLDER, "wara_ps_constants.yaml"))

    @staticmethod
    def from_file_content(content: str) -> "COLREGSConstraints":
        return COLREGSConstraints(**yaml.safe_load(content) or {})


def vessel_radius(length: float) -> float:
    return length * 4


def o2VisibilityByo1(o1_sees_o2_stern: bool, o2_length: float) -> float:
    if o1_sees_o2_stern:
        if o2_length < 5:
            return o2_length / 50 * VISIBILITY_DIST_2  # MADE UP FOR WARA-PS
        elif o2_length < 50:
            return VISIBILITY_DIST_2
        else:
            return VISIBILITY_DIST_3
    else:
        if o2_length < 5:
            return o2_length / 50 * VISIBILITY_DIST_5  # MADE UP FOR WARA-PS
        elif o2_length < 12:
            return VISIBILITY_DIST_2
        elif o2_length < 20:
            return VISIBILITY_DIST_3
        elif o2_length < 50:
            return VISIBILITY_DIST_5
        else:
            return VISIBILITY_DIST_6


def possible_vis_distances_by_length(length1, length2):
    return [
        min(o2VisibilityByo1(True, length1), o2VisibilityByo1(True, length2)),
        min(o2VisibilityByo1(True, length1), o2VisibilityByo1(False, length2)),
        min(o2VisibilityByo1(False, length1), o2VisibilityByo1(True, length2)),
        min(o2VisibilityByo1(False, length1), o2VisibilityByo1(False, length2)),
    ]


def possible_vis_distances_by_bearing(o2_sees_o1_stern, o1_sees_o2_stern):
    if o1_sees_o2_stern or o2_sees_o1_stern:
        return [
            VISIBILITY_DIST_2,
            VISIBILITY_DIST_3,
            VISIBILITY_DIST_2,
            VISIBILITY_DIST_3,
        ]
    else:
        return [
            VISIBILITY_DIST_2,
            VISIBILITY_DIST_3,
            VISIBILITY_DIST_5,
            VISIBILITY_DIST_6,
        ]


def vis_distance(o2_sees_o1_stern, length1, o1_sees_o2_stern, length2):
    return min(
        o2VisibilityByo1(o2_sees_o1_stern, length1),
        o2VisibilityByo1(o1_sees_o2_stern, length2),
    )


def drift_threshold(length1, length2):
    return max(length1, length2) / 2.0
