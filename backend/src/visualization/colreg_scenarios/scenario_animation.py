import threading
import time
from typing import List, Optional

from matplotlib import pyplot as plt
from matplotlib.animation import FuncAnimation

from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene, MonitoredSceneWithResults, MonitoredTrajectory
from visualization.colreg_scenarios.plot_components.plot_component import PlotComponent

# Animation constants
FRAMES_PER_SEC = 30.0
FRAME_DURATION = 1.0 / FRAMES_PER_SEC  # ~0.033 seconds per frame (30 FPS)


class ScenarioAnimation:
    """Simple animation engine that tracks time and fetches scenes based on speed ratio.

    The animation maintains an internal frame counter that increments at a fixed rate
    (30 FPS). The speed_up_ratio determines how fast we progress through the simulation
    data, but does not affect the frame counter itself.

    Real time is tracked using wall-clock time to ensure accuracy regardless of actual
    frame rate achieved by matplotlib.

    Example:
        At 1x speed: 1 second real time = 1 second sim time
        At 60x speed: 1 second real time = 60 seconds sim time
    """

    def __init__(
        self,
        fig: plt.Figure,
        monitored_trajectory: MonitoredTrajectory,
        components: List[PlotComponent],
    ) -> None:
        self.fig = fig
        self.monitored_trajectory = monitored_trajectory
        self.components = components

        # Animation state
        self.__speed_up_value = 40  # Multiplier for how fast we progress through sim data
        self.is_anim_paused = True
        self.anim = None

        # Thread-safe counters
        self.__speed_up_value_lock = threading.Lock()
        self.__frame_counter_lock = threading.Lock()
        self.__current_monitored_scene_lock = threading.Lock()
        self.__current_sim_time_lock = threading.Lock()
        self.__start_time_lock = threading.Lock()
        self.__anim_frame_counter = 0
        self.__current_sim_time = 0
        self.__current_monitored_scene = self.monitored_trajectory.initial_monitored_scene_with_results
        self.__animation_start_time = 0  # Wall-clock time when animation started

        # Initialize
        self.reset()

    # ========== Properties ==========

    @property
    def animation_start_time(self) -> Optional[float]:
        """Wall-clock time when animation started."""
        with self.__start_time_lock:
            return self.__animation_start_time

    def set_animation_start_time(self, new_time: int):
        """Set the wall-clock time when animation started."""
        with self.__start_time_lock:
            self.__animation_start_time = new_time

    def reset_animation_start_time(self):
        """Reset the wall-clock time when animation started."""
        with self.__start_time_lock:
            self.__animation_start_time = None

    @property
    def speed_up_value(self) -> int:
        """Speed up value."""
        with self.__speed_up_value_lock:
            return self.__speed_up_value

    def set_speed_up_value(self, speed_up_value: int):
        """Set the speed up value."""
        with self.__speed_up_value_lock:
            self.__speed_up_value = speed_up_value

    @property
    def anim_frame_counter(self) -> int:
        """Current frame number (increments at FRAMES_PER_SEC rate)."""
        with self.__frame_counter_lock:
            return self.__anim_frame_counter

    @property
    def real_time_passed(self) -> float:
        """Animation time elapsed in seconds based on actual wall-clock time."""
        if self.animation_start_time is None:
            return 0.0
        return time.time() - self.animation_start_time

    @property
    def current_monitored_scene(self) -> MonitoredSceneWithResults:
        """Currently displayed scene."""
        with self.__current_monitored_scene_lock:
            return self.__current_monitored_scene

    @property
    def current_sim_time(self) -> float:
        """Current simulation time."""
        with self.__current_sim_time_lock:
            return self.__current_sim_time

    def set_current_sim_time(self, sim_time: float):
        """Set the current simulation time."""
        with self.__current_sim_time_lock:
            self.__current_sim_time = int(sim_time)

    @property
    def sim_time_count(self) -> str:
        """Display string showing current time and speed."""
        return f"Simulation time: {round(self.current_sim_time)} s, Real time: {round(self.real_time_passed)} s, Speed: {self.speed_up_value}x"

    # ========== Frame Counter Methods ==========

    def increment_anim_frame_time(self):
        """Increment the frame counter by one frame."""
        with self.__frame_counter_lock:
            self.__anim_frame_counter += 1

    def increment_current_sim_time(self):
        """Increment the current simulation time by the speed up value."""
        with self.__current_sim_time_lock:
            self.__current_sim_time += FRAME_DURATION * self.speed_up_value

    def set_frame_counter(self, frame_number: int):
        """Set the frame counter to a specific frame."""
        with self.__frame_counter_lock:
            self.__anim_frame_counter = max(0, frame_number)

    def reset_frame_counter(self):
        """Reset frame counter and animation start time."""
        self.set_frame_counter(0)
        self.set_current_sim_time(0)
        self.reset_animation_start_time()

    # ========== Scene Methods ==========

    def update_scene_from_sim_time(self, sim_time: float):
        """Fetch and update the current scene based on simulation time."""
        sim_time_int = int(min(sim_time, self.monitored_trajectory.timespan))
        with self.__current_monitored_scene_lock:
            self.__current_monitored_scene = self.monitored_trajectory.get_monitored_scene_by_time(sim_time_int)

    def update_monitored_scene(self):
        """Update the current scene based on current sim_time_passed."""
        self.update_scene_from_sim_time(self.current_sim_time)

    # ========== Time Control Methods ==========

    def reset(self):
        """Reset animation to the beginning."""
        self.reset_frame_counter()
        self.update_scene_from_sim_time(0)
        self.is_anim_paused = True

    # ========== Animation Control ==========

    def start(self):
        """Start the matplotlib animation."""
        self.anim = FuncAnimation(
            self.fig,
            self._update_graphs,
            self._animation_generator,
            init_func=self._init_animation,
            blit=True,
            interval=int(FRAME_DURATION * 1000),  # milliseconds between frames
            cache_frame_data=False,
        )

    def _animation_generator(self):
        """Generator that yields scenes for each frame of animation."""
        while self.current_sim_time < self.monitored_trajectory.timespan:
            if not self.is_anim_paused:
                self.update_monitored_scene()
                self.increment_anim_frame_time()
                self.increment_current_sim_time()
            yield self.current_monitored_scene.monitored_scene

    def _update_graphs(self, monitored_scene: MonitoredScene):
        """Update all plot components with the current scene."""
        return [graph for component in self.components for graph in component.update(monitored_scene) if graph.get_visible()]

    def _init_animation(self):
        """Initialize animation (called by FuncAnimation)."""
        return [graph for component in self.components for graph in component.reset()]

    def toggle_anim(self, event):
        """Handle keyboard events for animation control."""
        if event.key == "down":
            self.reset()
            print("Animation reset")
        elif event.key == "up":
            if self.is_anim_paused:
                if self.anim is None:
                    self.start()
                # Start the wall-clock timer when animation starts
                if self.animation_start_time is None:
                    self.set_animation_start_time(time.time())
                self.is_anim_paused = False
                print("Animation started")
            else:
                self.is_anim_paused = True
                print("Animation paused")
