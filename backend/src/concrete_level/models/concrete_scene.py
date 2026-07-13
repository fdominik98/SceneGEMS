from dataclasses import dataclass, field
from itertools import combinations, product
from typing import Any, Dict, List, Optional, Set, Tuple, Type

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor, ConcreteStaticObstacle, ConcreteVessel
from concrete_level.models.relation import Relation
from logical_level.constraint_satisfaction.assignments import Assignments
from logical_level.constraint_satisfaction.evaluation_cache import EvaluationCache, GeometricProperties
from logical_level.models.actor_variable import ActorVariable
from logical_level.models.relation_constraints_concept.literals import InBowSectorOf, InSternSectorOf, LowTCPA, OnCollisionCourse, OutVis
from logical_level.models.relation_constraints_concept.predicates import (
    InCrossingFromPortCR,
    InHeadOnCR,
    InOvertakingToPortCR,
    InOvertakingToStarboardCR,
    InTwoWayCrossingFromPortCR,
    InTwoWayCrossingFromStarboardCR,
)
from utils.colregs_approximations import COLREGSConstraints
from utils.safety_domains import DomainCollection
from utils.serializable import Serializable


@dataclass(frozen=True)
class ConcreteScene(Serializable):
    _data: Dict[ConcreteActor, ActorState]
    dcpa: Optional[float] = None
    tcpa: Optional[float] = None
    danger_sector: Optional[float] = None
    proximity_index: Optional[float] = None

    first_level_hash: Optional[int] = None
    second_level_hash: Optional[int] = None
    is_relevant_by_fec: Optional[bool] = None
    is_relevant_by_fsm: Optional[bool] = None
    is_ambiguous_by_fec: Optional[bool] = None
    is_ambiguous_by_fsm: Optional[bool] = None

    vars: Dict[ConcreteActor, ActorVariable] = field(init=False, default_factory=dict)
    assignments: Assignments = field(init=False, default_factory=Assignments)
    evaluation_cache: EvaluationCache = field(init=False, default_factory=EvaluationCache)

    def __post_init__(self):
        # Convert _data to dict first
        object.__setattr__(self, "_data", dict(self._data))

        # Set up logical variables, assignments, and evaluation cache
        vars = {a: a.logical_variable for a in self.actors}
        assignments = Assignments(list(vars.values())).update_from_individual(self.individual)
        evaluation_cache = EvaluationCache(assignments)
        object.__setattr__(self, "vars", vars)
        object.__setattr__(self, "assignments", assignments)
        object.__setattr__(self, "evaluation_cache", evaluation_cache)

    def __hash__(self):
        # Use only primitive sortable values so hashing does not depend on ConcreteActor ordering.
        data_items = tuple(
            sorted(
                (
                    actor.id,
                    actor.is_vessel,
                    actor.type,
                    actor.length,
                    actor.breadth,
                    actor.safety_radius,
                    state.x,
                    state.y,
                    state.speed,
                    state.heading,
                )
                for actor, state in self._data.items()
            )
        )

        # Include all the optional immutable fields in the hash
        return hash(
            (
                data_items,
                self.dcpa,
                self.tcpa,
                self.danger_sector,
                self.proximity_index,
                self.first_level_hash,
                self.second_level_hash,
                self.is_relevant_by_fec,
                self.is_relevant_by_fsm,
                self.is_ambiguous_by_fec,
                self.is_ambiguous_by_fsm,
            )
        )

    @property
    def has_risk_metrics(self):
        return all(
            value is not None
            for value in [
                self.dcpa,
                self.tcpa,
                self.danger_sector,
                self.proximity_index,
            ]
        )

    @property
    def has_functional_hash(self):
        return all(
            value is not None
            for value in [
                self.first_level_hash,
                self.second_level_hash,
                self.is_relevant_by_fec,
                self.is_relevant_by_fsm,
                self.is_ambiguous_by_fec,
                self.is_ambiguous_by_fsm,
            ]
        )

    def __getitem__(self, key):
        return self._data[key]

    @property
    def actors(self) -> List[ConcreteActor]:
        return [actor for actor, _ in self.sorted_actor_states]

    @property
    def vessels(self) -> List[ConcreteVessel]:
        return [actor for actor, _ in self.sorted_actor_states if actor.is_vessel]

    @property
    def obstacles(self) -> List[ConcreteStaticObstacle]:
        return [actor for actor, _ in self.sorted_actor_states if not actor.is_vessel]

    @property
    def all_vessel_pair_combinations_with_obstacles(self) -> Set[Relation]:
        return self.all_vessel_pair_combinations.union({Relation(prod[0], prod[1]) for prod in set(product(self.vessels, self.obstacles))})

    @property
    def all_vessel_pair_combinations(self) -> Set[Relation]:
        return {Relation(ai, aj) for ai, aj in combinations(self.vessels, 2)}

    @property
    def os_ts_pairs(self) -> Set[Relation]:
        return {Relation(self.os, ts) for ts in self.ts_vessels}

    @property
    def actor_states(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    @property
    def sorted_actor_states(self):
        return sorted(self.items(), key=lambda item: item[0].id)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __len__(self):
        return len(self._data)

    def __iter__(self):
        return iter(self._data)

    def __repr__(self):
        return f"{self.__class__.__name__}({self._data})"

    def as_dict(self) -> Dict[ConcreteActor, ActorState]:
        return self._data

    @property
    def individual(self) -> List[float]:
        individual: List[float] = []
        for actor, state in self.sorted_actor_states:
            if isinstance(actor, ConcreteVessel):
                individual += [
                    state.x,
                    state.y,
                    state.heading,
                    actor.length,
                    state.speed,
                ]
            elif isinstance(actor, ConcreteStaticObstacle):
                individual += [state.x, state.y, actor.safety_radius]
            else:
                raise ValueError("Unsupported actor type.")
        return individual

    @property
    def actor_number(self) -> int:
        return len(self)

    @property
    def vessel_number(self) -> int:
        return len(self.vessels)

    @property
    def obstacle_number(self) -> int:
        return len(self.obstacles)

    @property
    def os(self) -> ConcreteVessel:
        vessel = next((vessel for vessel in self.vessels if vessel.is_os), None)
        if vessel is None:
            raise ValueError("No OS in the scene.")
        return vessel
    
    @property
    def os_state(self) -> ActorState:
        return self[self.os]

    @property
    def ts_vessels(self) -> Set[ConcreteVessel]:
        return {vessel for vessel in self.vessels if not vessel.is_os}

    def on_collision_course(self, actor1: ConcreteActor, actor2: ConcreteActor) -> bool:
        return OnCollisionCourse(self.vars[actor1], self.vars[actor2]).holds(self.evaluation_cache)

    
    def may_collide_anyone(self, actor: ConcreteActor) -> bool:
        for actor2 in self.actors:
            if actor == actor2:
                continue
            if self.on_collision_course(actor2, actor):
                return True
        return False

    def low_tcpa(self, actor1: ConcreteActor, actor2: ConcreteActor, colregs_constants: COLREGSConstraints) -> bool:
        return LowTCPA(self.vars[actor1], self.vars[actor2], colregs_constants).holds(self.evaluation_cache)

    def out_of_visibility_distance(self, actor1: ConcreteActor, actor2: ConcreteActor) -> bool:
        return OutVis(self.vars[actor1], self.vars[actor2]).holds(self.evaluation_cache)

    def in_stern_sector_of(self, actor1: ConcreteActor, actor2: ConcreteActor) -> bool:
        return InSternSectorOf(self.vars[actor1], self.vars[actor2]).holds(self.evaluation_cache)

    def in_bow_sector_of(self, actor1: ConcreteActor, actor2: ConcreteActor) -> bool:
        return InBowSectorOf(self.vars[actor1], self.vars[actor2]).holds(self.evaluation_cache)

    def in_head_on_cr(self, actor1: ConcreteActor, actor2: ConcreteActor, colregs_constants: COLREGSConstraints) -> bool:
        return InHeadOnCR(self.vars[actor1], self.vars[actor2], colregs_constants).holds(self.evaluation_cache)

    def in_overtaking_cr(self, actor1: ConcreteActor, actor2: ConcreteActor, colregs_constants: COLREGSConstraints) -> bool:
        return self.in_overtaking_to_port_cr(actor1, actor2, colregs_constants) or self.in_overtaking_to_starboard_cr(actor1, actor2, colregs_constants)

    def in_overtaking_to_port_cr(self, actor1: ConcreteActor, actor2: ConcreteActor, colregs_constants: COLREGSConstraints) -> bool:
        return InOvertakingToPortCR(self.vars[actor1], self.vars[actor2], colregs_constants).holds(self.evaluation_cache)

    def in_overtaking_to_starboard_cr(self, actor1: ConcreteActor, actor2: ConcreteActor, colregs_constants: COLREGSConstraints) -> bool:
        return InOvertakingToStarboardCR(self.vars[actor1], self.vars[actor2], colregs_constants).holds(self.evaluation_cache)

    def in_crossing_from_port_cr(self, actor1: ConcreteActor, actor2: ConcreteActor, colregs_constants: COLREGSConstraints) -> bool:
        return InCrossingFromPortCR(self.vars[actor1], self.vars[actor2], colregs_constants).holds(self.evaluation_cache)

    def in_two_way_crossing_from_port_cr(self, actor1: ConcreteActor, actor2: ConcreteActor, colregs_constants: COLREGSConstraints) -> bool:
        return InTwoWayCrossingFromPortCR(self.vars[actor1], self.vars[actor2], colregs_constants).holds(self.evaluation_cache)

    def in_two_way_crossing_from_starboard_cr(self, actor1: ConcreteActor, actor2: ConcreteActor, colregs_constants: COLREGSConstraints) -> bool:
        return InTwoWayCrossingFromStarboardCR(self.vars[actor1], self.vars[actor2], colregs_constants).holds(self.evaluation_cache)

    def get_geo_props(self, actor1: ConcreteActor, actor2: ConcreteActor) -> GeometricProperties:
        return self.evaluation_cache.get_props(self.vars[actor1], self.vars[actor2])

    def potential_safety_domains(self, actor1: ConcreteActor, actor2: ConcreteActor) -> Tuple[DomainCollection, DomainCollection]:
        actor1_violates_actor2 = self.get_geo_props(actor1, actor2).domain_violation_times
        actor2_violates_actor1 = self.get_geo_props(actor2, actor1).domain_violation_times
        state1, state2 = self[actor1], self[actor2]
        domain_collection1, domain_collection2 = DomainCollection(), DomainCollection()
        for time in actor1_violates_actor2:
            actor1_position = actor1.simulate(state1, (state1.heading, state1.speed), time).p
            actor2_position = actor2.simulate(state2, (state2.heading, state2.speed), time).p
            domain_collection1.add_domain(actor1_position, state1.heading, actor2.safety_radius)
            domain_collection2.add_domain(actor2_position, state2.heading, actor2.safety_radius)

        for time in actor2_violates_actor1:
            actor1_position = actor1.simulate(state1, (state1.heading, state1.speed), time).p
            actor2_position = actor2.simulate(state2, (state2.heading, state2.speed), time).p
            domain_collection2.add_domain(actor2_position, state2.heading, actor1.safety_radius)
            domain_collection1.add_domain(actor1_position, state1.heading, actor1.safety_radius)

        return domain_collection1, domain_collection2
    
    def get_tcpa(self, actor1: ConcreteActor, actor2: ConcreteActor) -> float:
        return self.evaluation_cache.get_props(self.vars[actor1], self.vars[actor2]).tcpa
    
    def get_dcpa(self, actor1: ConcreteActor, actor2: ConcreteActor) -> float:
        return self.evaluation_cache.get_props(self.vars[actor1], self.vars[actor2]).dcpa

    def to_dict(self):
        result = {}
        for key, value in self.__dict__.items():
            if key == "_data":
                result[key] = [(actor.to_dict(), state.to_dict()) for actor, state in self._data.items()]
            elif key not in ["vars", "assignments", "evaluation_cache"]:  # Handle primitive types
                result[key] = value
        return result

    def get_by_id(self, id: str) -> ConcreteActor:
        vessel = next((actor for actor in self.actors if actor.id == int(id)), None)
        if vessel is None:
            raise ValueError(f"Vessel with id {id} not found in the scene.")
        return vessel

    @classmethod
    def from_dict(cls: Type["ConcreteScene"], data: Dict[str, Any]) -> "ConcreteScene":
        copy_data = data.copy()
        for attr, value in data.items():
            if attr == "_data":
                copy_data[attr] = {ConcreteActor.from_dict(actor): ActorState.from_dict(state) for actor, state in value}

        return ConcreteScene(**copy_data)
