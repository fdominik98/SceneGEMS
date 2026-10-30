from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from concrete_level.colregs_monitoring.colregs_monitor_state import COLREGSMonitorState, COLREGSMonitorStateSet
from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult, COLREGSRuleResultMapSet
from concrete_level.colregs_monitoring.colregs_rules.colregs_rules import COLREGSRule
from concrete_level.colregs_monitoring.colregs_rules.maneuver_suggestions import ManeuverSuggestions
from concrete_level.colregs_monitoring.maneuver import ManeuverStateSet
from concrete_level.colregs_monitoring.situation_context import SituationContext, SituationContextSet
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.relation import Relation
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
    # The first timestamp each rule was FAILED at under each relation, over the whole
    # monitored run up to this scene. Keyed by relation too: a vessel give-way in two
    # encounters has the same Rule 16 in both, judged separately. A failure is sticky only
    # while its rule stays active (a rule that turns active again restarts as unknown), so
    # this is history the result maps alone do not keep. It lets a viewer that missed or
    # thinned frames still place the failure. Never mutated: a step that adds a failure
    # builds a new dict.
    first_failed_at: Dict[Tuple[Relation, COLREGSRule], int] = field(default_factory=dict)

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
        # Pair by relation, not by iteration order. Zipping the two .values() views
        # happens to line up today but silently mispairs a context with another
        # relation's state as soon as one of the maps gains or loses a relation.
        return [(context, self.colregs_state_set[relation]) for relation, context in self.situation_context_set.items() if relation in self.colregs_state_set]


def record_first_failures(previous: Dict[Tuple[Relation, COLREGSRule], int], results: COLREGSRuleResultMapSet, timestamp: int) -> Dict[Tuple[Relation, COLREGSRule], int]:
    """``previous`` plus the rules FAILED in ``results`` for the first time, at ``timestamp``.

    Returns ``previous`` itself when nothing new failed, so the common step allocates nothing.
    """
    updated = None
    for relation, result_map in results.items():
        for rule, result in result_map.items():
            if result is COLREGSRuleResult.FAILED and (relation, rule) not in previous:
                if updated is None:
                    updated = dict(previous)
                updated[(relation, rule)] = timestamp
    return previous if updated is None else updated


class MonitoredTrajectory:
    scene_path: List[ConcreteScene]
    situation_context_set_path: List[SituationContextSet]
    colregs_state_set_path: List[COLREGSMonitorStateSet]
    maneuver_state_set_path: List[ManeuverStateSet]
    monitor_result_map_set_path: List[COLREGSRuleResultMapSet]
    maneuver_suggestions_path: List[ManeuverSuggestions]
    first_failed_at_path: List[Dict[Tuple[Relation, COLREGSRule], int]]
    time_step: int

    def __init__(self, time_step: int) -> None:
        self.time_step = time_step
        self.scene_path = []
        self.situation_context_set_path = []
        self.colregs_state_set_path = []
        self.maneuver_state_set_path = []
        self.monitor_result_map_set_path = []
        self.maneuver_suggestions_path = []
        self.first_failed_at_path = []

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
            first_failed_at=self.first_failed_at_path[0],
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
            first_failed_at=self.first_failed_at_path[-1],
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

    def get_monitored_scene_by_index(self, index: int) -> MonitoredSceneWithResults:
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
            first_failed_at=self.first_failed_at_path[index],
        )

    @property
    def monitored_scenes_with_results(self) -> List[MonitoredSceneWithResults]:
        """Every scene on the path, paired with the monitor output recorded for it."""
        return [self.get_monitored_scene_by_index(index) for index in range(len(self))]

    def add_scene(self, monitored_scene_with_results: MonitoredSceneWithResults):
        self.scene_path.append(monitored_scene_with_results.scene)
        self.situation_context_set_path.append(monitored_scene_with_results.situation_context_set)
        self.colregs_state_set_path.append(monitored_scene_with_results.colregs_state_set)
        self.maneuver_state_set_path.append(monitored_scene_with_results.maneuver_state_set)
        self.maneuver_suggestions_path.append(monitored_scene_with_results.maneuver_suggestions)
        self.monitor_result_map_set_path.append(monitored_scene_with_results.monitor_result_map_set)
        self.first_failed_at_path.append(monitored_scene_with_results.first_failed_at)

    @property
    def trajectories(self) -> Trajectories:
        return Trajectories(scene_list=self.scene_path, time_step=self.time_step)
