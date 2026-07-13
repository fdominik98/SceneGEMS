import bisect
from dataclasses import dataclass
from typing import List, Optional, Set
from concrete_level.colregs_monitoring.colregs_monitor import COLREGSMonitor
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredSceneWithResults, MonitoredTrajectory
from concrete_level.models.concrete_scene import ConcreteScene
from utils.colregs_approximations import COLREGSConstraints

@dataclass(frozen=True)
class MonitoringTask:
    scene: ConcreteScene
    scene_timestamp: int
    time_step: int
    
    @property
    def is_initial_scene(self) -> bool:
        return self.scene_timestamp == 0
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MonitoringTask):
            return False
        return self.scene_timestamp == other.scene_timestamp and self.time_step == other.time_step and self.scene == other.scene
    
    def __hash__(self) -> int:
        return hash((self.scene_timestamp, self.time_step, self.scene))
    
        
class ColregsMonitorRuntime:
    def __init__(self, colregs_constants: COLREGSConstraints):
        self.colregs_constants = colregs_constants
        self.monitoring_tasks : List[MonitoringTask] = []
        self.monitor : Optional[COLREGSMonitor] = None
        self.monitored_trajectory : Optional[MonitoredTrajectory] = None
        
    @property
    def is_initialized(self) -> bool:
        return self.monitor is not None and self.monitored_trajectory is not None
    
    @property
    def has_tasks(self) -> bool:
        return len(self.monitoring_tasks) > 0

    def add_task(self, task: MonitoringTask):
        ids = [t.scene_timestamp for t in self.monitoring_tasks]
        index = bisect.bisect_left(ids, task.scene_timestamp)
        self.monitoring_tasks.insert(index, task)
        
    def monitor_current_tasks(self) -> List[MonitoredSceneWithResults]:
        if not self.has_tasks:
            return []
        
        if not self.is_initialized and not self.monitoring_tasks[0].is_initial_scene:
            return []
        
        monitored_scenes = []
        
        if not self.is_initialized:
            task = self.monitoring_tasks.pop(0)
            self.monitor = COLREGSMonitor(task.scene, self.colregs_constants)
            self.monitored_trajectory = MonitoredTrajectory(time_step=task.time_step)
            self.monitored_trajectory.add_scene(self.monitor.initial_monitored_scene_with_results)
            monitored_scenes.append(self.monitor.initial_monitored_scene_with_results)
        
        tasks_done : Set[MonitoringTask] = set()
        for task in self.monitoring_tasks:
            if task.scene_timestamp != self.monitored_trajectory.last_monitored_scene_with_results.timestamp + task.time_step:
                continue
            monitored_scene = self.monitor.step(self.monitored_trajectory.last_monitored_scene_with_results, task.scene, task.time_step)
            monitored_scenes.append(monitored_scene)
            self.monitored_trajectory.add_scene(monitored_scene)
            tasks_done.add(task)
        
        self.monitoring_tasks = [task for task in self.monitoring_tasks if task not in tasks_done]
        return monitored_scenes