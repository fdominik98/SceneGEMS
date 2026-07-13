from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from math import degrees
from typing import Callable, Dict, List, Set

import numpy as np

from concrete_level.colregs_monitoring.maneuver_context import ManeuverContext, ManeuverContextSet
from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.relation import Relation
from utils.colregs_approximations import COLREGSConstraints
from utils.global_constants import EPSILON
from utils.interval import Interval
from utils.math_utils import distance, heading_diff


class ManeuverType(Enum):
    COURSE_CHANGE_TO_THE_RIGHT = auto()
    COURSE_CHANGE_TO_THE_LEFT = auto()
    PERSISTING_COURSE = auto()
    UNDETECTED = auto()

    @property
    def custom_name(self) -> str:
        custom_names = {
            ManeuverType.COURSE_CHANGE_TO_THE_RIGHT: "turning right",
            ManeuverType.COURSE_CHANGE_TO_THE_LEFT: "turning left",
            ManeuverType.PERSISTING_COURSE: "persisting",
            ManeuverType.UNDETECTED: "Undetected",
        }
        return custom_names[self]

    @staticmethod
    def all_detected_maneuver_types() -> Set["ManeuverType"]:
        return set(ManeuverType).difference({ManeuverType.UNDETECTED})


def get_suggested_range_of_heading_change_for_course_change_to_the_right(
    max_heading_step: float,
    colregs_constants: COLREGSConstraints,
) -> Interval:
    min_range = colregs_constants.UNDETECTABLE_HEADING_CHANGE + EPSILON
    if max_heading_step < min_range:
        raise ValueError(f"max_heading_step ({max_heading_step}) is less than min_range ({min_range})")
    return Interval.closed(-max_heading_step, -min_range)


def get_suggested_range_of_heading_change_for_course_change_to_the_left(max_heading_step: float, colregs_constants: COLREGSConstraints) -> Interval:
    min_range = colregs_constants.UNDETECTABLE_HEADING_CHANGE + EPSILON
    if max_heading_step < min_range:
        raise ValueError(f"max_heading_step ({max_heading_step}) is less than min_range ({min_range})")
    return Interval.closed(min_range, max_heading_step)


def get_suggested_range_of_heading_change_for_persisting_course(max_heading_step: float, colregs_constants: COLREGSConstraints) -> Interval:
    # range = min(max_heading_step, GlobalConfig.UNDETECTABLE_COURSE_CHANGE_ANGLE - GlobalConfig.EPSILON)
    return Interval.closed(-EPSILON, EPSILON)


def get_suggested_range_of_heading_change_for_undetected(max_heading_step: float, colregs_constants: COLREGSConstraints) -> Interval:
    return Interval.closed(-max_heading_step, max_heading_step)


MANEUVER_TYPE_HEADING_CHANGE_MAP: Dict[ManeuverType, Callable[[float, COLREGSConstraints], Interval]] = {
    ManeuverType.COURSE_CHANGE_TO_THE_RIGHT: get_suggested_range_of_heading_change_for_course_change_to_the_right,
    ManeuverType.COURSE_CHANGE_TO_THE_LEFT: get_suggested_range_of_heading_change_for_course_change_to_the_left,
    ManeuverType.PERSISTING_COURSE: get_suggested_range_of_heading_change_for_persisting_course,
    ManeuverType.UNDETECTED: get_suggested_range_of_heading_change_for_undetected,
}


@dataclass(frozen=True)
class SpeedChange:
    speed_diff_since_previous: float
    speed_diff_since_start: float
    speed_diff_time_window: List[float]
    colregs_constants: COLREGSConstraints

    @property
    def speed_change_detected(self) -> bool:
        return abs(self.speed_diff_since_previous) > self.colregs_constants.UNDETECTABLE_SPEED_CHANGE

    @property
    def speed_change_detected_since_start(self) -> bool:
        return abs(self.speed_diff_since_start) > self.colregs_constants.UNDETECTABLE_SPEED_CHANGE

    @property
    def speed_diff_since_readily_apparent_time(self) -> float:
        return sum(self.speed_diff_time_window)

    def reset(self) -> "SpeedChange":
        return SpeedChange(speed_diff_since_previous=0, speed_diff_since_start=0, speed_diff_time_window=[], colregs_constants=self.colregs_constants)

    def step(self, speed_diff_since_previous: float, slide_time_window: bool = True) -> "SpeedChange":
        if slide_time_window:
            speed_diff_time_window = self.speed_diff_time_window[1:] + [speed_diff_since_previous]
        else:
            speed_diff_time_window = self.speed_diff_time_window + [speed_diff_since_previous]
        return SpeedChange(
            speed_diff_since_previous=speed_diff_since_previous,
            speed_diff_since_start=self.speed_diff_since_start + speed_diff_since_previous,
            speed_diff_time_window=speed_diff_time_window,
            colregs_constants=self.colregs_constants,
        )

    @property
    def is_readily_apparent_since_readily_apparent_time(self) -> bool:
        return abs(self.speed_diff_since_readily_apparent_time) > self.colregs_constants.READILY_APPARENT_SPEED_CHANGE


@dataclass(frozen=True)
class HeadingChange:
    heading_diff_since_previous: float
    heading_diff_since_start: float
    heading_diff_time_window: List[float]
    colregs_constants: COLREGSConstraints
    
    @property
    def detected_heading_direction(self) -> str:
        if self.change_detected_to_left:
            return "left"
        elif self.change_detected_to_right:
            return "right"
        return "none"

    @property
    def change_detected_to_left(self) -> bool:
        return self.heading_diff_since_previous > self.colregs_constants.UNDETECTABLE_HEADING_CHANGE

    @property
    def change_detected_to_right(self) -> bool:
        return self.heading_diff_since_previous < -self.colregs_constants.UNDETECTABLE_HEADING_CHANGE

    @property
    def change_detected(self) -> bool:
        return abs(self.heading_diff_since_previous) < self.colregs_constants.UNDETECTABLE_HEADING_CHANGE

    @property
    def change_detected_since_start_to_left(self) -> bool:
        return self.heading_diff_since_start > self.colregs_constants.UNDETECTABLE_HEADING_CHANGE

    @property
    def change_detected_since_start_to_right(self) -> bool:
        return self.heading_diff_since_start < -self.colregs_constants.UNDETECTABLE_HEADING_CHANGE

    @property
    def change_detected_since_start(self) -> bool:
        return abs(self.heading_diff_since_start) < self.colregs_constants.UNDETECTABLE_HEADING_CHANGE

    @property
    def is_readily_apparent_since_start_to_left(self) -> bool:
        return self.heading_diff_since_start > self.colregs_constants.READILY_APPARENT_HEADING_CHANGE

    @property
    def is_readily_apparent_since_start_to_right(self) -> bool:
        return self.heading_diff_since_start < -self.colregs_constants.READILY_APPARENT_HEADING_CHANGE

    @property
    def is_readily_apparent_since_start(self) -> bool:
        return abs(self.heading_diff_since_start) > self.colregs_constants.READILY_APPARENT_HEADING_CHANGE

    @property
    def is_readily_apparent_since_readily_apparent_time(self) -> bool:
        return abs(self.heading_diff_since_readily_apparent_time) > self.colregs_constants.READILY_APPARENT_HEADING_CHANGE

    @property
    def full_turn_detected(self) -> bool:
        return abs(self.heading_diff_since_start) > np.pi

    @property
    def overturning_detected(self) -> bool:
        return abs(self.heading_diff_since_start) > np.radians(80.0)

    @property
    def heading_diff_since_start_deg(self) -> float:
        return degrees(self.heading_diff_since_start)

    @property
    def heading_diff_since_previous_deg(self) -> float:
        return degrees(self.heading_diff_since_previous)

    def reset(self) -> "HeadingChange":
        return HeadingChange(
            heading_diff_since_previous=self.heading_diff_since_previous,
            heading_diff_since_start=self.heading_diff_since_previous,
            heading_diff_time_window=[self.heading_diff_since_previous],
            colregs_constants=self.colregs_constants,
        )

    def step(self, heading_diff_since_previous: float, slide_time_window: bool = True) -> "HeadingChange":
        if slide_time_window:
            heading_diff_time_window = self.heading_diff_time_window[1:] + [heading_diff_since_previous]
        else:
            heading_diff_time_window = self.heading_diff_time_window + [heading_diff_since_previous]
        return HeadingChange(
            heading_diff_since_previous=heading_diff_since_previous,
            heading_diff_since_start=self.heading_diff_since_start + heading_diff_since_previous,
            heading_diff_time_window=heading_diff_time_window,
            colregs_constants=self.colregs_constants,
        )

    @property
    def heading_diff_since_readily_apparent_time(self) -> float:
        return sum(self.heading_diff_time_window)

    @property
    def heading_diff_since_readily_apparent_time_deg(self) -> float:
        return degrees(self.heading_diff_since_readily_apparent_time)


@dataclass(frozen=True)
class ManeuverState(ABC):
    maneuver_context: ManeuverContext
    # if the start timestamp is different for two maneuver states it means that they belong to different maneuvers
    maneuver_count: int
    start_timestamp: int
    current_timestamp: int
    heading_change: HeadingChange
    speed_change: SpeedChange
    previous_maneuver_type: ManeuverType
    distance_made: float
    total_distance_made: float
    colregs_constants: COLREGSConstraints
    
    @abstractmethod
    def do_step(self, maneuver_context: ManeuverContext, hc: HeadingChange, sc: SpeedChange, next_timestamp: int, distance_made: float) -> "ManeuverState":
        pass

    @property
    def readily_apparent_timestamp(self) -> int:
        return self.current_timestamp - self.colregs_constants.READILY_APPARENT_COURSE_CHANGE_TIME

    @property
    def readily_apparent_time_passed(self) -> bool:
        return self.readily_apparent_timestamp >= self.start_timestamp

    @property
    def vessel(self) -> ConcreteVessel:
        return self.maneuver_context.vessel

    def step(self, maneuver_context: ManeuverContext, current_scene: ConcreteScene, next_scene: ConcreteScene, time_step: int) -> "ManeuverState":
        current_state = current_scene[self.vessel]
        next_state = next_scene[self.vessel]
        heading_diff_since_previous = heading_diff(next_state.heading, current_state.heading)
        speed_diff_since_previous = next_state.speed - current_state.speed

        slide_time_window = self.readily_apparent_time_passed
        next_hc = self.heading_change.step(heading_diff_since_previous, slide_time_window)
        next_sc = self.speed_change.step(speed_diff_since_previous, slide_time_window)
        next_timestamp = self.current_timestamp + time_step
        distance_made = distance(current_state.p, next_state.p)
        return self.do_step(maneuver_context, next_hc, next_sc, next_timestamp, distance_made)

    @property
    def timespan(self) -> int:
        return self.current_timestamp - self.start_timestamp

    @property
    @abstractmethod
    def type(self) -> ManeuverType:
        pass

    def same_maneuver(self, other: "ManeuverState") -> bool:
        return self.maneuver_count == other.maneuver_count and self.maneuver_context.vessel == other.maneuver_context.vessel

    @property
    def is_persisting_course(self) -> bool:
        return self.type == ManeuverType.PERSISTING_COURSE

    @property
    def is_course_change(self) -> bool:
        return self.type in [ManeuverType.COURSE_CHANGE_TO_THE_LEFT, ManeuverType.COURSE_CHANGE_TO_THE_RIGHT]

    @property
    def is_course_change_to_the_right(self) -> bool:
        return self.type == ManeuverType.COURSE_CHANGE_TO_THE_RIGHT

    @property
    def is_course_change_to_the_left(self) -> bool:
        return self.type == ManeuverType.COURSE_CHANGE_TO_THE_LEFT

    @property
    def just_started(self) -> bool:
        return self.current_timestamp == self.start_timestamp

    def __str__(self) -> str:
        return f"{self.type.name} ({self.start_timestamp} -> {self.current_timestamp})"

    def __repr__(self) -> str:
        return str(self)


@dataclass(frozen=True)
class CourseChangeToTheRightManeuver(ManeuverState):
    @property
    def type(self) -> ManeuverType:
        return ManeuverType.COURSE_CHANGE_TO_THE_RIGHT

    def do_step(self, maneuver_context: ManeuverContext, hc: HeadingChange, sc: SpeedChange, next_timestamp: int, distance_made: float) -> "ManeuverState":
        if hc.change_detected_to_left:
            return CourseChangeToTheLeftManeuver(
                maneuver_context,
                maneuver_count=self.maneuver_count + 1,
                distance_made=distance_made,
                start_timestamp=self.current_timestamp,
                current_timestamp=next_timestamp,
                heading_change=hc.reset(),
                speed_change=sc.reset(),
                previous_maneuver_type=self.type,
                total_distance_made=self.total_distance_made + distance_made,
                colregs_constants=self.colregs_constants,
            )
        if hc.change_detected_to_right:
            return CourseChangeToTheRightManeuver(
                maneuver_context,
                maneuver_count=self.maneuver_count,
                distance_made=self.distance_made + distance_made,
                start_timestamp=self.start_timestamp,
                current_timestamp=next_timestamp,
                heading_change=hc,
                speed_change=sc,
                previous_maneuver_type=self.previous_maneuver_type,
                total_distance_made=self.total_distance_made + distance_made,
                colregs_constants=self.colregs_constants,
            )
        return PersistingCourseManeuver(
            maneuver_context,
            maneuver_count=self.maneuver_count + 1,
            distance_made=self.distance_made,
            start_timestamp=self.current_timestamp,
            current_timestamp=next_timestamp,
            heading_change=hc.reset(),
            speed_change=sc.reset(),
            previous_maneuver_type=self.type,
            total_distance_made=self.total_distance_made + distance_made,
            colregs_constants=self.colregs_constants,
        )


@dataclass(frozen=True)
class CourseChangeToTheLeftManeuver(ManeuverState):
    @property
    def type(self) -> ManeuverType:
        return ManeuverType.COURSE_CHANGE_TO_THE_LEFT

    def do_step(self, maneuver_context: ManeuverContext, hc: HeadingChange, sc: SpeedChange, next_timestamp: int, distance_made: float) -> "ManeuverState":
        if hc.change_detected_to_left:
            return CourseChangeToTheLeftManeuver(
                maneuver_context,
                maneuver_count=self.maneuver_count,
                distance_made=self.distance_made + distance_made,
                start_timestamp=self.start_timestamp,
                current_timestamp=next_timestamp,
                heading_change=hc,
                speed_change=sc,
                previous_maneuver_type=self.previous_maneuver_type,
                total_distance_made=self.total_distance_made + distance_made,
                colregs_constants=self.colregs_constants,
            )
        if hc.change_detected_to_right:
            return CourseChangeToTheRightManeuver(
                maneuver_context,
                maneuver_count=self.maneuver_count + 1,
                distance_made=distance_made,
                start_timestamp=self.current_timestamp,
                current_timestamp=next_timestamp,
                heading_change=hc.reset(),
                speed_change=sc.reset(),
                previous_maneuver_type=self.type,
                total_distance_made=self.total_distance_made + distance_made,
                colregs_constants=self.colregs_constants,
            )
        return PersistingCourseManeuver(
            maneuver_context,
            maneuver_count=self.maneuver_count + 1,
            distance_made=distance_made,
            start_timestamp=self.current_timestamp,
            current_timestamp=next_timestamp,
            heading_change=hc.reset(),
            speed_change=sc.reset(),
            previous_maneuver_type=self.type,
            total_distance_made=self.total_distance_made + distance_made,
            colregs_constants=self.colregs_constants,
        )


@dataclass(frozen=True)
class PersistingCourseManeuver(ManeuverState):
    def do_step(self, maneuver_context: ManeuverContext, hc: HeadingChange, sc: SpeedChange, next_timestamp: int, distance_made: float) -> "ManeuverState":
        if hc.change_detected_to_left:
            # New course change maneuvers detected
            return CourseChangeToTheLeftManeuver(
                maneuver_context,
                maneuver_count=self.maneuver_count + 1,
                distance_made=distance_made,
                start_timestamp=self.current_timestamp,
                current_timestamp=next_timestamp,
                heading_change=hc.reset(),
                speed_change=sc.reset(),
                previous_maneuver_type=self.type,
                total_distance_made=self.total_distance_made + distance_made,
                colregs_constants=self.colregs_constants,
            )
        elif hc.change_detected_to_right:
            return CourseChangeToTheRightManeuver(
                maneuver_context,
                maneuver_count=self.maneuver_count + 1,
                distance_made=distance_made,
                start_timestamp=self.current_timestamp,
                current_timestamp=next_timestamp,
                heading_change=hc.reset(),
                speed_change=sc.reset(),
                previous_maneuver_type=self.type,
                total_distance_made=self.total_distance_made + distance_made,
                colregs_constants=self.colregs_constants,
            )
        elif hc.is_readily_apparent_since_start_to_left:
            # Same maneuver but the type of the maneuver has changed
            return CourseChangeToTheLeftManeuver(
                maneuver_context,
                maneuver_count=self.maneuver_count,
                distance_made=self.distance_made + distance_made,
                start_timestamp=self.start_timestamp,
                current_timestamp=next_timestamp,
                heading_change=hc,
                speed_change=sc,
                previous_maneuver_type=self.previous_maneuver_type,
                total_distance_made=self.total_distance_made + distance_made,
                colregs_constants=self.colregs_constants,
            )
        elif hc.is_readily_apparent_since_start_to_right:
            return CourseChangeToTheRightManeuver(
                maneuver_context,
                maneuver_count=self.maneuver_count,
                distance_made=self.distance_made + distance_made,
                start_timestamp=self.start_timestamp,
                current_timestamp=next_timestamp,
                heading_change=hc,
                speed_change=sc,
                previous_maneuver_type=self.previous_maneuver_type,
                total_distance_made=self.total_distance_made + distance_made,
                colregs_constants=self.colregs_constants,
            )
        # No change detected
        return PersistingCourseManeuver(
            maneuver_context,
            maneuver_count=self.maneuver_count,
            distance_made=self.distance_made + distance_made,
            start_timestamp=self.start_timestamp,
            current_timestamp=next_timestamp,
            heading_change=hc,
            speed_change=sc,
            previous_maneuver_type=self.previous_maneuver_type,
            total_distance_made=self.total_distance_made + distance_made,
            colregs_constants=self.colregs_constants,
        )

    @property
    def type(self) -> ManeuverType:
        return ManeuverType.PERSISTING_COURSE


@dataclass(frozen=True)
class UndetectedManeuver(ManeuverState):
    def do_step(self, maneuver_context: ManeuverContext, hc: HeadingChange, sc: SpeedChange, next_timestamp: int, distance_made: float) -> "ManeuverState":
        if next_timestamp - self.start_timestamp < self.colregs_constants.UNDETECTABLE_HEADING_PERSISTENCE_TIME:
            return UndetectedManeuver(
                maneuver_context,
                maneuver_count=self.maneuver_count,
                distance_made=self.distance_made + distance_made,
                start_timestamp=self.start_timestamp,
                current_timestamp=next_timestamp,
                heading_change=hc,
                speed_change=sc,
                previous_maneuver_type=self.previous_maneuver_type,
                total_distance_made=self.total_distance_made + distance_made,
                colregs_constants=self.colregs_constants,
            )
        if hc.change_detected_since_start_to_left:
            # New course change maneuvers detected
            return CourseChangeToTheLeftManeuver(
                maneuver_context,
                maneuver_count=self.maneuver_count,
                distance_made=self.distance_made + distance_made,
                start_timestamp=self.start_timestamp,
                current_timestamp=next_timestamp,
                heading_change=hc,
                speed_change=sc,
                previous_maneuver_type=self.previous_maneuver_type,
                total_distance_made=self.total_distance_made + distance_made,
                colregs_constants=self.colregs_constants,
            )
        elif hc.change_detected_since_start_to_right:
            return CourseChangeToTheRightManeuver(
                maneuver_context,
                maneuver_count=self.maneuver_count,
                distance_made=self.distance_made + distance_made,
                start_timestamp=self.start_timestamp,
                current_timestamp=next_timestamp,
                heading_change=hc,
                speed_change=sc,
                previous_maneuver_type=self.previous_maneuver_type,
                total_distance_made=self.total_distance_made + distance_made,   
                colregs_constants=self.colregs_constants,
            )
        # No change detected
        return PersistingCourseManeuver(
            maneuver_context,
            maneuver_count=self.maneuver_count,
            distance_made=self.distance_made + distance_made,
            start_timestamp=self.start_timestamp,
            current_timestamp=next_timestamp,
            heading_change=hc,
            speed_change=sc,
            previous_maneuver_type=self.previous_maneuver_type,
            total_distance_made=self.total_distance_made + distance_made,
            colregs_constants=self.colregs_constants,
        )

    @property
    def type(self) -> ManeuverType:
        return ManeuverType.UNDETECTED


class ManeuverStateSet(Dict[Relation, ManeuverState]):
    @property
    def maneuver_context_set(self) -> ManeuverContextSet:
        return ManeuverContextSet({rel: state.maneuver_context for rel, state in self.items()})

    def merge(self, other: "ManeuverStateSet") -> "ManeuverStateSet":
        return ManeuverStateSet({**self, **other})
