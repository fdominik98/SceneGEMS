"""
Helpers to build `SimulationFrame` JSON compatible with the frontend `frameSchema`.

Replace `build_stub_frame` with serializers from your `MonitoredTrajectory` / monitor outputs.
"""

from __future__ import annotations

from typing import Any, Dict, List

from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredSceneWithResults
from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.relation import Relation


def _relation_key(relation: Relation) -> str:
    return f"{relation.actor1.id}->{relation.actor2.id}"


def _to_json_safe(value: Any) -> Any:
    """Recursively coerce numpy/object scalars into JSON-serializable primitives."""
    if isinstance(value, dict):
        return {str(k): _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_json_safe(v) for v in value]
    if hasattr(value, "item") and callable(value.item):
        try:
            return _to_json_safe(value.item())
        except Exception:
            pass
    return value


def _actor_bool_map(values: Dict[Any, bool]) -> Dict[str, bool]:
    return {str(actor.id): bool(value) for actor, value in values.items()}


def monitor_payload_from_scene(monitored_scene: MonitoredSceneWithResults) -> Dict[str, Any]:
    situation_contexts: List[Dict[str, Any]] = []
    colregs_states: List[Dict[str, Any]] = []
    rule_results: List[Dict[str, Any]] = []
    maneuver_states: List[Dict[str, Any]] = []

    scene = monitored_scene.scene

    for relation, context in monitored_scene.situation_context_set.items():
        relation_id = _relation_key(relation)
        actor1_id = str(relation.actor1.id)
        actor2_id = str(relation.actor2.id)

        situation_contexts.append(
            {
                "relationId": relation_id,
                "actor1Id": actor1_id,
                "actor2Id": actor2_id,
                "situationType": context.situation_type.name,
                "situationLabel": context.situation_type.custom_name,
                "startTimestamp": context.start_timestamp,
                "avoidanceDirectionByActorId": {
                    actor1_id: context.avoidance_direction(relation.actor1).name,
                    actor2_id: context.avoidance_direction(relation.actor2).name,
                },
                "globalAvoidanceDirectionByActorId": {
                    actor1_id: monitored_scene.situation_context_set.actor_avoidance_direction(relation.actor1).name,
                    actor2_id: monitored_scene.situation_context_set.actor_avoidance_direction(relation.actor2).name,
                },
                "giveWayByActorId": {
                    actor1_id: context.is_give_way_actor(relation.actor1),
                    actor2_id: context.is_give_way_actor(relation.actor2),
                },
                "globalGiveWayByActorId": {
                    actor1_id: monitored_scene.situation_context_set.actor_has_to_give_way(relation.actor1),
                    actor2_id: monitored_scene.situation_context_set.actor_has_to_give_way(relation.actor2),
                },
                "timeSpentInCurrentContext": monitored_scene.timestamp - context.start_timestamp,
            }
        )

        state = monitored_scene.colregs_state_set.get(relation)
        if state is not None:
            colregs_states.append(
                {
                    "relationId": relation_id,
                    "actorsSeeEachOther": state.actors_see_each_other,
                    "actorsPassedEachOther": state.actors_passed_each_other,
                    "actorsViolateSafetyDomain": state.actors_violate_safety_domain,
                    "actorsOnCollisionCourse": state.actors_on_collision_course,
                    "actorsHaveLowTcpa": state.actors_have_low_tcpa,
                    "currentTimestamp": state.current_timestamp,
                    "timeSpentInCurrentContext": state.time_spent_in_current_context,
                    "actorsRightOfStartStateById": _actor_bool_map(state.actors_right_of_start_state),
                    "actorsLeftOfStartStateById": _actor_bool_map(state.actors_left_of_start_state),
                    "actorsHaveBeenInRightManeuverById": _actor_bool_map(state.actors_have_been_in_right_maneuver),
                    "actorsHaveBeenInLeftManeuverById": _actor_bool_map(state.actors_have_been_in_left_maneuver),
                    "actorsPassedPotentialCollisionDomainById": _actor_bool_map(state.actors_passed_potential_collision_domain),
                    "actorsInFrontOfPotentialCollisionDomainById": _actor_bool_map(state.actors_in_front_of_potential_collision_domain),
                }
            )

        relation_rule_result = monitored_scene.monitor_result_map_set.get_result(relation)
        rules = []
        for rule, result in relation_rule_result.items():
            rules.append(
                {
                    "name": rule.name,
                    "description": rule.description,
                    "result": result.name,
                }
            )
        rule_results.append(
            {
                "relationId": relation_id,
                "isFailed": relation_rule_result.is_failed(),
                "failedRuleNames": [rule.name for rule in relation_rule_result.get_failed_rules()],
                "rules": rules,
            }
        )

    for relation, maneuver_state in monitored_scene.maneuver_state_set.items():
        relation_id = _relation_key(relation)
        suggested_maneuvers = sorted(m.name for m in monitored_scene.maneuver_suggestions.get_all_maneuvers(relation.actor1))
        maneuver_states.append(
            {
                "relationId": relation_id,
                "maneuverType": maneuver_state.type.name,
                "previousManeuverType": maneuver_state.previous_maneuver_type.name,
                "maneuverCount": maneuver_state.maneuver_count,
                "startTimestamp": maneuver_state.start_timestamp,
                "currentTimestamp": maneuver_state.current_timestamp,
                "timespan": maneuver_state.timespan,
                "distanceMade": maneuver_state.distance_made,
                "totalDistanceMade": maneuver_state.total_distance_made,
                "justStarted": maneuver_state.just_started,
                "readilyApparentTimePassed": maneuver_state.readily_apparent_time_passed,
                "headingChange": {
                    "detectedDirection": maneuver_state.heading_change.detected_heading_direction,
                    "headingDiffSincePreviousDeg": maneuver_state.heading_change.heading_diff_since_previous_deg,
                    "headingDiffSinceStartDeg": maneuver_state.heading_change.heading_diff_since_start_deg,
                    "headingDiffSinceReadilyApparentTimeDeg": maneuver_state.heading_change.heading_diff_since_readily_apparent_time_deg,
                },
                "speedChange": {
                    "speedDiffSincePrevious": maneuver_state.speed_change.speed_diff_since_previous,
                    "speedDiffSinceStart": maneuver_state.speed_change.speed_diff_since_start,
                    "speedDiffSinceReadilyApparentTime": maneuver_state.speed_change.speed_diff_since_readily_apparent_time,
                },
                "suggestedManeuvers": suggested_maneuvers,
                "suggestionInfo": monitored_scene.maneuver_suggestions.get_info(relation.actor1),
            }
        )

    metrics: Dict[str, Any] = {
        "scene": {
            "dcpa": scene.dcpa,
            "tcpa": scene.tcpa,
            "dangerSector": scene.danger_sector,
            "proximityIndex": scene.proximity_index,
        },
        "relations": {},
    }
    for relation in monitored_scene.situation_context_set.keys():
        props = scene.get_geo_props(relation.actor1, relation.actor2)
        metrics["relations"][_relation_key(relation)] = {
            "distance": props.o_distance,
            "tcpa": props.tcpa,
            "dcpa": props.dcpa,
            "safetyDistance": props.safety_dist,
            "visibilityDistance": props.vis_distance,
        }

    payload = {
        "situationContexts": situation_contexts,
        "colregsStates": colregs_states,
        "ruleResults": rule_results,
        "maneuverStates": maneuver_states,
        "metrics": metrics,
    }
    return _to_json_safe(payload)


def serialize_monitored_frame(scenario_id : str, monitored_scene: MonitoredSceneWithResults, timestamp: int, time_step: int) -> Dict[str, Any]:
    base_frame = serialize_frame(scenario_id=scenario_id, scene=monitored_scene.scene, timestamp=timestamp, time_step=time_step)
    monitor_payload = monitor_payload_from_scene(monitored_scene)
    for key, value in monitor_payload.items():
        base_frame[key] = value
    return base_frame

def serialize_frame(scenario_id : str, scene: ConcreteScene, timestamp: int, time_step: int) -> Dict[str, Any]:
    actors: List[Dict[str, Any]] = []
    states: Dict[str, Dict[str, float]] = {}

    for actor, state in scene.sorted_actor_states:
        actor_id = str(actor.id)
        if isinstance(actor, ConcreteVessel):
            vessel_data = {
                "rudderMass": actor.rudder_mass,
                "rudderLength": actor.rudder_length,
                "rudderWidth": actor.rudder_width,
                "rudderHeight": actor.rudder_height,
                "propellerDiameter": actor.propeller_diameter,
                "thrusterMass": actor.thruster_mass,
                "motorLength": actor.motor_length,
            }
        actors.append(
            {
                "id": actor_id,
                "name": actor.name,
                "type": actor.type,
                "isVessel": actor.is_vessel,
                "isOwnShip": bool(getattr(actor, "is_os", False)),
                "length": actor.length,
                "breadth": actor.breadth,
                "height": actor.height,
                "draft": actor.draft,
                "mass": actor.mass,
                "safetyRadius": actor.safety_radius,
                "maxSpeed": actor.max_speed,
                "maxAngularSpeed": actor.max_angular_speed,
                "maxAcceleration": actor.max_acceleration,
                **vessel_data,
            }
        )
        states[actor_id] = {
            "x": state.x,
            "y": state.y,
            "speed": state.speed,
            "heading": state.heading,
        }

    return {
        "scenarioId": scenario_id,
        "timestamp": timestamp,
        "timeStep": time_step,
        "actors": actors,
        "statesByActorId": states,  
        "situationContexts": [],
        "colregsStates": [],
        "ruleResults": [],
        "maneuverStates": [],
        "metrics": {},
    }