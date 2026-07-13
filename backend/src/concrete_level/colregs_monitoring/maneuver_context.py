from typing import Dict, List

from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.relation import Relation
from utils.colregs_approximations import COLREGSConstraints


class ManeuverContext:
    def __init__(self, vessel: ConcreteVessel, start_scene: ConcreteScene, start_timestamp: int, colregs_constants: COLREGSConstraints):
        self.vessel = vessel
        self.relation = Relation(vessel, vessel)
        self.start_scene = start_scene
        self.start_timestamp = start_timestamp
        self.colregs_constants = colregs_constants


class ManeuverContextSet(Dict[Relation, ManeuverContext]):
    @staticmethod
    def from_scene(scene: ConcreteScene, start_timestamp: int, colregs_constants: COLREGSConstraints) -> "ManeuverContextSet":
        maneuver_context_set = ManeuverContextSet()
        for vessel in scene.vessels:
            maneuver_context = ManeuverContext(vessel, scene, start_timestamp, colregs_constants)
            maneuver_context_set[maneuver_context.relation] = maneuver_context
        return maneuver_context_set

    @property
    def vessels(self) -> List[ConcreteVessel]:
        return [context.vessel for context in self.values()]

    @property
    def relations(self) -> List[Relation]:
        return list(self.keys())
