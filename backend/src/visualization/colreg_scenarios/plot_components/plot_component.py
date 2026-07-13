from abc import ABC, abstractmethod
from typing import List

from matplotlib import pyplot as plt

from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene


class PlotComponent(ABC):
    def __init__(self, ax: plt.Axes, monitored_scene: MonitoredScene) -> None:
        self.ax = ax
        self.monitored_scene = monitored_scene
        self.graphs: List[plt.Artist] = []
        self.zorder = 0

    def draw(self):
        self.do_draw()

    @abstractmethod
    def do_draw(self):
        pass

    def update(self, monitored_scene: MonitoredScene) -> List[plt.Artist]:
        return self.do_update(monitored_scene)

    @abstractmethod
    def do_update(self, monitored_scene: MonitoredScene) -> List[plt.Artist]:
        pass

    def reset(self) -> List[plt.Artist]:
        return self.update(self.monitored_scene)
