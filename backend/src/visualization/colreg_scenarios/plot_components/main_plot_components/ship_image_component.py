import xml.etree.ElementTree as ET
from functools import lru_cache
from math import degrees
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from matplotlib import pyplot as plt
from matplotlib import transforms as mtransforms
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath
from svgpath2mpl import parse_path  # type: ignore[import]

from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor
from utils.colors import light_colors
from utils.file_system_utils import IMAGES_FOLDER
from utils.vessel_types import UnspecifiedVesselType
from visualization.colreg_scenarios.plot_components.plot_component import PlotComponent


class ShipImageComponent(PlotComponent):
    def __init__(self, ax: plt.Axes, monitored_scene: MonitoredScene) -> None:
        super().__init__(ax, monitored_scene)
        self.vector_paths = {
            True: self._load_normalized_path(Path(IMAGES_FOLDER) / "ship.svg"),
            False: self._load_normalized_path(Path(IMAGES_FOLDER) / "buoy.svg"),
        }
        self.image_graphs: Dict[ConcreteActor, PathPatch] = {}
        self.zorder = -4
        self._min_icon_px = 18
        self._max_icon_px = 36

    def do_draw(self):
        for actor, state in self.monitored_scene.scene.items():
            patch = PathPatch(
                self.vector_paths[actor.is_vessel],
                facecolor=light_colors[actor.id],
                edgecolor="black",
                lw=0.8,
                zorder=self.zorder,
            )
            patch.set_transform(self._build_transform(state, actor))
            self.ax.add_patch(patch)
            self.image_graphs[actor] = patch

            self.graphs.append(patch)

    def do_update(self, monitored_scene: MonitoredScene) -> List[plt.Artist]:
        for actor, state in monitored_scene.scene.items():
            if not self.image_graphs[actor].get_visible():
                continue
            self.image_graphs[actor].set_transform(self._build_transform(state, actor))
        return self.graphs

    def reset(self) -> List[plt.Artist]:
        """Reset ship icons when animation restarts or is rewound."""
        return super().reset()

    def _build_transform(self, state: ActorState, actor: ConcreteActor) -> mtransforms.Transform:
        scale = self._compute_scale(actor)
        heading = degrees(state.heading) + 90
        return mtransforms.Affine2D().scale(scale).rotate_deg(heading).translate(state.x, state.y) + self.ax.transData

    def _compute_scale(self, actor: ConcreteActor) -> float:
        # data_per_pixel = self._data_units_per_pixel()
        # if data_per_pixel is None:
        #    return 1.0
        data_per_pixel = 10.0
        normalized = actor.length / UnspecifiedVesselType.max_length
        normalized = np.clip(normalized, 0.0, 1.0)
        desired_px = self._min_icon_px + normalized * (self._max_icon_px - self._min_icon_px)
        return desired_px * data_per_pixel

    def _data_units_per_pixel(self) -> Optional[float]:
        bbox = self.ax.bbox
        width_pixels = bbox.width
        if width_pixels <= 0:
            return None
        xlim = self.ax.get_xlim()
        xrange = abs(xlim[1] - xlim[0])
        if xrange == 0:
            return None
        return xrange / width_pixels

    @staticmethod
    @lru_cache(maxsize=4)
    def _load_normalized_path(svg_file: Path):
        svg_data = svg_file.read_text()
        try:
            root = ET.fromstring(svg_data)
        except ET.ParseError as exc:
            raise ValueError(f"Invalid SVG file: {svg_file}") from exc

        path_segments = []
        for element in root.iter():
            maybe_path = ShipImageComponent._path_from_element(element)
            if maybe_path is not None:
                path_segments.append(maybe_path)

        if not path_segments:
            raise ValueError(f"No supported vector shapes found in {svg_file}")

        if len(path_segments) == 1:
            path = path_segments[0]
        else:
            vertices = np.concatenate([segment.vertices for segment in path_segments])
            codes = np.concatenate([segment.codes for segment in path_segments])
            path = MplPath(vertices, codes)

        vertices = np.array(path.vertices)
        min_vals = vertices.min(axis=0)
        max_vals = vertices.max(axis=0)
        center = (min_vals + max_vals) / 2.0
        size = (max_vals - min_vals).max()
        if size == 0:
            size = 1.0
        normalized_vertices = (vertices - center) / size
        path.vertices = normalized_vertices
        return path

    @staticmethod
    def _strip_namespace(tag: str) -> str:
        return tag.split("}")[-1]

    @staticmethod
    def _path_from_element(element: ET.Element) -> Optional[MplPath]:
        tag = ShipImageComponent._strip_namespace(element.tag)
        builders = {
            "path": ShipImageComponent._build_path_tag,
            "circle": ShipImageComponent._build_circle_path,
            "ellipse": ShipImageComponent._build_ellipse_path,
            "rect": ShipImageComponent._build_rect_path,
            "polygon": ShipImageComponent._build_polygon_path,
            "polyline": ShipImageComponent._build_polyline_path,
        }
        builder = builders.get(tag)
        if builder is None:
            return None
        return builder(element)

    @staticmethod
    def _build_path_tag(element: ET.Element) -> Optional[MplPath]:
        d_attr = element.get("d")
        if not d_attr:
            return None
        return parse_path(d_attr)

    @staticmethod
    def _build_circle_path(element: ET.Element) -> Optional[MplPath]:
        r = float(element.get("r", 0))
        if r == 0:
            return None
        cx = float(element.get("cx", 0))
        cy = float(element.get("cy", 0))
        base = MplPath.unit_circle()
        transform = mtransforms.Affine2D().scale(r).translate(cx, cy)
        return transform.transform_path(base)

    @staticmethod
    def _build_ellipse_path(element: ET.Element) -> Optional[MplPath]:
        rx = float(element.get("rx", 0))
        ry = float(element.get("ry", 0))
        if rx == 0 or ry == 0:
            return None
        cx = float(element.get("cx", 0))
        cy = float(element.get("cy", 0))
        base = MplPath.unit_circle()
        transform = mtransforms.Affine2D().scale(rx, ry).translate(cx, cy)
        return transform.transform_path(base)

    @staticmethod
    def _build_rect_path(element: ET.Element) -> Optional[MplPath]:
        width = float(element.get("width", 0))
        height = float(element.get("height", 0))
        if width == 0 or height == 0:
            return None
        x = float(element.get("x", 0))
        y = float(element.get("y", 0))
        vertices = np.array(
            [
                [x, y],
                [x + width, y],
                [x + width, y + height],
                [x, y + height],
                [x, y],
            ]
        )
        codes = np.array(
            [
                MplPath.MOVETO,
                MplPath.LINETO,
                MplPath.LINETO,
                MplPath.LINETO,
                MplPath.CLOSEPOLY,
            ]
        )
        return MplPath(vertices, codes)

    @staticmethod
    def _build_polygon_path(element: ET.Element) -> Optional[MplPath]:
        return ShipImageComponent._build_polyline_like_path(element, close=True)

    @staticmethod
    def _build_polyline_path(element: ET.Element) -> Optional[MplPath]:
        return ShipImageComponent._build_polyline_like_path(element, close=False)

    @staticmethod
    def _build_polyline_like_path(element: ET.Element, *, close: bool) -> Optional[MplPath]:
        points_attr = element.get("points", "")
        points = []
        for pair in points_attr.split():
            if "," not in pair:
                continue
            px, py = pair.split(",")
            points.append([float(px), float(py)])
        if not points:
            return None
        if close:
            points.append(points[0])
        vertices = np.array(points)
        codes = [MplPath.MOVETO] + [MplPath.LINETO] * (len(points) - 1)
        if close:
            codes[-1] = MplPath.CLOSEPOLY
        return MplPath(vertices, codes)
