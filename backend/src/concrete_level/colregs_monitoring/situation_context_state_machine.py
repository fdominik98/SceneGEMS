from concrete_level.colregs_monitoring.situation_context import COLREGSType, SituationContext, HeadOnSituationContext, OvertakingSituationContext, CrossingFromPortSituationContext, TwoWayCrossingFromPortSituationContext, TwoWayCrossingFromStarboardSituationContext, OtherSituationContext
from concrete_level.models.concrete_actors import ConcreteActor, ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from utils.colregs_approximations import COLREGSConstraints


class SituationContextStateMachine:
    """Static class for monitoring a single vessel-pair situation context."""

    @staticmethod
    def create_initial(
        scene: ConcreteScene,
        actor1: ConcreteActor,
        actor2: ConcreteActor,
        start_timestamp: int,
        colregs_constants: COLREGSConstraints,
    ) -> SituationContext:
        """Create the initial situation context for a vessel pair."""
        return SituationContextStateMachine.get_situation_context(scene, actor1, actor2, start_timestamp, colregs_constants)

    @staticmethod
    def step(
        current_situation_context: SituationContext,
        next_scene: ConcreteScene,
        next_timestamp: int,
        colregs_constants: COLREGSConstraints,
    ) -> SituationContext:
        """Calculate the next situation context without mutating the current one."""
        if current_situation_context.get_actors_passed_each_other(next_scene):
            return OtherSituationContext(current_situation_context.actor1, current_situation_context.actor2, next_scene, next_timestamp, colregs_constants)
        candidate = SituationContextStateMachine.get_situation_context(
            next_scene,
            current_situation_context.actor1,
            current_situation_context.actor2,
            next_timestamp,
            colregs_constants,
        )
        if current_situation_context.situation_type == COLREGSType.OTHER and candidate.situation_type != COLREGSType.OTHER:
            return candidate
        return current_situation_context
    
    
    @staticmethod
    def get_situation_context(scene: ConcreteScene, vessel1: ConcreteActor, vessel2: ConcreteActor, start_timestamp: int, colregs_constants: COLREGSConstraints) -> SituationContext:
        if isinstance(vessel1, ConcreteVessel) and isinstance(vessel2, ConcreteVessel):
            if scene.out_of_visibility_distance(vessel1, vessel2):
                return  OtherSituationContext(vessel1, vessel2, scene, start_timestamp, colregs_constants)
            if scene.in_head_on_cr(vessel1, vessel2, colregs_constants):
                return HeadOnSituationContext(vessel1, vessel2, scene, start_timestamp, colregs_constants)
            elif scene.in_overtaking_cr(vessel1, vessel2, colregs_constants):
                return OvertakingSituationContext(vessel1, vessel2, scene, start_timestamp, colregs_constants)
            elif scene.in_crossing_from_port_cr(vessel1, vessel2, colregs_constants):
                return CrossingFromPortSituationContext(vessel1, vessel2, scene, start_timestamp, colregs_constants)
            elif scene.in_overtaking_cr(vessel2, vessel1, colregs_constants):
                return OvertakingSituationContext(vessel2, vessel1, scene, start_timestamp, colregs_constants)
            elif scene.in_crossing_from_port_cr(vessel2, vessel1, colregs_constants):
                return CrossingFromPortSituationContext(vessel2, vessel1, scene, start_timestamp, colregs_constants)
            elif scene.in_two_way_crossing_from_port_cr(vessel1, vessel2, colregs_constants):
                return TwoWayCrossingFromPortSituationContext(vessel1, vessel2, scene, start_timestamp, colregs_constants)
            elif scene.in_two_way_crossing_from_starboard_cr(vessel1, vessel2, colregs_constants):
                return TwoWayCrossingFromStarboardSituationContext(vessel1, vessel2, scene, start_timestamp, colregs_constants)
        return OtherSituationContext(vessel1, vessel2, scene, start_timestamp, colregs_constants)
