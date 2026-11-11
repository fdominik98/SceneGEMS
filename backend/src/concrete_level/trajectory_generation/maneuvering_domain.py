from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from concrete_level.colregs_monitoring.colregs_rules.conditions.give_way_early_action_condition import early_action_start_deadline
from concrete_level.colregs_monitoring.situation_context import COLREGSType, SituationContext
from concrete_level.models.concrete_actors import ConcreteActor
from utils.colregs_approximations import COLREGSConstraints
from utils.global_constants import EPSILON
from utils.math_utils import Direction
from utils.safety_domains import DomainCollection


@dataclass(frozen=True)
class CorridorShape:
    """How a give-way ship's corridor departs from the one its frozen domains give.

    ``outbound_angle`` is the heading change of the outbound leg A-B (and of the inbound
    leg C-D) in radians; the corridor never gets a shallower slant than it has, so 0.0
    keeps it. ``width_factor`` multiplies the clearance offset of the leg B-C. The default
    shape is the corridor as `ManeuveringDomain.for_give_way_ship` sizes it.

    The frozen domains say where the ship's own course runs into the conflict. They do not
    say how far the ship has to go to resolve it: a sideways shift barely changes the miss
    distance of a crossing, whose relative motion runs across the track, and it cannot
    know that the other vessel is leaving its course as well. The seed therefore tries
    other shapes when the monitor fails the default one (`search_seed_corridors`).
    """

    outbound_angle: float = 0.0
    width_factor: float = 1.0

    def lost_progress(self, slant_angle: float) -> float:
        """Progress along the track the two slanted legs cost, per unit of corridor width.

        Orders the shapes from the mildest manoeuvre to the largest. ``slant_angle`` is the
        angle a corridor has anyway (the readily apparent heading change), which is what an
        ``outbound_angle`` below it means.
        """
        angle = max(self.outbound_angle, slant_angle)
        return self.width_factor * (2.0 * float(np.tan(angle / 2.0)) + CorridorShape.WIDTH_WEIGHT)

    # Two shapes that lose the same progress are told apart by their width.
    WIDTH_WEIGHT = 0.1


class ManeuveringDomain:
    """Give-way trapezoid grown from frozen potential collision domains.

    Vertices live in the give-way vessel's original-course frame: along the heading at
    the first give-way latch, across positive toward the committed avoidance side. A is
    a short stretch of original-track travel after that latch, inside the window Rule 16
    leaves for the first turn (the monitor's ``early_action_start_deadline``). A-B is a readily apparent outbound slant, steeper if that ray would
    cut a frozen potential collision domain. B-C is original heading at the clearance
    offset, past the furthest domain. C-D is a straight inbound segment at the same
    slant back onto the original track. After D the seed stays on that track. Empty
    potential collision domain yields None.
    The monitor frame also carries this shape as `maneuveringDomainsByActorId`.
    """

    def __init__(
        self,
        origin: np.ndarray,
        forward: np.ndarray,
        across: np.ndarray,
        t0: float,
        along_b: float,
        along_c: float,
        along_d: float,
        inner_across: float,
        outer_across: float,
    ):
        self.origin = np.asarray(origin, dtype=float)
        self.forward = np.asarray(forward, dtype=float)
        self.across = np.asarray(across, dtype=float)
        self.t0 = t0
        self.along_b = along_b
        self.along_c = along_c
        self.along_d = along_d
        self.inner_across = inner_across
        self.outer_across = outer_across
        self.vertex_a = self._world(t0, inner_across)
        self.vertex_b = self._world(along_b, outer_across)
        self.vertex_c = self._world(along_c, outer_across)
        self.vertex_d = self._world(along_d, inner_across)

    def reshaped(self, shape: Optional[CorridorShape]) -> "ManeuveringDomain":
        """This corridor with the outbound angle and the width of ``shape``.

        A stays where it is, so the first turn keeps its place inside the window Rule 16
        leaves for it. B and D follow from the slant and the width. C stays where the
        frozen domains end, unless the outbound leg now reaches further along than that.
        """
        if shape is None or shape == CorridorShape():
            return self
        outer_across = self.outer_across * shape.width_factor
        slant = max(float(np.tan(shape.outbound_angle)), self.outer_across / max(self.along_b - self.t0, EPSILON))
        run = outer_across / max(slant, EPSILON)
        along_b = self.t0 + run
        along_c = max(self.along_c, along_b)
        return ManeuveringDomain(self.origin, self.forward, self.across, self.t0, along_b, along_c, along_c + run, self.inner_across, outer_across)

    @property
    def far_along(self) -> float:
        """Original-track landing after the inbound segment."""
        return self.along_d

    @property
    def hold_heading_change(self) -> float:
        """Signed heading change from the original course that follows A-B."""
        return _heading_change(self.vertex_b - self.vertex_a, self.forward)

    @property
    def inbound_heading_change(self) -> float:
        """Signed heading change from the original course that follows C-D."""
        return _heading_change(self.vertex_d - self.vertex_c, self.forward)

    @property
    def vertices(self) -> List[np.ndarray]:
        return [self.vertex_a, self.vertex_b, self.vertex_c, self.vertex_d]

    @property
    def edges(self) -> List[Tuple[np.ndarray, np.ndarray]]:
        verts = self.vertices
        return [(verts[i], verts[(i + 1) % 4]) for i in range(4)]

    def local(self, point: np.ndarray) -> Tuple[float, float]:
        delta = np.asarray(point, dtype=float) - self.origin
        return float(np.dot(delta, self.forward)), float(np.dot(delta, self.across))

    def contains(self, point: np.ndarray) -> bool:
        along, across = self.local(point)
        upper = self._across_upper(along)
        if upper is None:
            return False
        return self.inner_across - EPSILON <= across <= upper + EPSILON

    def distance_to_avoidance_polyline(self, point: np.ndarray) -> float:
        """Distance to the seed edge A-B-C-D."""
        point = np.asarray(point, dtype=float)
        return min(
            _segment_distance(point, self.vertex_a, self.vertex_b),
            _segment_distance(point, self.vertex_b, self.vertex_c),
            _segment_distance(point, self.vertex_c, self.vertex_d),
        )

    def magnet_cost(self, point: np.ndarray, scale: float) -> float:
        """Soft pull onto A-B-C-D. Inside is expensive; far outside saturates."""
        scale = max(scale, EPSILON)
        distance = self.distance_to_avoidance_polyline(point)
        if self.contains(point):
            return ManeuveringDomain.INSIDE_WEIGHT * distance / scale
        excess = min(distance, ManeuveringDomain.FAR_CAP_FRACTION * scale)
        return ManeuveringDomain.OUTSIDE_WEIGHT * excess / scale

    def _world(self, along: float, across: float) -> np.ndarray:
        return self.origin + along * self.forward + across * self.across

    def _across_upper(self, along: float) -> Optional[float]:
        if along < self.t0 - EPSILON or along > self.along_d + EPSILON:
            return None
        if along <= self.along_b:
            return _lerp(self.inner_across, self.outer_across, along - self.t0, self.along_b - self.t0)
        if along <= self.along_c:
            return self.outer_across
        return _lerp(self.outer_across, self.inner_across, along - self.along_c, self.along_d - self.along_c)

    def near_outer(self, across: float) -> bool:
        return across >= self.outer_across - self._corner_tol()

    def near_track(self, across: float) -> bool:
        return across <= self.inner_across + self._corner_tol()

    def reached_b(self, along: float, across: float) -> bool:
        """True once the ship has both passed A's along and reached the outer offset."""
        return along >= self.along_b - EPSILON and self.near_outer(across)

    def reached_d(self, along: float, across: float) -> bool:
        """True once the inbound has put the ship back on the original track."""
        return along >= self.along_c - EPSILON and self.near_track(across)

    def _corner_tol(self) -> float:
        return max(abs(self.outer_across) * 0.1, 1.0)

    INSIDE_WEIGHT: float = 6.0
    OUTSIDE_WEIGHT: float = 1.5
    FAR_CAP_FRACTION: float = 2.0

    @staticmethod
    def from_projected_corners(
        origin: np.ndarray,
        forward: np.ndarray,
        across: np.ndarray,
        alongs: List[float],
        acrosses: List[float],
        safety_radius: float,
        slant_angle: float,
        delay_along: float = 0.0,
    ) -> Optional["ManeuveringDomain"]:
        geometry = _hold_course_geometry(alongs, acrosses, safety_radius, slant_angle, delay_along)
        if geometry is None:
            return None
        t0, along_b, along_c, along_d, inner_across, outer_across = geometry
        return ManeuveringDomain(origin, forward, across, t0, along_b, along_c, along_d, inner_across, outer_across)

    @staticmethod
    def for_give_way_ship(actor: ConcreteActor, situation_contexts: Sequence[SituationContext], shape: Optional[CorridorShape] = None) -> Optional["ManeuveringDomain"]:
        give_way = _give_way_contexts(actor, situation_contexts)
        if not give_way:
            return None
        first = min(give_way, key=lambda context: context.start_timestamp)
        # Same tie-break as SituationContextSet.get_actor_avoidance_direction: starboard
        # wins when two live encounters disagree. Using the earliest latch's own side
        # put the kite to port on overtaking-to-port + crossing-from-port, while the
        # rules still demanded a starboard turn and the path went wavy.
        direction = _committed_avoidance_direction(actor, give_way)
        start = first.start_scene[actor]
        across = start.v_norm_perp_right if direction is Direction.RIGHT else start.v_norm_perp_left
        origin = start.p
        forward = np.array([np.cos(start.heading), np.sin(start.heading)])
        alongs: List[float] = []
        acrosses: List[float] = []
        for context in give_way:
            projected = _project_pcd_corners(origin, forward, across, context.start_potential_collision_domains[actor])
            alongs.extend(projected[0])
            acrosses.extend(projected[1])
        domain = ManeuveringDomain.from_projected_corners(
            origin,
            forward,
            across,
            alongs,
            acrosses,
            actor.safety_radius,
            first.colregs_constants.READILY_APPARENT_HEADING_CHANGE,
            start.speed * outbound_start_delay(first.colregs_constants),
        )
        return None if domain is None else domain.reshaped(shape)

    def to_monitor_payload(self) -> Dict[str, Any]:
        """Vertices and hold polyline in world metres for the web console overlay."""
        return {
            "vertices": [_xy(point) for point in self.vertices],
            "holdPolyline": [_xy(self.vertex_a), _xy(self.vertex_b), _xy(self.vertex_c), _xy(self.vertex_d)],
            "holdHeadingChangeDeg": float(np.degrees(self.hold_heading_change)),
        }


def outbound_start_delay(colregs_constants: COLREGSConstraints) -> float:
    """Seconds a give-way ship keeps its course after the latch before it turns at A.

    It is the monitor's deadline for the first turn to be under way, so the corridor and
    Rule 16 agree. This was READILY_APPARENT_COURSE_CHANGE_TIME, which is how long a turn
    takes to be seen, not how long the ship may wait: with the shipped 70 s it put A
    behind the 60 s of IMMEDIATE_HEADING_CHANGE_TIME and every seed failed Rule 16 at its
    first step after that.
    """
    return float(early_action_start_deadline(colregs_constants))


def _give_way_contexts(actor: ConcreteActor, situation_contexts: Sequence[SituationContext]) -> List[SituationContext]:
    give_way: List[SituationContext] = []
    for context in situation_contexts:
        if context.situation_type is COLREGSType.OTHER:
            continue
        if not context.is_give_way_actor(actor):
            continue
        if context.avoidance_direction(actor) not in (Direction.LEFT, Direction.RIGHT):
            continue
        give_way.append(context)
    return give_way


def _committed_avoidance_direction(actor: ConcreteActor, situation_contexts: Sequence[SituationContext]) -> Direction:
    directions = {context.avoidance_direction(actor) for context in situation_contexts}
    if Direction.RIGHT in directions:
        return Direction.RIGHT
    if Direction.LEFT in directions:
        return Direction.LEFT
    return Direction.FORWARD


def _heading_change(delta: np.ndarray, forward: np.ndarray) -> float:
    hold = float(np.arctan2(delta[1], delta[0]))
    original = float(np.arctan2(forward[1], forward[0]))
    return (hold - original + np.pi) % (2.0 * np.pi) - np.pi


def _xy(point: np.ndarray) -> List[float]:
    return [float(point[0]), float(point[1])]


def _hold_course_geometry(
    alongs: List[float],
    acrosses: List[float],
    safety_radius: float,
    slant_angle: float,
    delay_along: float = 0.0,
) -> Optional[Tuple[float, float, float, float, float, float]]:
    if not alongs:
        return None
    gap = max(safety_radius, EPSILON)
    tan_ra = float(np.tan(max(slant_angle, EPSILON)))
    t0, tan_used = _outbound_start(alongs, acrosses, gap, tan_ra, delay_along)
    tan_used = max(tan_used, EPSILON)
    inner_across = 0.0
    outer_across = max(max(acrosses), 0.0) + gap
    along_b = t0 + outer_across / tan_used
    along_c = max(max(alongs) + gap, along_b)
    along_d = along_c + outer_across / tan_used
    return t0, along_b, along_c, along_d, inner_across, outer_across


def _outbound_start(alongs: List[float], acrosses: List[float], gap: float, tan_ra: float, delay_along: float) -> Tuple[float, float]:
    """Place A a short delay after latch, not at the last-moment clearance of the PCD.

    Sliding A to the latest readily apparent ray put the trapezoid on top of the collision
    domain, far from the ship. The seed instead waits only ``delay_along`` (seconds of
    original-track travel after detection). If even that is too late to clear at the
    readily apparent angle, A is pulled back and the slant steepens.
    """
    latest = _latest_ra_turn_along(alongs, acrosses, gap, tan_ra)
    t0 = max(0.0, delay_along)
    if latest is None:
        return t0, tan_ra
    if latest < 0.0:
        t0 = 0.0
    else:
        t0 = min(t0, latest)
    return t0, max(tan_ra, _clearance_tangent_from(alongs, acrosses, gap, t0))


def _latest_ra_turn_along(alongs: List[float], acrosses: List[float], gap: float, tan_ra: float) -> Optional[float]:
    limits: List[float] = []
    for along, across in zip(alongs, acrosses):
        need = across + gap
        if need <= EPSILON:
            continue
        limits.append(along - need / tan_ra)
    if not limits:
        return None
    return min(limits)


def _clearance_tangent_from(alongs: List[float], acrosses: List[float], gap: float, t0: float) -> float:
    tan_needed = 0.0
    for along, across in zip(alongs, acrosses):
        remaining = along - t0
        if remaining > EPSILON:
            tan_needed = max(tan_needed, (across + gap) / remaining)
    return tan_needed


def _project_pcd_corners(
    origin: np.ndarray,
    forward: np.ndarray,
    across: np.ndarray,
    pcd: DomainCollection,
) -> Tuple[List[float], List[float]]:
    alongs: List[float] = []
    acrosses: List[float] = []
    if pcd.empty:
        return alongs, acrosses
    corners = np.asarray(pcd.bounding_rectangle.points_for_plotting)
    if corners.size == 0:
        return alongs, acrosses
    origin = np.asarray(origin, dtype=float)
    for corner in corners[:-1]:
        delta = corner - origin
        alongs.append(float(np.dot(delta, forward)))
        acrosses.append(float(np.dot(delta, across)))
    return alongs, acrosses


def _lerp(start: float, end: float, offset: float, span: float) -> float:
    frac = offset / max(span, EPSILON)
    frac = min(1.0, max(0.0, frac))
    return start + frac * (end - start)


def _segment_distance(point: np.ndarray, start: np.ndarray, end: np.ndarray) -> float:
    span = end - start
    length2 = float(np.dot(span, span))
    if length2 <= EPSILON * EPSILON:
        return float(np.linalg.norm(point - start))
    t = float(np.dot(point - start, span) / length2)
    t = min(1.0, max(0.0, t))
    return float(np.linalg.norm(point - (start + t * span)))
