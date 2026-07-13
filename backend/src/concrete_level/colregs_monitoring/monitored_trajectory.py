from dataclasses import dataclass
from typing import List, Tuple

from concrete_level.colregs_monitoring.colregs_monitor_state import COLREGSMonitorState, COLREGSMonitorStateSet
from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResultMapSet
from concrete_level.colregs_monitoring.colregs_rules.maneuver_suggestions import ManeuverSuggestions
from concrete_level.colregs_monitoring.maneuver import ManeuverStateSet
from concrete_level.colregs_monitoring.situation_context import SituationContext, SituationContextSet
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories


@dataclass(frozen=True)
class MonitoredScene:
    scene: ConcreteScene
    situation_context_set: SituationContextSet
    colregs_state_set: COLREGSMonitorStateSet
    maneuver_state_set: ManeuverStateSet
    timestamp: int


@dataclass(frozen=True)
class MonitoredSceneWithResults:
    monitored_scene: MonitoredScene
    monitor_result_map_set: COLREGSRuleResultMapSet
    maneuver_suggestions: ManeuverSuggestions

    @property
    def scene(self) -> ConcreteScene:
        return self.monitored_scene.scene

    @property
    def situation_context_set(self) -> SituationContextSet:
        return self.monitored_scene.situation_context_set

    @property
    def colregs_state_set(self) -> COLREGSMonitorStateSet:
        return self.monitored_scene.colregs_state_set

    @property
    def maneuver_state_set(self) -> ManeuverStateSet:
        return self.monitored_scene.maneuver_state_set

    @property
    def timestamp(self) -> int:
        return self.monitored_scene.timestamp

    @property
    def colregs_states_with_context(self) -> List[Tuple[SituationContext, COLREGSMonitorState]]:
        return list(zip(self.situation_context_set.values(), self.colregs_state_set.values()))


class MonitoredTrajectory:
    scene_path: List[ConcreteScene]
    situation_context_set_path: List[SituationContextSet]
    colregs_state_set_path: List[COLREGSMonitorStateSet]
    maneuver_state_set_path: List[ManeuverStateSet]
    monitor_result_map_set_path: List[COLREGSRuleResultMapSet]
    maneuver_suggestions_path: List[ManeuverSuggestions]
    time_step: int

    def __init__(self, time_step: int) -> None:
        self.time_step = time_step
        self.scene_path = []
        self.situation_context_set_path = []
        self.colregs_state_set_path = []
        self.maneuver_state_set_path = []
        self.monitor_result_map_set_path = []
        self.maneuver_suggestions_path = []

    def __len__(self):
        return len(self.scene_path)

    def __iter__(self):
        return iter(self.scene_path)

    def __repr__(self):
        return f"{self.__class__.__name__}(time_step={self.time_step}, trajectory={self.scene_path})"

    @property
    def timespan(self) -> int:
        return (len(self) - 1) * self.time_step

    @property
    def initial_monitored_scene_with_results(self) -> MonitoredSceneWithResults:
        return MonitoredSceneWithResults(
            monitored_scene=MonitoredScene(
                scene=self.first_scene,
                situation_context_set=self.first_situation_context_set,
                colregs_state_set=self.first_colregs_state_set,
                maneuver_state_set=self.first_maneuver_state_set,
                timestamp=0,
            ),
            monitor_result_map_set=self.first_monitor_result_map_set,
            maneuver_suggestions=self.first_maneuver_suggestions,
        )

    @property
    def last_monitored_scene_with_results(self) -> MonitoredSceneWithResults:
        return MonitoredSceneWithResults(
            monitored_scene=MonitoredScene(
                scene=self.last_scene,
                situation_context_set=self.last_situation_context_set,
                colregs_state_set=self.last_colregs_state_set,
                maneuver_state_set=self.last_maneuver_state_set,
                timestamp=self.timespan,
            ),
            monitor_result_map_set=self.last_monitor_result_map_set,
            maneuver_suggestions=self.last_maneuver_suggestions,
        )

    @property
    def last_maneuver_state_set(self) -> ManeuverStateSet:
        return self.maneuver_state_set_path[-1]

    @property
    def last_monitor_result_map_set(self) -> COLREGSRuleResultMapSet:
        return self.monitor_result_map_set_path[-1]

    @property
    def last_colregs_state_set(self) -> COLREGSMonitorStateSet:
        return self.colregs_state_set_path[-1]

    @property
    def last_scene(self) -> ConcreteScene:
        return self.scene_path[-1]

    @property
    def first_scene(self) -> ConcreteScene:
        return self.scene_path[0]

    @property
    def first_colregs_state_set(self) -> COLREGSMonitorStateSet:
        return self.colregs_state_set_path[0]

    @property
    def first_maneuver_state_set(self) -> ManeuverStateSet:
        return self.maneuver_state_set_path[0]

    @property
    def first_monitor_result_map_set(self) -> COLREGSRuleResultMapSet:
        return self.monitor_result_map_set_path[0]

    @property
    def first_maneuver_suggestions(self) -> ManeuverSuggestions:
        return self.maneuver_suggestions_path[0]

    @property
    def last_maneuver_suggestions(self) -> ManeuverSuggestions:
        return self.maneuver_suggestions_path[-1]

    @property
    def first_situation_context_set(self) -> SituationContextSet:
        return self.situation_context_set_path[0]

    @property
    def last_situation_context_set(self) -> SituationContextSet:
        return self.situation_context_set_path[-1]

    @property
    def actors(self) -> List[ConcreteActor]:
        if len(self) == 0:
            return []
        return list(self.initial_monitored_scene_with_results.scene.actors)

    def get_monitored_scene_by_time(self, timestamp: int) -> MonitoredSceneWithResults:
        index = timestamp // self.time_step
        return MonitoredSceneWithResults(
            monitored_scene=MonitoredScene(
                scene=self.scene_path[index],
                situation_context_set=self.situation_context_set_path[index],
                colregs_state_set=self.colregs_state_set_path[index],
                maneuver_state_set=self.maneuver_state_set_path[index],
                timestamp=index * self.time_step,
            ),
            monitor_result_map_set=self.monitor_result_map_set_path[index],
            maneuver_suggestions=self.maneuver_suggestions_path[index],
        )

    def add_scene(self, monitored_scene_with_results: MonitoredSceneWithResults):
        self.scene_path.append(monitored_scene_with_results.scene)
        self.situation_context_set_path.append(monitored_scene_with_results.situation_context_set)
        self.colregs_state_set_path.append(monitored_scene_with_results.colregs_state_set)
        self.maneuver_state_set_path.append(monitored_scene_with_results.maneuver_state_set)
        self.maneuver_suggestions_path.append(monitored_scene_with_results.maneuver_suggestions)
        self.monitor_result_map_set_path.append(monitored_scene_with_results.monitor_result_map_set)

    @property
    def trajectories(self) -> Trajectories:
        return Trajectories(scene_list=self.scene_path, time_step=self.time_step)
