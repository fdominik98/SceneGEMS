"""Serialization of frames and monitor results for the frontend."""

import dataclasses
import json
import os
import subprocess
import sys

import numpy as np
import pytest

from concrete_level.colregs_monitoring.colregs_monitor_runtime import ColregsMonitorRuntime, MonitoringTask
from scenegems_tool.gateway.serialization import _safety_domain_payload, _to_json_safe, serialize_frame, serialize_monitored_frame
from tests.scenegems_tool.vessel_stack.scenarios import encounter_trajectories
from utils.colregs_approximations import COLREGSConstraints
from utils.file_system_utils import COLREGS_CONSTANTS_FOLDER
from utils.safety_domains import CircularSafetyDomain, EllipticalSafetyDomain, RectangularSafetyDomain


class TestJsonSafe:
    def test_numpy_scalars_become_python_numbers(self):
        value = _to_json_safe({"a": np.float64(1.5), "b": np.int64(2), "c": np.bool_(True)})
        assert value == {"a": 1.5, "b": 2, "c": True}
        assert type(value["a"]) is float and type(value["b"]) is int and type(value["c"]) is bool
        json.dumps(value)

    def test_containers_are_converted_recursively(self):
        value = _to_json_safe({"list": [np.float32(1.0), (np.int32(2),)], "set": {np.int8(3)}})
        assert value == {"list": [1.0, [2]], "set": [3]}

    def test_keys_become_strings(self):
        assert _to_json_safe({1: "a"}) == {"1": "a"}

    def test_plain_values_pass_through(self):
        assert _to_json_safe("text") == "text"
        assert _to_json_safe(None) is None


class TestSafetyDomainPayload:
    def test_circle(self):
        payload = _safety_domain_payload(CircularSafetyDomain(np.array([1.0, 2.0]), 0.5, 30.0))
        assert payload == {"center": [1.0, 2.0], "heading": 0.5, "shape": "circle", "radius": 30.0}

    def test_ellipse(self):
        payload = _safety_domain_payload(EllipticalSafetyDomain(np.array([0.0, 0.0]), 0.0, 40.0, 20.0))
        assert (payload["shape"], payload["a"], payload["b"]) == ("ellipse", 40.0, 20.0)

    def test_rectangle(self):
        payload = _safety_domain_payload(RectangularSafetyDomain(np.array([0.0, 0.0]), 0.0, 40.0, 20.0))
        assert (payload["shape"], payload["a"], payload["b"]) == ("rectangle", 40.0, 20.0)

    def test_payloads_are_json_serializable(self):
        json.dumps(_safety_domain_payload(CircularSafetyDomain(np.array([1.0, 2.0]), 0.5, 30.0)))


class TestFrame:
    @pytest.fixture(scope="module")
    def scene(self):
        return encounter_trajectories("head_on", 10).initial_scene

    def test_frame_has_the_fields_the_frontend_reads(self, scene):
        frame = serialize_frame("s1", scene, 3, 1)
        assert (frame["scenarioId"], frame["timestamp"], frame["timeStep"]) == ("s1", 3, 1)
        assert set(frame) >= {"actors", "statesByActorId", "situationContexts", "colregsStates", "ruleResults", "maneuverStates", "metrics"}

    def test_actors_are_listed_with_their_dimensions_and_limits(self, scene):
        frame = serialize_frame("s1", scene, 0, 1)
        own = next(actor for actor in frame["actors"] if actor["isOwnShip"])
        assert own["id"] == "0"
        assert own["length"] == 30.0 and own["safetyRadius"] == 120.0
        assert own["maxSpeed"] == pytest.approx(20.57778)
        assert {"rudderMass", "propellerDiameter", "motorLength"} <= set(own)
        assert sum(actor["isOwnShip"] for actor in frame["actors"]) == 1

    def test_states_are_keyed_by_actor_id(self, scene):
        states = serialize_frame("s1", scene, 0, 1)["statesByActorId"]
        assert states["0"] == {"x": 0.0, "y": 0.0, "speed": 8.0, "heading": 0.0}
        assert states["1"]["x"] == 6000.0

    def test_frame_is_json_serializable(self, scene):
        json.dumps(serialize_frame("s1", scene, 0, 1))


class TestMonitoredFrame:
    @pytest.fixture(scope="module")
    def monitored(self):
        with open(os.path.join(COLREGS_CONSTANTS_FOLDER, "general_maritime_constants.yaml"), encoding="utf-8") as file:
            constants = COLREGSConstraints.from_file_content(file.read())
        trajectories = encounter_trajectories("head_on", 400)
        runtime = ColregsMonitorRuntime(constants)
        results = []
        for index, scene in enumerate(trajectories.scene_list):
            runtime.add_task(MonitoringTask(scene=scene, scene_timestamp=index, time_step=1))
            results.extend(runtime.monitor_current_tasks())
        return results

    def test_every_scene_is_monitored(self, monitored):
        assert len(monitored) == 401

    def test_frame_combines_the_scene_and_the_monitor_payload(self, monitored):
        frame = serialize_monitored_frame("s1", monitored[200], 200, 1)
        assert frame["timestamp"] == 200
        assert set(frame["statesByActorId"]) == {"0", "1"}
        assert frame["situationContexts"], "a head-on encounter at 200 s has a situation context"

    def test_frame_is_json_serializable(self, monitored):
        json.dumps(serialize_monitored_frame("s1", monitored[200], 200, 1))

    def test_serialization_is_deterministic(self, monitored):
        first = json.dumps(serialize_monitored_frame("s1", monitored[300], 300, 1), sort_keys=True)
        second = json.dumps(serialize_monitored_frame("s1", monitored[300], 300, 1), sort_keys=True)
        assert first == second


class TestEncounterRules:
    @pytest.fixture(scope="class")
    def frame(self):
        from tests.concrete_level.colregs_monitoring.monitor_runs import monitored_run

        return serialize_monitored_frame("s1", monitored_run((3600.0, -3600.0), 60)[40], 40, 1)

    def test_the_stand_on_vessel_has_its_rule_17_in_the_encounter(self, frame):
        """Per-vessel rules live under the vessel related to itself, which the frames left out."""
        (encounter,) = frame["ruleResults"]
        assert ("17", "1") in {(rule["ruleNumber"], rule["subjectActorId"]) for rule in encounter["rules"]}
        assert {"Rule 8: Readily Apparent Course Change"} <= {rule["name"] for rule in encounter["rules"]}

    def test_rules_are_listed_by_kind_number_and_vessel(self, frame):
        (encounter,) = frame["ruleResults"]
        keys = [(rule["kind"] != "rule", int(rule["ruleNumber"] or 10**6), rule["subjectActorName"]) for rule in encounter["rules"]]
        assert keys == sorted(keys)

    def test_the_order_does_not_depend_on_the_hash_seed(self):
        script = (
            "from tests.concrete_level.colregs_monitoring.monitor_runs import monitored_run\n"
            "from scenegems_tool.gateway.serialization import serialize_monitored_frame\n"
            "frame = serialize_monitored_frame('s', monitored_run((3600.0, -3600.0), 60)[40], 40, 1)\n"
            "print([rule['name'] + '/' + str(rule['subjectActorId']) + '/' + rule['ruleId'] for row in frame['ruleResults'] for rule in row['rules']])\n"
            "turned = serialize_monitored_frame('s', monitored_run((3600.0, -3600.0), 120, 30, 30)[60], 60, 1)\n"
            "print([(rule['ruleId'], rule['firstFailedAt']) for row in turned['ruleResults'] for rule in row['rules']])\n"
        )
        outputs = set()
        for seed in ("0", "1", "4242"):
            environment = dict(os.environ, PYTHONHASHSEED=seed)
            outputs.add(subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True, env=environment).stdout)
        assert len(outputs) == 1


def _rules(frame):
    (encounter,) = frame["ruleResults"]
    return {rule["ruleId"]: rule for rule in encounter["rules"]}


@pytest.fixture(scope="module")
def run():
    from tests.concrete_level.colregs_monitoring.monitor_runs import monitored_run

    # the stand-on target turns at 30 s and fails Rule 17 at 31 s
    return monitored_run((3600.0, -3600.0), 120, turn_at=30, turn_s=30)


class TestRuleIdsAndFirstFailures:
    STAND_ON_RULE = "rule:17:stand-on-vessel-keeps-course-and-speed:1-1:1"

    def test_every_rule_has_an_id_unique_in_its_encounter(self, run):
        (encounter,) = serialize_monitored_frame("s", run[40], 40, 1)["ruleResults"]
        ids = [rule["ruleId"] for rule in encounter["rules"]]
        assert len(ids) == len(set(ids)) and self.STAND_ON_RULE in ids

    def test_the_first_frame_lists_every_rule_with_its_id(self, run):
        first, later = _rules(serialize_monitored_frame("s", run[0], 0, 1)), _rules(serialize_monitored_frame("s", run[40], 40, 1))
        assert set(first) == set(later)
        assert {rule["result"] for rule in first.values()} == {"UNKNOWN"}

    def test_first_failed_at_is_none_before_and_the_first_failure_after(self, run):
        assert _rules(serialize_monitored_frame("s", run[20], 20, 1))[self.STAND_ON_RULE]["firstFailedAt"] is None
        for index in (31, 40, 119):
            rule = _rules(serialize_monitored_frame("s", run[index], index, 1))[self.STAND_ON_RULE]
            assert (rule["result"], rule["firstFailedAt"]) == ("FAILED", 31)

    def test_first_failed_at_comes_from_the_monitor_history_not_the_result(self, run):
        """A rule that turned active again restarts unknown; its first failure stays on the wire."""
        monitored = run[20]
        (relation,) = monitored.situation_context_set.keys()
        (rule_16,) = [rule for rule in monitored.monitor_result_map_set[relation] if rule.rule_number == "16"]
        restarted = dataclasses.replace(monitored, first_failed_at={(relation, rule_16): 7})
        rule = _rules(serialize_monitored_frame("s", restarted, 20, 1))[rule_16.rule_id]
        assert (rule["result"], rule["firstFailedAt"]) == ("UNKNOWN", 7)


class TestCpaPositions:
    @staticmethod
    def relation_metrics(own, target):
        from concrete_level.colregs_monitoring.colregs_monitor import COLREGSMonitor
        from concrete_level.models.concrete_scene import ConcreteScene
        from tests.concrete_level.colregs_monitoring.monitor_runs import OWN_SHIP, TARGET, constants

        monitored = COLREGSMonitor(ConcreteScene({OWN_SHIP: own, TARGET: target}), constants()).initial_monitored_scene_with_results
        return serialize_monitored_frame("s", monitored, 0, 1)["metrics"]["relations"]["0->1"]

    def test_both_vessels_at_the_closest_point_of_approach(self):
        from concrete_level.models.actor_state import ActorState

        # the own ship east from the origin, the target north from (3600, -3600), both at 8 m/s: they meet at (3600, 0) after 450 s
        metrics = self.relation_metrics(ActorState(0.0, 0.0, 8.0, 0.0), ActorState(3600.0, -3600.0, 8.0, np.pi / 2))
        assert metrics["tcpa"] == pytest.approx(450.0)
        positions = metrics["cpaPositionsByActorId"]
        assert set(positions) == {"0", "1"}
        for actor_id in ("0", "1"):
            assert (positions[actor_id]["x"], positions[actor_id]["y"]) == (pytest.approx(3600.0), pytest.approx(0.0, abs=1e-6))
        assert metrics["dcpa"] == pytest.approx(np.hypot(positions["1"]["x"] - positions["0"]["x"], positions["1"]["y"] - positions["0"]["y"]), abs=1e-6)

    def test_none_without_relative_motion(self):
        from concrete_level.models.actor_state import ActorState

        assert self.relation_metrics(ActorState(0.0, 0.0, 8.0, 0.0), ActorState(0.0, 500.0, 8.0, 0.0))["cpaPositionsByActorId"] is None

    def test_none_once_the_closest_point_is_behind(self):
        from concrete_level.models.actor_state import ActorState

        metrics = self.relation_metrics(ActorState(0.0, 0.0, 8.0, np.pi), ActorState(1000.0, 0.0, 8.0, 0.0))
        assert metrics["tcpa"] < 0 and metrics["cpaPositionsByActorId"] is None
