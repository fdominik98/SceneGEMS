"""HullForm: the coefficients, the stations of the buoyant volume and the surface mesh of the parametric hull."""

import math
from collections import Counter
from typing import List, Tuple

import pytest

from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.hull_form import (
    DECK_FLARE,
    END_BREADTH_SHARE,
    HullForm,
    HullMesh,
    HullStation,
    midship_coefficient_of,
    station_count,
    stations_volume,
    stations_waterplane_area,
    waterplane_coefficient_of,
)

LENGTH, BREADTH, DRAFT = 30.0, 10.0, 2.5
HEIGHT = 2.5 * DRAFT
BLOCK_COEFFICIENTS = (0.4, 0.6, 0.82)  # a fine hull, the default and a tanker
STATION_COUNTS = (1, 2, 3, 9, 10, 24)


@pytest.fixture(params=BLOCK_COEFFICIENTS)
def hull(request) -> HullForm:
    return HullForm.from_dimensions(LENGTH, BREADTH, DRAFT, request.param)


def mean_of(curve, samples: int = 20000) -> float:
    """Mean of a curve over the hull's length (xi from -1 to 1), by the midpoint rule."""
    return sum(curve(-1.0 + 2.0 * (index + 0.5) / samples) for index in range(samples)) / samples


class TestCoefficients:
    def test_the_midship_coefficient_follows_kerlens_formula(self):
        assert midship_coefficient_of(0.6) == pytest.approx(1.006 - 0.0056 * 0.6**-3.56)
        assert midship_coefficient_of(0.6) == pytest.approx(0.9715, abs=1e-4)

    def test_a_fuller_hull_has_a_fuller_midship_section_up_to_a_bilge_radius(self):
        values = [midship_coefficient_of(block) for block in (0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)]
        assert values == sorted(values)
        assert values[-1] == 0.99 and midship_coefficient_of(0.82) == 0.99, "the formula passes 0.99 near a block coefficient of 0.75"
        assert all(value <= 0.99 for value in values)

    def test_the_waterplane_coefficient_follows_schneekluths_formula(self):
        assert waterplane_coefficient_of(0.6) == pytest.approx(2.2 / 3.0)
        assert waterplane_coefficient_of(1.0) == pytest.approx(1.0)
        assert all(block < waterplane_coefficient_of(block) < 1.0 for block in BLOCK_COEFFICIENTS)

    def test_a_hull_derives_its_coefficients_from_the_block_coefficient(self, hull):
        assert hull.midship_coefficient == pytest.approx(midship_coefficient_of(hull.block_coefficient))
        assert hull.waterplane_coefficient == pytest.approx(waterplane_coefficient_of(hull.block_coefficient))
        assert hull.prismatic_coefficient == pytest.approx(hull.block_coefficient / hull.midship_coefficient)

    def test_the_coefficients_are_ordered_as_on_a_real_hull(self, hull):
        """Block below prismatic below waterplane, and nothing fuller than its rectangle."""
        assert hull.block_coefficient < hull.prismatic_coefficient < hull.waterplane_coefficient < 1.0
        assert hull.block_coefficient < hull.midship_coefficient < 1.0

    def test_given_coefficients_replace_the_derived_ones(self):
        hull = HullForm.from_dimensions(LENGTH, BREADTH, DRAFT, 0.6, midship_coefficient=0.9, waterplane_coefficient=0.8)
        assert (hull.midship_coefficient, hull.waterplane_coefficient) == (0.9, 0.8)
        assert hull.prismatic_coefficient == pytest.approx(0.6 / 0.9)

    def test_the_midship_section_is_never_finer_than_the_hull(self):
        """Kerlen's formula falls below the block coefficient for a very fine hull, and a given value may too."""
        assert HullForm.from_dimensions(LENGTH, BREADTH, DRAFT, 0.2).midship_coefficient == 0.2
        assert HullForm.from_dimensions(LENGTH, BREADTH, DRAFT, 0.6, midship_coefficient=0.3).midship_coefficient == 0.6
        assert HullForm.from_dimensions(LENGTH, BREADTH, DRAFT, 0.6, midship_coefficient=1.4).midship_coefficient == 1.0

    def test_the_waterline_is_at_least_as_full_as_the_sectional_area_curve(self):
        hull = HullForm.from_dimensions(LENGTH, BREADTH, DRAFT, 0.6, waterplane_coefficient=0.3)
        assert hull.waterplane_coefficient == pytest.approx(hull.prismatic_coefficient)
        assert HullForm.from_dimensions(LENGTH, BREADTH, DRAFT, 0.6, waterplane_coefficient=1.7).waterplane_coefficient == 1.0

    def test_volume_waterplane_and_wetted_surface(self, hull):
        assert hull.displaced_volume == pytest.approx(hull.block_coefficient * LENGTH * BREADTH * DRAFT)
        assert hull.waterplane_area == pytest.approx(hull.waterplane_coefficient * LENGTH * BREADTH)
        assert hull.wetted_surface == pytest.approx(1.7 * LENGTH * DRAFT + hull.displaced_volume / DRAFT), "Denny and Mumford"

    def test_the_wetted_surface_lies_between_the_waterplane_and_the_box(self, hull):
        assert hull.waterplane_area < hull.wetted_surface < LENGTH * (BREADTH + 2.0 * DRAFT)

    @pytest.mark.parametrize("length,breadth,draft", [(0.0, 10.0, 2.5), (30.0, 0.0, 2.5), (30.0, 10.0, 0.0), (-30.0, 10.0, 2.5), (30.0, -1.0, 2.5), (30.0, 10.0, -2.5)])
    def test_dimensions_that_are_not_positive_are_refused(self, length, breadth, draft):
        with pytest.raises(ValueError, match="a hull needs a positive length, breadth and draft"):
            HullForm.from_dimensions(length, breadth, draft, 0.6)

    @pytest.mark.parametrize("block_coefficient", [0.0, -0.2, 1.01, 6.0])
    def test_a_block_coefficient_outside_its_range_is_refused(self, block_coefficient):
        with pytest.raises(ValueError, match=r"the block coefficient must be in \(0, 1\]"):
            HullForm.from_dimensions(LENGTH, BREADTH, DRAFT, block_coefficient)

    def test_a_block_coefficient_of_one_is_a_box(self):
        hull = HullForm.from_dimensions(LENGTH, BREADTH, DRAFT, 1.0)
        assert (hull.midship_coefficient, hull.waterplane_coefficient, hull.prismatic_coefficient) == (1.0, 1.0, 1.0)
        for station in hull.stations(5):
            assert (station.breadth, station.depth) == pytest.approx((BREADTH, DRAFT))


class TestCurves:
    """The waterline and the sectional area curve the stations and the mesh are cut from."""

    def test_the_waterline_has_the_waterplane_coefficient_as_its_mean(self, hull):
        assert mean_of(hull.waterline_share) == pytest.approx(hull.waterplane_coefficient, abs=1e-6)

    def test_the_sectional_area_curve_has_the_prismatic_coefficient_as_its_mean(self, hull):
        assert mean_of(hull.section_share) == pytest.approx(hull.prismatic_coefficient, abs=1e-6)

    def test_both_curves_are_full_amidships_and_close_at_the_ends(self, hull):
        for curve in (hull.waterline_share, hull.section_share):
            assert curve(0.0) == 1.0
            assert curve(1.0) == pytest.approx(0.0, abs=1e-12) and curve(-1.0) == pytest.approx(0.0, abs=1e-12)

    def test_both_curves_fall_from_midship_toward_each_end(self, hull):
        positions = [index / 200.0 for index in range(201)]
        for curve in (hull.waterline_share, hull.section_share):
            for sign in (1.0, -1.0):
                ordinates = [curve(sign * position) for position in positions]
                assert all(0.0 <= later <= earlier <= 1.0 for earlier, later in zip(ordinates, ordinates[1:]))

    def test_the_bow_is_finer_than_the_stern_everywhere(self, hull):
        for index in range(1, 200):
            position = index / 200.0
            assert hull.waterline_share(position) <= hull.waterline_share(-position)
            assert hull.section_share(position) <= hull.section_share(-position)
        assert hull.waterline_share(0.8) < hull.waterline_share(-0.8)
        assert hull.section_share(0.8) < hull.section_share(-0.8)

    def test_no_section_overfills_the_rectangle_under_its_waterline(self, hull):
        """Section area over waterline breadth times draft is at most 1: the sectional area curve stays below the waterline."""
        for index in range(-199, 200):
            position = index / 200.0
            assert hull.midship_coefficient * hull.section_share(position) <= hull.waterline_share(position) + 1e-12


class TestStations:
    @pytest.mark.parametrize("count", STATION_COUNTS)
    def test_the_stations_displace_exactly_the_hulls_volume(self, hull, count):
        stations = hull.stations(count)
        assert stations_volume(stations) == pytest.approx(hull.block_coefficient * LENGTH * BREADTH * DRAFT, rel=1e-12)
        assert sum(station.volume for station in stations) == pytest.approx(hull.displaced_volume, rel=1e-12)

    @pytest.mark.parametrize("count", STATION_COUNTS)
    def test_the_stations_have_exactly_the_hulls_waterplane_area(self, hull, count):
        stations = hull.stations(count)
        assert stations_waterplane_area(stations) == pytest.approx(hull.waterplane_coefficient * LENGTH * BREADTH, rel=1e-12)

    @pytest.mark.parametrize("count", STATION_COUNTS)
    def test_the_stations_tile_the_hull_from_the_stern_to_the_stem(self, hull, count):
        stations = hull.stations(count)
        assert len(stations) == count
        step = LENGTH / count
        for index, station in enumerate(stations):
            assert station.length == pytest.approx(step)
            assert station.x == pytest.approx(-LENGTH / 2.0 + (index + 0.5) * step)
        assert stations[0].x - stations[0].length / 2.0 == pytest.approx(-LENGTH / 2.0)
        assert stations[-1].x + stations[-1].length / 2.0 == pytest.approx(LENGTH / 2.0)

    @pytest.mark.parametrize("count", STATION_COUNTS)
    def test_every_station_has_a_positive_breadth_and_depth_within_the_hull(self, hull, count):
        for station in hull.stations(count):
            assert 0.0 < station.breadth <= BREADTH * (1.0 + 1e-9)
            assert 0.0 < station.depth <= DRAFT * (1.0 + 1e-9)

    @pytest.mark.parametrize("count", (9, 10, 24))
    def test_every_station_holds_its_part_of_the_hull(self, hull, count):
        """Volume and waterplane of each station against the curves integrated over it, within a thousandth of a mean station."""
        samples = 2000
        for index, station in enumerate(hull.stations(count)):
            positions = [-1.0 + 2.0 * (index + (sample + 0.5) / samples) / count for sample in range(samples)]
            volume = hull.midship_coefficient * BREADTH * DRAFT * station.length * sum(hull.section_share(xi) for xi in positions) / samples
            waterplane = BREADTH * station.length * sum(hull.waterline_share(xi) for xi in positions) / samples
            assert station.volume == pytest.approx(volume, abs=1e-3 * hull.displaced_volume / count)
            assert station.waterplane_area == pytest.approx(waterplane, abs=1e-3 * hull.waterplane_area / count)

    def test_the_hull_is_fullest_amidships(self, hull):
        stations = hull.stations(9)
        middle = stations[4]
        assert middle.x == pytest.approx(0.0)
        assert middle.breadth >= 0.97 * max(station.breadth for station in stations), "the widest station is the middle one, or one of the parallel body next to it"
        assert middle.volume >= 0.97 * max(station.volume for station in stations)
        assert middle.breadth > stations[0].breadth and middle.breadth > stations[-1].breadth
        assert middle.volume > 2.0 * stations[0].volume and middle.volume > 2.0 * stations[-1].volume

    def test_breadth_and_volume_rise_to_midship_and_fall_again(self, hull):
        stations = hull.stations(9)
        for values in ([station.breadth for station in stations], [station.volume for station in stations]):
            tolerance = 1e-3 * max(values)  # stations of the parallel body are equal
            assert all(later >= earlier - tolerance for earlier, later in zip(values[:5], values[1:5]))
            assert all(later <= earlier + tolerance for earlier, later in zip(values[4:], values[5:]))

    @pytest.mark.parametrize("count", (2, 9, 10, 24))
    def test_the_bow_is_finer_than_the_stern(self, hull, count):
        stations = hull.stations(count)
        for aft, fore in zip(stations[: count // 2], reversed(stations)):
            assert fore.x == pytest.approx(-aft.x)
            assert fore.breadth <= aft.breadth * (1.0 + 1e-9)
            assert fore.volume <= aft.volume * (1.0 + 1e-9)
        assert stations[-1].breadth < stations[0].breadth and stations[-1].volume < stations[0].volume
        assert sum(station.volume * station.x for station in stations) < 0.0, "the center of buoyancy lies aft of midship"
        assert sum(station.waterplane_area * station.x for station in stations) < 0.0, "and so does the center of flotation"

    def test_one_station_is_the_box_of_the_whole_hull(self, hull):
        (station,) = hull.stations(1)
        assert (station.x, station.length) == (0.0, LENGTH)
        assert station.breadth == pytest.approx(hull.waterplane_coefficient * BREADTH)
        assert station.depth == pytest.approx(hull.block_coefficient / hull.waterplane_coefficient * DRAFT)

    def test_the_stations_scale_with_the_hull(self, hull):
        """Twice the hull in every direction: the same shape, so twice every station measure."""
        double = HullForm.from_dimensions(2.0 * LENGTH, 2.0 * BREADTH, 2.0 * DRAFT, hull.block_coefficient)
        for small, large in zip(hull.stations(9), double.stations(9)):
            assert (large.x, large.length, large.breadth, large.depth) == pytest.approx((2.0 * small.x, 2.0 * small.length, 2.0 * small.breadth, 2.0 * small.depth))

    def test_a_hull_without_stations_is_refused(self, hull):
        with pytest.raises(ValueError, match="a hull has at least one station, got 0"):
            hull.stations(0)

    def test_a_station_knows_its_volume_and_waterplane(self):
        station = HullStation(x=1.0, length=2.0, breadth=3.0, depth=0.5)
        assert station.volume == 3.0 and station.waterplane_area == 6.0

    def test_station_count_keeps_the_minimum(self):
        assert station_count(9, 4) == 9
        assert station_count(9, 21) == 21


def edge_counts(mesh: HullMesh) -> Tuple[Counter, Counter]:
    """How many faces share each edge, and how often each edge is walked in each direction."""
    undirected: Counter = Counter()
    directed: Counter = Counter()
    for a, b, c in mesh.faces:
        for start, end in ((a, b), (b, c), (c, a)):
            undirected[frozenset((start, end))] += 1
            directed[(start, end)] += 1
    return undirected, directed


def face_normal(mesh: HullMesh, face: Tuple[int, int, int]) -> Tuple[float, float, float]:
    """Not normalized: twice the face's area long."""
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = (mesh.vertices[index] for index in face)
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    return uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx


def parse_stl(text: str) -> List[Tuple[Tuple[float, float, float], List[Tuple[float, float, float]]]]:
    """(normal, three vertices) of every facet of an ASCII STL, checking its structure on the way."""
    lines = [line.strip() for line in text.splitlines()]
    facets = []
    index = 1
    while lines[index].startswith("facet normal"):
        normal = tuple(float(value) for value in lines[index].split()[2:])
        assert lines[index + 1] == "outer loop"
        vertices = []
        for line in lines[index + 2 : index + 5]:
            keyword, *values = line.split()
            assert keyword == "vertex" and len(values) == 3
            vertices.append(tuple(float(value) for value in values))
        assert lines[index + 5] == "endloop" and lines[index + 6] == "endfacet"
        assert len(normal) == 3
        facets.append((normal, vertices))
        index += 7
    assert index == len(lines) - 1, "nothing but facets between solid and endsolid"
    return facets


MESH_RESOLUTIONS = ((41, 9), (2, 3), (5, 4), (12, 6))


class TestMesh:
    @pytest.mark.parametrize("sections,points", MESH_RESOLUTIONS)
    def test_every_cross_section_has_its_vertices_at_its_own_station(self, hull, sections, points):
        mesh = hull.mesh(HEIGHT, sections, points)
        ring = 2 * points - 1
        assert len(mesh.vertices) == sections * ring
        for section in range(sections):
            x = (-1.0 + 2.0 * section / (sections - 1)) * LENGTH / 2.0
            assert [vertex[0] for vertex in mesh.vertices[section * ring : (section + 1) * ring]] == pytest.approx([x] * ring)

    @pytest.mark.parametrize("sections,points", MESH_RESOLUTIONS)
    def test_a_cross_section_runs_from_the_port_deck_edge_over_the_keel_to_the_starboard_deck_edge(self, hull, sections, points):
        mesh = hull.mesh(HEIGHT, sections, points)
        ring = 2 * points - 1
        for section in range(sections):
            vertices = mesh.vertices[section * ring : (section + 1) * ring]
            heights = [vertex[2] for vertex in vertices]
            assert heights[0] == pytest.approx(HEIGHT - DRAFT) and heights[-1] == pytest.approx(HEIGHT - DRAFT), "the deck edges"
            assert vertices[points - 1][1:] == (0.0, -DRAFT), "the keel"
            assert all(lower < upper for upper, lower in zip(heights[:points], heights[1:points])), "the port side goes down"
            assert heights.count(0.0) == 2, "one vertex at the waterline on each side"
            assert all(vertex[1] > 0.0 for vertex in vertices[: points - 1]) and all(vertex[1] < 0.0 for vertex in vertices[points:])

    @pytest.mark.parametrize("sections,points", MESH_RESOLUTIONS)
    def test_the_surface_is_closed(self, hull, sections, points):
        mesh = hull.mesh(HEIGHT, sections, points)
        undirected, directed = edge_counts(mesh)
        assert set(undirected.values()) == {2}, "every edge is shared by exactly two faces"
        assert set(directed.values()) == {1}, "which walk it in opposite directions, so the faces all look the same way"
        assert {index for face in mesh.faces for index in face} == set(range(len(mesh.vertices))), "and no vertex is left over"
        assert all(len(set(face)) == 3 for face in mesh.faces)

    @pytest.mark.parametrize("sections,points", MESH_RESOLUTIONS)
    def test_the_faces_look_outward(self, hull, sections, points):
        mesh = hull.mesh(HEIGHT, sections, points)
        assert mesh.enclosed_volume() > 0.0
        ring = 2 * points - 1
        # Spot checks of the direction: the first shell face lies on the port side, the first deck face looks up,
        # the caps look aft and forward.
        assert face_normal(mesh, mesh.faces[0])[1] > 0.0
        assert face_normal(mesh, mesh.faces[2 * (ring - 1)])[2] > 0.0
        stern, stem = mesh.faces[-2], mesh.faces[-1]
        assert face_normal(mesh, stern)[0] <= 0.0 and face_normal(mesh, stem)[0] >= 0.0

    def test_no_shell_face_looks_inward(self, hull):
        """Seen from the centerline at its own height, every face of the sides and the bottom looks away."""
        mesh = hull.mesh(HEIGHT)
        for face in mesh.faces:
            normal = face_normal(mesh, face)
            center = [sum(mesh.vertices[index][axis] for index in face) / 3.0 for axis in range(3)]
            if abs(normal[1]) > 1e-9 and abs(center[1]) > 1e-9:
                assert normal[1] * center[1] > 0.0, "a face to port of the centerline looks to port"

    def test_the_vertices_stay_within_the_hulls_box(self, hull):
        for x, y, z in hull.mesh(HEIGHT).vertices:
            assert -LENGTH / 2.0 <= x <= LENGTH / 2.0
            assert -BREADTH / 2.0 <= y <= BREADTH / 2.0
            assert -DRAFT <= z <= HEIGHT - DRAFT
        xs = [vertex[0] for vertex in hull.mesh(HEIGHT).vertices]
        assert (min(xs), max(xs)) == (-LENGTH / 2.0, LENGTH / 2.0), "the mesh is as long as the hull"

    def test_the_enclosed_volume_lies_between_the_displaced_volume_and_the_hulls_box(self, hull):
        volume = hull.mesh(HEIGHT).enclosed_volume()
        assert hull.displaced_volume < volume < LENGTH * BREADTH * HEIGHT
        assert volume < hull.displaced_volume + LENGTH * BREADTH * (HEIGHT - DRAFT), "at most the full deck area above the waterline"
        assert volume > hull.displaced_volume + 0.9 * hull.waterplane_area * (HEIGHT - DRAFT), "at least about the waterplane (the sides flare outward)"

    def test_the_underwater_part_is_the_displaced_volume(self, hull):
        """A hull whose deck lies at the waterline encloses its underwater part.

        The flat faces cut the round of the bilge, so the mesh holds less than the smooth hull, and
        the fullest cross section is capped at 0.98 of its rectangle where the midship coefficient
        reaches 0.99. With 161 sections of 33 points a side 3 percent covers both (measured: 0.1
        percent for the fine hull, 2.1 for the tanker); the default mesh of 41 sections of 9 points
        misses up to 12 percent of the tanker's full sections.
        """
        awash = DRAFT * (1.0 + 1e-9)
        fine = hull.mesh(awash, sections=161, points=33).enclosed_volume()
        default = hull.mesh(awash).enclosed_volume()
        assert fine == pytest.approx(hull.displaced_volume, rel=0.03)
        assert default == pytest.approx(hull.displaced_volume, rel=0.12)
        assert abs(fine - hull.displaced_volume) < abs(default - hull.displaced_volume), "a finer mesh comes closer"

    def test_the_underwater_cross_sections_have_the_area_of_the_sectional_area_curve(self, hull):
        """Along the middle body, where neither the section's fullness nor its breadth is capped."""
        samples = 4000
        for position in (-0.5, -0.25, 0.0, 0.25, 0.5):
            depths = [-DRAFT * (sample + 0.5) / samples for sample in range(samples)]
            area = 2.0 * sum(hull.half_breadth(position, z, HEIGHT) for z in depths) * DRAFT / samples
            wanted = min(hull.midship_coefficient * hull.section_share(position), 0.98 * hull.waterline_share(position)) * BREADTH * DRAFT
            assert area == pytest.approx(wanted, rel=2e-3)

    def test_the_sides_follow_the_waterline_and_flare_to_the_deck(self, hull):
        freeboard = HEIGHT - DRAFT
        for position in (-0.9, -0.5, 0.0, 0.5, 0.9):
            waterline = hull.waterline_share(position) * BREADTH / 2.0
            assert hull.half_breadth(position, 0.0, HEIGHT) == pytest.approx(waterline)
            assert hull.half_breadth(position, -DRAFT, HEIGHT) == pytest.approx(0.0, abs=1e-12), "the keel"
            deck = hull.half_breadth(position, freeboard, HEIGHT)
            assert deck == pytest.approx(waterline + DECK_FLARE * (BREADTH / 2.0 - waterline))
            below = [hull.half_breadth(position, -DRAFT * step / 20.0, HEIGHT) for step in range(21)]
            assert all(deeper <= shallower for shallower, deeper in zip(below, below[1:])), "the hull narrows toward the keel"

    def test_the_ends_keep_a_sliver_of_breadth(self, hull):
        """So that no face of the stem or the stern collapses to a line."""
        for position in (-1.0, 1.0):
            assert hull.half_breadth(position, 0.0, HEIGHT) == pytest.approx(END_BREADTH_SHARE * BREADTH / 2.0)

    @pytest.mark.parametrize("sections,points", MESH_RESOLUTIONS)
    def test_port_and_starboard_are_mirror_images(self, hull, sections, points):
        mesh = hull.mesh(HEIGHT, sections, points)
        ring = 2 * points - 1
        for section in range(sections):
            vertices = mesh.vertices[section * ring : (section + 1) * ring]
            for port, starboard in zip(vertices, reversed(vertices)):
                assert (port[0], -port[1], port[2]) == starboard
        assert set(mesh.vertices) == {(x, -y, z) for x, y, z in mesh.vertices}

    def test_the_mirrored_halves_enclose_the_same_volume(self, hull):
        mesh = hull.mesh(HEIGHT)
        mirrored = HullMesh(tuple((x, -y, z) for x, y, z in mesh.vertices), tuple((a, c, b) for a, b, c in mesh.faces))
        assert mirrored.enclosed_volume() == pytest.approx(mesh.enclosed_volume(), rel=1e-12)

    def test_the_mesh_grows_with_the_hull_height_above_the_waterline_only(self, hull):
        low, high = hull.mesh(1.5 * DRAFT), hull.mesh(3.0 * DRAFT)
        assert high.enclosed_volume() > low.enclosed_volume()
        assert [vertex for vertex in low.vertices if vertex[2] <= 0.0] == [vertex for vertex in high.vertices if vertex[2] <= 0.0]

    def test_a_hull_no_higher_than_its_draft_has_no_mesh(self, hull):
        with pytest.raises(ValueError, match="must exceed the draft"):
            hull.mesh(DRAFT)
        with pytest.raises(ValueError, match="must exceed the draft"):
            hull.mesh(0.5 * DRAFT)

    @pytest.mark.parametrize("sections,points", [(1, 9), (41, 2), (0, 0)])
    def test_too_coarse_a_mesh_is_refused(self, hull, sections, points):
        with pytest.raises(ValueError, match="at least 2 sections of 3 points per side"):
            hull.mesh(HEIGHT, sections, points)

    def test_enclosed_volume_of_a_known_solid(self):
        """A tetrahedron with outward faces holds a sixth of its box; turned inside out the volume is negative."""
        vertices = ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 3.0, 0.0), (0.0, 0.0, 4.0))
        outward = HullMesh(vertices, ((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)))
        assert outward.enclosed_volume() == pytest.approx(4.0)
        inward = HullMesh(vertices, tuple((a, c, b) for a, b, c in outward.faces))
        assert inward.enclosed_volume() == pytest.approx(-4.0)


class TestMovedMesh:
    """HullMesh.moved: the surface in the model's frame, whose origin is not amidships."""

    @pytest.mark.parametrize("offset", [0.613, -2.0, 15.0])
    def test_every_vertex_moves_along_the_hull_only(self, hull, offset):
        mesh = hull.mesh(HEIGHT)
        moved = mesh.moved(offset)
        assert len(moved.vertices) == len(mesh.vertices)
        for (x, y, z), (moved_x, moved_y, moved_z) in zip(mesh.vertices, moved.vertices):
            assert moved_x == pytest.approx(x + offset, abs=1e-12)
            assert (moved_y, moved_z) == (y, z)

    def test_the_faces_stay_the_same(self, hull):
        mesh = hull.mesh(HEIGHT)
        moved = mesh.moved(0.613)
        assert moved.faces == mesh.faces
        undirected, directed = edge_counts(moved)
        assert set(undirected.values()) == {2} and set(directed.values()) == {1}, "still closed"

    def test_the_moved_surface_encloses_the_same_volume(self, hull):
        mesh = hull.mesh(HEIGHT)
        assert mesh.moved(0.613).enclosed_volume() == pytest.approx(mesh.enclosed_volume(), rel=1e-9)
        assert mesh.moved(-40.0).enclosed_volume() == pytest.approx(mesh.enclosed_volume(), rel=1e-9), "wherever it lies"

    def test_the_moved_surface_spans_the_hull_from_its_new_place(self, hull):
        xs = [vertex[0] for vertex in hull.mesh(HEIGHT).moved(0.613).vertices]
        assert (min(xs), max(xs)) == pytest.approx((-LENGTH / 2.0 + 0.613, LENGTH / 2.0 + 0.613))

    def test_the_mesh_itself_is_left_where_it_was(self, hull):
        mesh = hull.mesh(HEIGHT)
        before = mesh.vertices
        moved = mesh.moved(3.0)
        assert moved is not mesh and mesh.vertices is before
        assert mesh == hull.mesh(HEIGHT)

    def test_moving_by_nothing_and_moving_back_give_the_mesh_again(self, hull):
        mesh = hull.mesh(HEIGHT)
        assert mesh.moved(0.0) == mesh
        there_and_back = mesh.moved(0.5).moved(-0.5)
        assert there_and_back.faces == mesh.faces
        for vertex, original in zip(there_and_back.vertices, mesh.vertices):
            assert vertex == pytest.approx(original, abs=1e-12)

    def test_the_stl_of_a_moved_mesh_has_its_vertices_moved_and_its_normals_kept(self, hull):
        mesh = hull.mesh(HEIGHT, 5, 4)
        for (normal, vertices), (moved_normal, moved_vertices) in zip(parse_stl(mesh.to_stl()), parse_stl(mesh.moved(2.0).to_stl())):
            assert moved_normal == pytest.approx(normal, abs=1e-5)
            for (x, y, z), moved in zip(vertices, moved_vertices):
                assert moved == pytest.approx((x + 2.0, y, z), rel=1e-5, abs=1e-9)


class TestStl:
    def test_the_text_is_a_named_ascii_solid(self, hull):
        text = hull.mesh(HEIGHT).to_stl("agent_3_hull")
        lines = text.splitlines()
        assert lines[0] == "solid agent_3_hull" and lines[-1] == "endsolid agent_3_hull"
        assert text.endswith("endsolid agent_3_hull\n")
        assert text.isascii()

    def test_the_default_name_is_hull(self, hull):
        assert hull.mesh(HEIGHT, 2, 3).to_stl().startswith("solid hull\n")

    @pytest.mark.parametrize("sections,points", MESH_RESOLUTIONS)
    def test_there_is_one_facet_for_every_face_that_has_an_area(self, hull, sections, points):
        mesh = hull.mesh(HEIGHT, sections, points)
        with_area = [face for face in mesh.faces if math.sqrt(sum(component**2 for component in face_normal(mesh, face))) != 0.0]
        facets = parse_stl(mesh.to_stl())
        assert len(facets) == len(with_area)
        assert len(with_area) >= len(mesh.faces) - 4 * points, "only faces of the stem and stern caps can collapse (their side is straight above the waterline)"

    def test_every_facet_carries_its_unit_normal_and_its_three_vertices(self, hull):
        mesh = hull.mesh(HEIGHT)
        with_area = [face for face in mesh.faces if math.sqrt(sum(component**2 for component in face_normal(mesh, face))) != 0.0]
        for (normal, vertices), face in zip(parse_stl(mesh.to_stl()), with_area):
            assert math.sqrt(sum(component**2 for component in normal)) == pytest.approx(1.0, abs=1e-5)
            exact = face_normal(mesh, face)
            length = math.sqrt(sum(component**2 for component in exact))
            assert normal == pytest.approx(tuple(component / length for component in exact), abs=1e-5)
            for written, index in zip(vertices, face):
                assert written == pytest.approx(mesh.vertices[index], rel=1e-5, abs=1e-9)

    def test_the_written_solid_encloses_the_meshs_volume(self, hull):
        """The facets keep the faces' winding, so the volume from the file is the mesh's (to the six digits it is written with)."""
        mesh = hull.mesh(HEIGHT)
        total = 0.0
        for _, ((ax, ay, az), (bx, by, bz), (cx, cy, cz)) in parse_stl(mesh.to_stl()):
            total += ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)
        assert total / 6.0 == pytest.approx(mesh.enclosed_volume(), rel=1e-4)

    def test_a_collapsed_face_is_left_out(self):
        mesh = HullMesh(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 1.0, 0.0)), ((0, 1, 2), (0, 1, 3)))
        facets = parse_stl(mesh.to_stl())
        assert len(facets) == 1
        assert facets[0][0] == (0.0, 0.0, 1.0)

    def test_generation_is_deterministic(self, hull):
        assert hull.mesh(HEIGHT).to_stl("hull") == hull.mesh(HEIGHT).to_stl("hull")
