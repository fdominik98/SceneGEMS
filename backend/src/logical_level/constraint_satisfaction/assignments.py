from typing import Dict, List, Union

import numpy as np

from logical_level.models.actor_variable import ActorVariable
from logical_level.models.values import ActorValues, ObstacleValues, VesselValues


class Assignments(Dict[ActorVariable, ActorValues]):
    def __init__(self, actor_variables: List[ActorVariable] = [], *args, **kwargs):
        super().__init__({}, *args, **kwargs)
        self.actor_variables = actor_variables

    def update_from_individual(self, states: Union[np.ndarray, List[float]]) -> "Assignments":
        if len(states) != sum(len(var) for var in self.actor_variables):
            raise Exception("the variable number is insufficient.")

        index = 0
        for var in self.actor_variables:
            if var.is_vessel:
                self[var] = VesselValues(
                    _x=states[index + 0],
                    _y=states[index + 1],
                    _h=states[index + 2],
                    _l=states[index + 3],
                    _sp=states[index + 4],
                )
            else:
                self[var] = ObstacleValues(_x=states[index + 0], _y=states[index + 1], _r=states[index + 2])
            index += len(var)
        return self
