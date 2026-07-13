import random
from typing import Dict, Set, Tuple

from concrete_level.colregs_monitoring.maneuver import MANEUVER_TYPE_HEADING_CHANGE_MAP, ManeuverType
from concrete_level.models.concrete_actors import ConcreteActor
from utils.colregs_approximations import COLREGSConstraints
from utils.interval import Interval


class ManeuverSuggestions(Dict[ConcreteActor, Set[ManeuverType]]):
    def __init__(self, data: Dict[ConcreteActor, Set[ManeuverType]] = {}, info_data: Dict[ConcreteActor, str] = {}):
        super().__init__(data)
        self.info_data = info_data

    def merge(self, other: "ManeuverSuggestions") -> "ManeuverSuggestions":
        # Merge the suggested maneuvers by taking the intersection of the sets for those actors that are present in both dictionaries
        # for the actors that are not present in both dictionaries, take the set where the actor is present
        merged_suggestions = ManeuverSuggestions()
        info_data: Dict[ConcreteActor, str] = {}
        for actor in self.keys() | other.keys():
            info_text = ""
            if actor in self:
                info_text += self.info_data.get(actor, "")
                if actor in other:
                    merged_suggestions[actor] = self[actor].intersection(other[actor])
                    info_text += f"\n{other.info_data.get(actor, '')}"
                else:
                    merged_suggestions[actor] = self[actor]
            else:
                merged_suggestions[actor] = other[actor]
                info_text += other.info_data.get(actor, "")
            info_data[actor] = info_text
        merged_suggestions.info_data = info_data
        return merged_suggestions

    def __str__(self) -> str:
        return "\n".join([f"{actor.name}: {maneuvers}" for actor, maneuvers in self.items()])

    def __repr__(self) -> str:
        return str(self)

    def get_random_maneuver(self, actor: ConcreteActor) -> ManeuverType:
        maneuver_list = list(self[actor].difference({ManeuverType.UNDETECTED}))
        if len(maneuver_list) == 0:
            print(f"WARNING:No maneuvers available for {actor.name}")
            return random.choice(list(ManeuverType.all_detected_maneuver_types()))
        return random.choice(maneuver_list)

    def get_all_maneuvers(self, actor: ConcreteActor) -> Set[ManeuverType]:
        if actor not in self:
            # print(f"WARNING:{actor.name} is not in the maneuver suggestions")
            return ManeuverType.all_detected_maneuver_types()
        return self[actor].difference({ManeuverType.UNDETECTED})

    def get_info(self, actor: ConcreteActor) -> str:
        if actor not in self:
            # print(f"WARNING:{actor.name} is not in the maneuver suggestions")
            return ""
        return self.info_data[actor]

    def union(self, other: "ManeuverSuggestions") -> "ManeuverSuggestions":
        return ManeuverSuggestions({actor: self.get(actor, set()).union(other.get(actor, set())) for actor in self.keys() | other.keys()})

    def get_suggested_range_of_heading_change(self, actor: ConcreteActor, dt: float, colregs_constants: COLREGSConstraints) -> Interval:
        # return the union of the suggested ranges of the maneuvers for the actor
        max_heading_step = actor.get_max_heading_step(dt)
        intervals = [
            MANEUVER_TYPE_HEADING_CHANGE_MAP[maneuver](max_heading_step, colregs_constants)
            for maneuver in self.get_all_maneuvers(actor)
        ]

        return Interval(*intervals)
