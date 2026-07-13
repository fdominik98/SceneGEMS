import math

import numpy as np
from geographiclib.geodesic import Geodesic
from shapely.geometry import LineString, Point, Polygon  # type: ignore  # noqa: PGH003


class HullSearch:
    def calculate_search_pattern(
        self,
        points: list = None,
        spacing_meters: float = 3.0,
        altitude: float = 10.0,
        epsilon: float = 0.0001,
    ):
        if points is None:
            points = []

        def create_grid_within_hull(hull_points, spacing_meters):
            min_lat = np.min(hull_points[:, 0])
            max_lat = np.max(hull_points[:, 0])
            min_lon = np.min(hull_points[:, 1])
            max_lon = np.max(hull_points[:, 1])

            # Calculate approximate spacing in degrees
            lat_spacing_deg = spacing_meters / 111320  # meters per degree latitude
            lon_spacing_deg = spacing_meters / (
                111320 * np.cos(np.radians(min_lat))
            )  # meters per degree longitude at min_lat

            lat_range = np.arange(min_lat, max_lat, lat_spacing_deg)
            lon_range = np.arange(min_lon, max_lon, lon_spacing_deg)

            grid_points = []
            for lat in lat_range:
                for lon in lon_range:
                    point = [lat, lon]
                    if SearchHelpers.point_in_polygon(point, hull_points):
                        grid_points.append(point)

            return grid_points

        def plan_search_path(grid_points, altitude):
            grid_points.sort(key=lambda x: (x[0], x[1]))
            path = []
            toggle = False
            for i in range(len(grid_points)):
                if toggle:
                    path.append(grid_points[i] + [altitude])
                else:
                    path.append(grid_points[i] + [altitude])
                toggle = not toggle
            return path

        # Convert the input list to a numpy array for easier manipulation
        points = np.array(
            [p[:2] for p in points]
        )  # Only consider the first two values (latitude and longitude)

        # Step 1: Compute the convex hull
        hull_points = SearchHelpers.compute_convex_hull(points)

        # Step 2: Create a grid within the convex hull
        grid_points = create_grid_within_hull(hull_points, spacing_meters)

        # Step 3: Plan the search path
        search_path = plan_search_path(grid_points, altitude)

        # Step 4: Simplify the path
        simplified_path = SearchHelpers.ramer_douglas_peucker(search_path, epsilon)

        # Step 5: Adjust points outside the convex hull
        final_path = SearchHelpers.adjust_points_inside_hull(
            simplified_path, hull_points
        )

        # Step 6: Format the final path with the required precision
        formatted_path = [
            [round(float(lat), 7), round(float(lon), 7), round(float(alt), 3)]
            for lat, lon, alt in final_path
        ]

        return SearchHelpers.truncate_search_path(formatted_path)


class SpiralSearch:
    def calculate_search_pattern(
        self, area: list, spacing_meters: int = 3, search_alt_rel: float = 10.0
    ):
        """Generate a spiral path from the boundary towards the center."""
        if not area:
            return []

        path = []
        polygon = Polygon(area)

        if not polygon.is_valid:
            # Try to make valid.
            polygon = polygon.buffer(0)

            if not polygon.is_valid:
                raise ValueError("The provided area does not form a valid polygon.")

        center = SearchHelpers.calculate_center(area)

        # Calculate maximum distance from center to boundary using geographiclib
        geod = Geodesic.WGS84
        max_distance = 0
        for point in area:
            dist_info = geod.Inverse(center[0], center[1], point[0], point[1])
            distance_to_point = dist_info["s12"]
            max_distance = max(distance_to_point, max_distance)

        # Calculate the number of rounds
        number_of_rounds = int(max_distance / spacing_meters)
        number_of_rounds_left = number_of_rounds

        current_bounds = area

        for _ in range(number_of_rounds):
            new_bounds = []

            for point in current_bounds:
                # Calculate distance from the point to the center
                dist_info = geod.Inverse(center[0], center[1], point[0], point[1])
                distance_to_center = dist_info["s12"]

                # Calculate the new position towards the center
                distance_to_move = distance_to_center / number_of_rounds_left
                direction = dist_info["azi1"]
                new_point_info = geod.Direct(
                    point[0], point[1], direction + 180, distance_to_move
                )
                new_point = [new_point_info["lat2"], new_point_info["lon2"]]

                # # Adjust new_point to ensure it's within the polygon
                # new_point_geom = Point(new_point)
                # if not polygon.contains(new_point_geom):
                #     hull_line = LineString(area)
                #     nearest_point = hull_line.interpolate(
                #         hull_line.project(new_point_geom)
                #     )
                #     new_point = [nearest_point.x, nearest_point.y]

                new_bounds.append(new_point)

            if number_of_rounds_left > 1:
                number_of_rounds_left = number_of_rounds_left - 1

            # Merge points that are too close
            merged_bounds = []
            for i, point in enumerate(new_bounds):
                if i == 0:
                    merged_bounds.append(point)
                else:
                    prev_point = merged_bounds[-1]
                    dist = geod.Inverse(
                        prev_point[0], prev_point[1], point[0], point[1]
                    )["s12"]
                    if dist < spacing_meters / 2:
                        # Merge points
                        merged_point = [
                            (prev_point[0] + point[0]) / 2,
                            (prev_point[1] + point[1]) / 2,
                        ]
                        merged_bounds[-1] = merged_point
                    else:
                        merged_bounds.append(point)

            current_bounds = merged_bounds

            # Add altitude for 3D point
            for point in current_bounds:
                path.append(point + [search_alt_rel])

        # Format the path with the required precision
        formatted_path = [
            [round(lat, 7), round(lon, 7), round(alt, 3)] for lat, lon, alt in path
        ]

        return SearchHelpers.truncate_search_path(formatted_path)


class GridSearch:
    def calculate_search_pattern(
        self, area: list, spacing_meters: int = 3, search_alt_rel: float = 10.0
    ):
        """Generate a grid search pattern within the specified area."""
        if not area:
            return []

        path = []
        polygon = Polygon(area)

        if not polygon.is_valid:
            # Try to make valid.
            polygon = polygon.buffer(0)

            if not polygon.is_valid:
                raise ValueError("The provided area does not form a valid polygon.")

        # Adjust the spacing
        space: float = spacing_meters

        # Calculate bounds of the polygon
        miny, minx, maxy, maxx = polygon.bounds

        # Create grid points
        current_lat = miny
        geod = Geodesic.WGS84

        while current_lat <= maxy:
            current_lon = minx
            while current_lon <= maxx:
                point = Point(current_lat, current_lon)
                if polygon.contains(point):
                    path.append([current_lat, current_lon, search_alt_rel])
                # Move to the next grid point in the longitude direction
                lon_info = geod.Direct(current_lat, current_lon, 90, space)
                current_lon = lon_info["lon2"]
            # Move to the next grid point in the latitude direction
            lat_info = geod.Direct(current_lat, minx, 0, space)
            current_lat = lat_info["lat2"]

        # Simplify the path by removing intermediate collinear points
        simplified_path = SearchHelpers.simplify_path(path)

        # Format the path with the required precision
        formatted_path = [
            [round(lat, 7), round(lon, 7), round(alt, 3)]
            for lat, lon, alt in simplified_path
        ]

        return SearchHelpers.truncate_search_path(formatted_path)


# HELPERS ==============================================================


class SearchHelpers:
    @staticmethod
    def calculate_center(area):
        """Calculate the geometric center of the polygon."""
        latitudes = [point[0] for point in area]
        longitudes = [point[1] for point in area]
        center_lat = sum(latitudes) / len(latitudes)
        center_lon = sum(longitudes) / len(longitudes)
        return center_lat, center_lon

    # Function to check if three points are collinear
    @staticmethod
    def is_collinear(p1, p2, p3):
        # Calculate the area of the triangle formed by p1, p2, p3
        # If the area is zero, the points are collinear
        return (p2[0] - p1[0]) * (p3[1] - p1[1]) == (p3[0] - p1[0]) * (p2[1] - p1[1])

    @staticmethod
    def simplify_path(path: list):
        # Simplify the path by removing intermediate collinear points
        simplified_path: list = []
        if len(path) >= 3:
            simplified_path.append(path[0])
            for i in range(1, len(path) - 1):
                if not SearchHelpers.is_collinear(path[i - 1], path[i], path[i + 1]):
                    simplified_path.append(path[i])
            simplified_path.append(path[-1])
        else:
            # If the path has fewer than 3 points, just copy it as is
            simplified_path = path

        return simplified_path

    @staticmethod
    def point_in_polygon(point, polygon):
        """Check if a point is inside a polygon using ray-casting algorithm."""
        x, y = point
        n = len(polygon)
        inside = False

        p1x, p1y = polygon[0][:2]
        for i in range(n + 1):
            p2x, p2y = polygon[i % n][:2]
            xinters = None
            if y > min(p1y, p2y):  # noqa: SIM102
                if y <= max(p1y, p2y):  # noqa: SIM102
                    if x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or x <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y

        return inside

    @staticmethod
    def compute_convex_hull(points):
        """Compute the convex hull of a set of 2D points."""
        points_2d = sorted(points, key=lambda x: (x[0], x[1]))

        def cross(o, a, b):
            return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

        # Build the lower hull
        lower = []
        for p in points_2d:
            while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
                lower.pop()
            lower.append(p)

        # Build the upper hull
        upper = []
        for p in reversed(points_2d):
            while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
                upper.pop()
            upper.append(p)

        # Concatenate lower and upper hull
        return np.array(lower[:-1] + upper[:-1])

    @staticmethod
    def adjust_points_inside_hull(points, hull_points):
        """Adjust points outside the convex hull to be inside."""
        hull_polygon = Polygon(hull_points)
        adjusted_points = []
        for point in points:
            point_geom = Point(point[:2])
            if not hull_polygon.contains(point_geom):
                # Find the closest point on the hull boundary
                hull_line = LineString(hull_points)
                nearest_point = hull_line.interpolate(hull_line.project(point_geom))
                adjusted_points.append([nearest_point.x, nearest_point.y, point[2]])
            else:
                adjusted_points.append(point)
        return adjusted_points

    @staticmethod
    def adjust_points_inside_area(area, points):
        hull_points = SearchHelpers.compute_convex_hull(points)
        hull_polygon = Polygon(hull_points)
        adjusted_points = []
        for point in points:
            point_geom = Point(point[:2])
            if not hull_polygon.contains(point_geom):
                # Find the closest point on the hull boundary
                hull_line = LineString(hull_points)
                nearest_point = hull_line.interpolate(hull_line.project(point_geom))
                adjusted_points.append([nearest_point.x, nearest_point.y, point[2]])
            else:
                adjusted_points.append(point)
        return adjusted_points

    @staticmethod
    def truncate_search_path(search_path, max_items=600):
        if len(search_path) <= max_items:
            return search_path

        epsilon: float = 0.0001

        while True:
            wps: list = SearchHelpers.ramer_douglas_peucker(search_path, epsilon)
            wps_len = len(wps)

            print(f"{wps_len} {epsilon}")

            if wps_len > max_items:
                epsilon = epsilon * 2
            else:
                return wps

    @staticmethod
    def ramer_douglas_peucker(points, epsilon: float = 0.0001):
        """Simplify the path using the Ramer-Douglas-Peucker algorithm."""
        if len(points) < 3:
            return points

        # Find the point with the maximum distance from the line between the first and last point
        start, end = points[0], points[-1]
        max_dist = -1
        index = -1
        for i in range(1, len(points) - 1):
            dist = np.linalg.norm(
                np.cross(
                    np.array(end[:2]) - np.array(start[:2]),
                    np.array(start[:2]) - np.array(points[i][:2]),
                )
            ) / np.linalg.norm(np.array(end[:2]) - np.array(start[:2]))
            if dist > max_dist:
                max_dist = dist
                index = i

        # If the maximum distance is greater than epsilon, recursively simplify
        if max_dist > epsilon:
            left = SearchHelpers.ramer_douglas_peucker(points[: index + 1], epsilon)
            right = SearchHelpers.ramer_douglas_peucker(points[index:], epsilon)
            return left[:-1] + right
        else:
            return [start, end]

    @staticmethod
    def ramer_douglas_peucker_max_points(points, max_points):
        if len(points) <= max_points or len(points) < 3:
            return points

        # Recursive function to simplify path
        def simplify(points, num_points):
            if len(points) <= num_points:
                return points

            # Find the point with the maximum distance from the line between the first and last point
            start, end = points[0], points[-1]
            max_dist = -1
            index = -1
            for i in range(1, len(points) - 1):
                dist = np.linalg.norm(
                    np.cross(
                        np.array(end[:2]) - np.array(start[:2]),
                        np.array(start[:2]) - np.array(points[i][:2]),
                    )
                ) / np.linalg.norm(np.array(end[:2]) - np.array(start[:2]))
                if dist > max_dist:
                    max_dist = dist
                    index = i

            # If we cannot reduce more, return the endpoints
            if index == -1:
                return [start, end]

            # Recursively simplify the path
            left = simplify(points[: index + 1], num_points // 2 + 1)
            right = simplify(points[index:], num_points - len(left) + 1)

            return left[:-1] + right

        return simplify(points, max_points)

    @staticmethod
    def calculate_altitude(
        coverage_meters: float, overlap_percent: float, camera_fov_degrees: float
    ) -> float:
        # Adjust the coverage for the overlap
        effective_coverage = coverage_meters * (1 - overlap_percent / 100)

        # Convert the full FOV to half for the tangent calculation
        half_fov_radians = math.radians(camera_fov_degrees / 2)

        # Calculate the altitude using the tangent of half the FOV
        altitude = (effective_coverage / 2) / math.tan(half_fov_radians)

        return altitude

    @staticmethod
    def calculate_coverage(
        altitude_meters: float, overlap_percent: float, camera_fov_degrees: float
    ) -> float:
        # Convert the full FOV to half for the tangent calculation
        half_fov_radians = math.radians(camera_fov_degrees / 2)

        # Calculate the coverage using the tangent of half the FOV
        coverage = 2 * altitude_meters * math.tan(half_fov_radians)

        # Adjust the coverage for the overlap
        effective_coverage = coverage * (1 - overlap_percent / 100)

        return effective_coverage


# Example usage
area_1 = [
    [57.75906377316506, 16.678234081919438],
    [57.7598069047565, 16.67715653229311],
    [57.760061844190645, 16.677593651481157],
    [57.7598069047565, 16.679077823607997],
    [57.759709267901165, 16.680226532171904],
    [57.75857015176367, 16.68031802223451],
    [57.75840741795576, 16.67693288991785],
    [57.75879255344942, 16.67691255879283],
]

area_2 = [
    [57.760511099921025, 16.669109164670914],
    [57.76109850825079, 16.670100190113345],
    [57.76023341265944, 16.671601743814],
    [57.76103976784751, 16.672682862478474],
    [57.7605057598015, 16.674054281525077],
    [57.75983289842763, 16.67247264496036],
    [57.7592988725468, 16.673643856846876],
    [57.75867939263834, 16.67243260352835],
    [57.75964065001965, 16.672262427442288],
    [57.7591279825982, 16.671481619517934],
    [57.75968337197647, 16.67036045942145],
    [57.76006786731516, 16.671101225913795],
    [57.75961928902231, 16.668608646770707],
    [57.76014262982262, 16.66864868820272],
    [57.7602387528192, 16.670100190113345],
]

if __name__ == "__main__":
    area_orig = area_1
    space_m: float = 10.0
    alt_m: float = 10

    hull_search = HullSearch()
    hull_pattern = hull_search.calculate_search_pattern(area_orig, space_m, alt_m)
    print(f"Hull: {len(hull_pattern)}")

    spiral_search = SpiralSearch()
    spiral_pattern = spiral_search.calculate_search_pattern(area_orig, space_m, alt_m)
    print(f"Spiral: {len(spiral_pattern)}")

    grid_search = GridSearch()
    grid_pattern = grid_search.calculate_search_pattern(area_orig, space_m, alt_m)
    print(f"Grid: {len(grid_pattern)}")

    # Plot and save the search pattern
    # myp = Plot.Plot()
    # myp.plot_search_pattern(area_orig, hull_pattern, "pattern_hull.png")
    # myp.plot_search_pattern(area_orig, spiral_pattern, "pattern_spiral.png")
    # myp.plot_search_pattern(area_orig, grid_pattern, "pattern_grid.png")
