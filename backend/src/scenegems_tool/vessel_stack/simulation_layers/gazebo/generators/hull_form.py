"""Parametric hull form of the generated vessel model: a ship-shaped hull from length, breadth, draft and block coefficient.

The hull is described by two curves along its length, both 1 amidships and 0 at the ends:

- the waterline: the breadth at the waterline over the full breadth. Its mean is the waterplane
  coefficient (waterplane area over L * B);
- the sectional area curve: the immersed area of a cross section over the midship section's.
  Its mean is the prismatic coefficient (block coefficient over midship coefficient).

Each curve is a parallel middle body with parabolic ends, or, for a fine hull, ends of a lower
power without a parallel body: the one-parameter family whose mean is the wanted coefficient.
The bow is finer than the stern (it takes the larger share of what the curve lacks to a
rectangle). The midship and waterplane coefficients follow the block coefficient by the usual
design formulas unless they are given.

From the curves come:

- the stations of the buoyant volume (HullForm.stations): boxes along the hull with the
  waterline breadth and the mean immersed depth of their part of the hull, so that the model
  displaces the hull's volume, with its waterplane area and its center of buoyancy;
- the wetted surface for the resistance;
- the surface mesh the model shows (HullForm.mesh), with cross sections of the power that gives
  each section its area: full amidships, V-shaped toward the ends.

Frame: x forward, y to port, z up, origin amidships at the waterline.
"""

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

FORE_SHARE_WATERLINE = 0.6  # share of the waterline's missing area that lies in the fore half
FORE_SHARE_SECTIONS = 0.55  # the same for the sectional area curve
MIN_HALF_FULLNESS = 0.2  # a half of a curve is not made finer than this
MAX_SECTION_COEFFICIENT = 0.98  # a cross section is at most this full (a small bilge radius)
MIN_SECTION_COEFFICIENT = 0.3
END_BREADTH_SHARE = 0.01  # the mesh keeps this share of the breadth at the stem and the stern, so no face collapses
DECK_FLARE = 0.15  # the deck edge takes this share of the way from the waterline breadth to the full breadth
SAMPLES_PER_STATION = 16
Vertex = Tuple[float, float, float]
Face = Tuple[int, int, int]


def midship_coefficient_of(block_coefficient: float) -> float:
    """Kerlen's formula: the midship section fills its B * T rectangle more the fuller the hull."""
    return min(0.99, 1.006 - 0.0056 * block_coefficient**-3.56)


def waterplane_coefficient_of(block_coefficient: float) -> float:
    """Schneekluth's formula for a hull with U-shaped sections."""
    return (1.0 + 2.0 * block_coefficient) / 3.0


def _end_curve(t: float, fullness: float) -> float:
    """Ordinate at t (0 amidships, 1 at the end) of the half curve whose mean is `fullness`."""
    if fullness >= 1.0:
        return 1.0
    if fullness >= 2.0 / 3.0:
        parallel, power = 3.0 * fullness - 2.0, 2.0
    else:
        parallel, power = 0.0, fullness / (1.0 - fullness)
    if t <= parallel:
        return 1.0
    return max(0.0, 1.0 - ((t - parallel) / (1.0 - parallel)) ** power)


def _half_fullness(coefficient: float, fore_share: float) -> Tuple[float, float]:
    """(fore, aft) means of a curve of the given mean whose missing area lies by fore_share in the fore half."""
    fore = max(1.0 - 2.0 * fore_share * (1.0 - coefficient), MIN_HALF_FULLNESS)
    aft = 2.0 * coefficient - fore
    if aft > 1.0:
        fore, aft = 2.0 * coefficient - 1.0, 1.0
    return fore, aft


@dataclass(frozen=True)
class HullStation:
    """One box of the buoyant volume."""

    x: float  # m, its center along the hull (forward positive)
    length: float  # m
    breadth: float  # m, the mean waterline breadth of this part of the hull
    depth: float  # m, its mean immersed depth: section area over waterline breadth

    @property
    def volume(self) -> float:
        return self.length * self.breadth * self.depth

    @property
    def waterplane_area(self) -> float:
        return self.length * self.breadth


@dataclass(frozen=True)
class HullMesh:
    vertices: Tuple[Vertex, ...]
    faces: Tuple[Face, ...]  # vertex indices, counterclockwise seen from outside

    def moved(self, x: float) -> "HullMesh":
        """The same surface moved along the hull by x m."""
        return HullMesh(tuple((vx + x, vy, vz) for vx, vy, vz in self.vertices), self.faces)

    def to_stl(self, name: str = "hull") -> str:
        """ASCII STL: one facet per face with its outward normal."""
        lines = [f"solid {name}"]
        for a, b, c in self.faces:
            pa, pb, pc = self.vertices[a], self.vertices[b], self.vertices[c]
            ux, uy, uz = pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]
            vx, vy, vz = pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2]
            nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            norm = math.sqrt(nx * nx + ny * ny + nz * nz)
            if norm == 0.0:
                continue  # a collapsed face has no area to show
            lines.append(f"  facet normal {nx / norm:.6g} {ny / norm:.6g} {nz / norm:.6g}")
            lines.append("    outer loop")
            for x, y, z in (pa, pb, pc):
                lines.append(f"      vertex {x:.6g} {y:.6g} {z:.6g}")
            lines.append("    endloop")
            lines.append("  endfacet")
        lines.append(f"endsolid {name}")
        return "\n".join(lines) + "\n"

    def enclosed_volume(self) -> float:
        """Volume inside the surface (divergence theorem); positive when the faces look outward."""
        total = 0.0
        for a, b, c in self.faces:
            (ax, ay, az), (bx, by, bz), (cx, cy, cz) = self.vertices[a], self.vertices[b], self.vertices[c]
            total += ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)
        return total / 6.0


@dataclass(frozen=True)
class HullForm:
    length: float
    breadth: float
    draft: float
    block_coefficient: float
    midship_coefficient: float
    waterplane_coefficient: float

    @classmethod
    def from_dimensions(
        cls, length: float, breadth: float, draft: float, block_coefficient: float, midship_coefficient: Optional[float] = None, waterplane_coefficient: Optional[float] = None
    ) -> "HullForm":
        if min(length, breadth, draft) <= 0:
            raise ValueError(f"a hull needs a positive length, breadth and draft, got {length}, {breadth} and {draft}")
        if not 0.0 < block_coefficient <= 1.0:
            raise ValueError(f"the block coefficient must be in (0, 1], got {block_coefficient}")
        midship = midship_coefficient_of(block_coefficient) if midship_coefficient is None else midship_coefficient
        midship = min(max(midship, block_coefficient), 1.0)  # the hull is nowhere fuller than amidships
        waterplane = waterplane_coefficient_of(block_coefficient) if waterplane_coefficient is None else waterplane_coefficient
        # The waterline is at least as full as the sectional area curve, so no section overfills its rectangle.
        waterplane = min(max(waterplane, block_coefficient / midship), 1.0)
        return cls(length, breadth, draft, block_coefficient, midship, waterplane)

    @property
    def prismatic_coefficient(self) -> float:
        return self.block_coefficient / self.midship_coefficient

    @property
    def displaced_volume(self) -> float:
        return self.block_coefficient * self.length * self.breadth * self.draft

    @property
    def waterplane_area(self) -> float:
        return self.waterplane_coefficient * self.length * self.breadth

    @property
    def wetted_surface(self) -> float:
        """Denny and Mumford's estimate: 1.7 L T + volume / T."""
        return 1.7 * self.length * self.draft + self.displaced_volume / self.draft

    def waterline_share(self, xi: float) -> float:
        """Waterline breadth over the full breadth at xi (-1 at the stern, 0 amidships, 1 at the stem)."""
        fore, aft = _half_fullness(self.waterplane_coefficient, FORE_SHARE_WATERLINE)
        return _end_curve(abs(xi), fore if xi >= 0 else aft)

    def section_share(self, xi: float) -> float:
        """Immersed section area over the midship section's at xi."""
        fore, aft = _half_fullness(self.prismatic_coefficient, FORE_SHARE_SECTIONS)
        return _end_curve(abs(xi), fore if xi >= 0 else aft)

    def stations(self, count: int) -> Tuple[HullStation, ...]:
        """The hull cut into `count` boxes along its length, stern first.

        The breadths are scaled so that the boxes have exactly the hull's waterplane area, and the
        depths so that they displace exactly its volume: what the sampling of the curves misses.
        """
        if count < 1:
            raise ValueError(f"a hull has at least one station, got {count}")
        step = self.length / count
        breadths, areas = [], []
        for index in range(count):
            samples = [-1.0 + 2.0 * (index + (sample + 0.5) / SAMPLES_PER_STATION) / count for sample in range(SAMPLES_PER_STATION)]
            breadths.append(self.breadth * sum(self.waterline_share(xi) for xi in samples) / SAMPLES_PER_STATION)
            areas.append(self.midship_coefficient * self.breadth * self.draft * sum(self.section_share(xi) for xi in samples) / SAMPLES_PER_STATION)
        breadth_scale = self.waterplane_area / (step * sum(breadths))
        area_scale = self.displaced_volume / (step * sum(areas))
        return tuple(
            HullStation(x=-self.length / 2.0 + (index + 0.5) * step, length=step, breadth=breadth * breadth_scale, depth=area * area_scale / (breadth * breadth_scale))
            for index, (breadth, area) in enumerate(zip(breadths, areas))
        )

    def half_breadth(self, xi: float, z: float, height: float) -> float:
        """Half breadth of the hull surface at xi and height z above the waterline (keel at -draft, deck at height - draft)."""
        waterline = max(self.waterline_share(xi), END_BREADTH_SHARE) * self.breadth / 2.0
        if z >= 0.0:
            freeboard = height - self.draft
            rise = z / freeboard if freeboard > 0 else 0.0
            return waterline + DECK_FLARE * rise * (self.breadth / 2.0 - waterline)
        share = max(self.waterline_share(xi), END_BREADTH_SHARE)
        coefficient = self.midship_coefficient * max(self.section_share(xi), END_BREADTH_SHARE) / share
        coefficient = min(max(coefficient, MIN_SECTION_COEFFICIENT), MAX_SECTION_COEFFICIENT)
        power = coefficient / (1.0 - coefficient)
        return waterline * (1.0 - min(-z / self.draft, 1.0) ** power)

    def mesh(self, height: float, sections: int = 41, points: int = 9) -> HullMesh:
        """Closed surface of the hull up to its deck: `sections` cross sections of 2 * points - 1 vertices each.

        A cross section runs from the port deck edge down to the keel and up to the starboard deck
        edge; `points` vertices lie on each side, the keel included, with one of them at the waterline.
        """
        if height <= self.draft:
            raise ValueError(f"the hull height {height} must exceed the draft {self.draft}")
        if sections < 2 or points < 3:
            raise ValueError("a hull mesh needs at least 2 sections of 3 points per side")
        freeboard = height - self.draft
        above = max(1, points // 3)  # vertices above the waterline, the deck edge included
        below = points - 2 - above  # vertices between the waterline and the keel, both excluded
        levels = [freeboard * (above - index) / above for index in range(above)] + [0.0]
        levels += [-self.draft * (1.0 - math.cos(math.pi / 2.0 * (index + 1) / (below + 1))) for index in range(below)]
        levels.append(-self.draft)

        ring = 2 * points - 1
        vertices: List[Vertex] = []
        for section in range(sections):
            xi = -1.0 + 2.0 * section / (sections - 1)
            x = xi * self.length / 2.0
            side = [(self.half_breadth(xi, z, height), z) for z in levels]
            for y, z in side[:-1]:
                vertices.append((x, y, z))  # port side, deck edge first
            vertices.append((x, 0.0, -self.draft))  # keel
            for y, z in reversed(side[:-1]):
                vertices.append((x, -y, z))  # starboard side, deck edge last

        faces: List[Face] = []
        for section in range(sections - 1):
            aft, fore = section * ring, (section + 1) * ring
            for index in range(ring - 1):  # shell: port deck edge, keel, starboard deck edge
                faces.append((aft + index, fore + index, fore + index + 1))
                faces.append((aft + index, fore + index + 1, aft + index + 1))
            # deck, from the starboard edge back to the port edge
            faces.append((aft + ring - 1, fore + ring - 1, fore))
            faces.append((aft + ring - 1, fore, aft))
        for index in range(1, ring - 1):
            faces.append((0, index, index + 1))  # stern, looking aft
            last = (sections - 1) * ring
            faces.append((last, last + index + 1, last + index))  # stem, looking forward
        return HullMesh(tuple(vertices), tuple(faces))


def station_count(minimum: int, cells: int) -> int:
    """Stations for a hull whose buoyancy needs at least `cells` cells along it."""
    return max(minimum, cells)


def stations_volume(stations: Sequence[HullStation]) -> float:
    return sum(station.volume for station in stations)


def stations_waterplane_area(stations: Sequence[HullStation]) -> float:
    return sum(station.waterplane_area for station in stations)
