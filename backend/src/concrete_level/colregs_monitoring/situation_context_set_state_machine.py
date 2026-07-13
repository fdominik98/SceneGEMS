from typing import Dict

from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.colregs_monitoring.situation_context import SituationContext, SituationContextSet
from concrete_level.colregs_monitoring.situation_context_state_machine import SituationContextStateMachine
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.relation import Relation
from utils.colregs_approximations import COLREGSConstraints
from utils.math_utils import Direction


class SituationContextSetStateMachine:
    """Static class for monitoring situation contexts across all vessel pairs."""

    @staticmethod
    def create_initial_state_set(scene: ConcreteScene, start_timestamp: int, colregs_constants: COLREGSConstraints) -> SituationContextSet:
        """Create the initial situation context set for all vessel pairs."""
        situation_contexts = {}
        for actor1, actor2 in scene.all_vessel_pair_combinations_with_obstacles:
            pair_relation = Relation.canonical(actor1, actor2)
            situation_context = SituationContextStateMachine.create_initial(scene, actor1, actor2, start_timestamp, colregs_constants)
            situation_contexts[pair_relation] = situation_context
        return SituationContextSetStateMachine.from_situation_contexts(situation_contexts, scene)

    @staticmethod
    def step(
        current_monitored_scene: MonitoredScene,
        next_scene: ConcreteScene,
        next_timestamp: int,
        colregs_constants: COLREGSConstraints,
    ) -> SituationContextSet:
        """Calculate the next situation context set without mutating the current one."""
        current_situation_context_set = current_monitored_scene.situation_context_set
        next_situation_contexts = {}
        for relation in current_situation_context_set.relations:
            current_context = current_situation_context_set[relation]
            next_situation_contexts[relation] = SituationContextStateMachine.step(current_context, next_scene, next_timestamp, colregs_constants)
        return SituationContextSetStateMachine.from_situation_contexts(next_situation_contexts, next_scene)

    @staticmethod
    def from_situation_contexts(situation_contexts: Dict[Relation, SituationContext], scene: ConcreteScene) -> SituationContextSet:
        copied_situation_contexts = dict(situation_contexts)
        actors_have_to_give_way: Dict[ConcreteActor, bool] = {actor: SituationContextSet.get_actor_has_to_give_way(actor, copied_situation_contexts) for actor in scene.vessels}
        actors_avoidance_directions: Dict[ConcreteActor, Direction] = {actor: SituationContextSet.get_actor_avoidance_direction(actor, copied_situation_contexts) for actor in scene.vessels}
        return SituationContextSet(copied_situation_contexts, actors_have_to_give_way=actors_have_to_give_way, actors_avoidance_directions=actors_avoidance_directions)
