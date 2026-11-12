"""The monitoring document: one monitor node per MonitorImplementation, the rule list checked against the code."""

import ast
from pathlib import Path

from concrete_level.colregs_monitoring.colregs_rules import colregs_rules
from scenegems_tool.persistence.schema import MonitorImplementation
from scenegems_tool.subsystems.monitoring.monitoring_specs import monitoring_document, rule_specs
from utils.file_system_utils import BACKEND_ROOT

SOURCE_ROOT = Path(BACKEND_ROOT) / "src"


def test_every_monitor_implementation_has_a_node_in_the_monitor_lane():
    document = monitoring_document()
    assert {node.id for node in document.nodes if node.lane == "monitor"} == {f"monitoring/{member.value}" for member in MonitorImplementation}


def test_only_the_monitors_that_judge_run_the_engine():
    edges = {(edge.source, edge.target) for edge in monitoring_document().edges}
    assert ("monitoring/post_hoc", "monitoring/monitor_runtime") in edges and ("monitoring/live", "monitoring/monitor_runtime") in edges
    assert not any(source == "monitoring/empty" and target == "monitoring/monitor_runtime" for source, target in edges)


def test_both_monitors_are_judged_by_the_monitoring_pool_and_the_live_one_is_fed_by_the_run():
    document = monitoring_document()
    hosts = {(edge.source, edge.target) for edge in document.edges if edge.target in ("monitoring/post_hoc", "monitoring/live")}
    assert hosts == {("monitoring/mqtt_service", "monitoring/post_hoc"), ("monitoring/mqtt_service", "monitoring/live"), ("monitoring/simulation_job", "monitoring/live")}
    nodes = {node.id: node for node in document.nodes}
    assert nodes["monitoring/simulation_job"].label == "Simulation run" and "monitoring slot" in nodes["monitoring/simulation_job"].description
    assert "waits for an answer only" in nodes["monitoring/live"].description
    assert {node.id for node in document.nodes if node.lane == "host"} == {"monitoring/mqtt_service", "monitoring/simulation_job"}, "no container of its own per job any more"


def test_the_monitoring_pool_says_how_it_runs_a_request():
    [pool] = [node for node in monitoring_document().nodes if node.id == "monitoring/mqtt_service"]
    facts = {fact.key: fact.value for fact in pool.facts}
    assert (pool.label, facts["request"]) == ("Monitoring pool", "monitor-scenario")
    assert "one scenario never run at once" in facts["tasks"] and "slots" in facts["pool"] and "seed" in facts["seed"]
    assert "sensor/monitored-scene" in facts["publishes"] and "sensor/monitor_result" in facts["publishes"] and "queued" in facts["task_states"]


def test_the_rule_list_names_real_rule_classes():
    for rule in rule_specs():
        assert hasattr(colregs_rules, rule.rule_class), rule.rule_class
        assert getattr(colregs_rules, rule.rule_class).__mro__[1] is colregs_rules.COLREGSRule


def test_the_rules_are_those_the_default_rules_instantiate():
    tree = ast.parse((SOURCE_ROOT / "concrete_level/colregs_monitoring/colregs_rules/default_rules.py").read_text(encoding="utf-8"))
    instantiated = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id.endswith(("Rule", "Suggestion"))}
    assert {rule.rule_class for rule in rule_specs()} == instantiated


def test_a_rule_is_checked_by_the_state_of_its_context():
    edges = {(edge.source, edge.target) for edge in monitoring_document().edges}
    assert ("monitoring/situation_context_state", "monitoring/safe_distance") in edges
    assert ("monitoring/maneuver_state", "monitoring/stand_on_course_persistence") in edges


def test_the_rule_titles_are_those_of_the_rule_classes():
    document = {node.id: node for node in monitoring_document().nodes}
    for rule in rule_specs():
        label = document[f"monitoring/{rule.local}"].label
        assert rule.title in label and (rule.number in label)


def test_the_measured_throughput_sits_on_the_engine_and_the_mqtt_service():
    nodes = {node.id: node for node in monitoring_document().nodes}
    assert any(fact.key == "throughput_in_process" and fact.measured for fact in nodes["monitoring/colregs_monitor"].facts)
    assert any(fact.key == "throughput_batch_100" and fact.measured for fact in nodes["monitoring/mqtt_service"].facts)


def test_every_code_location_exists():
    for node in monitoring_document().nodes:
        for fact in node.facts:
            if fact.key == "code":
                assert (SOURCE_ROOT / str(fact.value)).exists(), fact.value
