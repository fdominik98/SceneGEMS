"""Architecture description of monitoring: the monitor implementations, the rule engine they run and the rules it checks.

A campaign names a monitor by MonitorImplementation; a new member needs its MonitorSpec in monitor_specs() (the
coverage check fails otherwise). A new rule is one RuleSpec in rule_specs(). Declared values live here, measured
ones in subsystems/measured_capabilities.yaml under the ids "monitoring/<node id>".
"""

from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

from scenegems_tool.architecture.architecture_model import (
    GROUP_CAPABILITY,
    GROUP_PROPERTY,
    KIND_COMPONENT,
    KIND_INTERFACE,
    KIND_ROLE,
    ROLE_SUPPORT,
    ArchitectureDocument,
    Fact,
    Lane,
    MetamodelEdge,
    MetamodelNode,
)
from scenegems_tool.persistence.schema import MonitorImplementation
from scenegems_tool.subsystems.subsystem_spec import MeasuredFacts, check_covers_enum, spec_edge, spec_node

DOCUMENT_ID = "monitoring"
_MONITORING = "concrete_level/colregs_monitoring"

LANE_HOST = "host"
LANE_MONITOR = "monitor"
LANE_ENGINE = "engine"
LANE_RULES = "rules"


def _id(local: str) -> str:
    return f"{DOCUMENT_ID}/{local}"


META_HOST = _id("host")
META_MONITOR = _id("monitor")
META_RUNTIME = _id("monitor_runtime")
META_STATE = _id("state_machine")
META_RULE = _id("rule")
META_RUNS_ON = _id("host_to_monitor")
META_RUNS = _id("monitor_to_runtime")
META_STEPS = _id("runtime_to_state")
META_CHECKS = _id("state_to_rule")


@dataclass(frozen=True)
class MonitorSpec:
    monitor: MonitorImplementation
    label: str
    description: str
    code: str
    hosts: Tuple[str, ...]  # local ids of the hosts it runs in
    engine: bool  # whether it runs the rule engine
    facts: Tuple[Fact, ...] = ()


@dataclass(frozen=True)
class RuleSpec:
    local: str
    rule_class: str
    number: str  # COLREGS rule number with its paragraph ("8(b)", "17(a)(i)"), "" for an advisory suggestion
    title: str
    scope: str  # situation (per vessel pair) or maneuver (per vessel)
    kind: str  # rule | suggestion


def monitor_specs() -> Tuple[MonitorSpec, ...]:
    return (
        MonitorSpec(
            MonitorImplementation.POST_HOC,
            "Post hoc",
            "A monitoring job judges the recorded run after the simulation. The monitor result summary is passed or failed.",
            "scenegems_tool/cluster/worker_node/jobs/monitoring_post_hoc_job.py",
            ("runner_container",),
            True,
            (Fact("early_stop", "Early stop", False, GROUP_CAPABILITY),),
        ),
        MonitorSpec(
            MonitorImplementation.LIVE,
            "Live",
            "The engine runs inside the simulation, step by step, and can stop the run once every rule is decided.",
            "scenegems_tool/cluster/worker_node/jobs/simulation_job.py",
            ("simulation_job", "mqtt_service"),
            True,
            (Fact("early_stop", "Early stop", True, GROUP_CAPABILITY),),
        ),
        MonitorSpec(
            MonitorImplementation.EMPTY,
            "None",
            "Nothing is judged. Every monitor result summary is unmonitored.",
            "scenegems_tool/persistence/schema/campaign_tables.py",
            (),
            False,
            (Fact("early_stop", "Early stop", False, GROUP_CAPABILITY),),
        ),
    )


def rule_specs() -> Tuple[RuleSpec, ...]:
    return (
        RuleSpec("safe_distance", "SafeDistanceRule", "8(d)", "Passing at a Safe Distance", "situation", "rule"),
        RuleSpec("give_way_early_action", "GiveWayEarlyActionRule", "16", "Give-Way Vessel Takes Early and Substantial Action", "situation", "rule"),
        RuleSpec("hold_avoidance_course", "HoldAvoidanceCourseRule", "8(a)", "Give-Way Steering After First Evasive", "situation", "rule"),
        RuleSpec("go_around_collision_domain", "GoAroundCollisionDomainSuggestion", "", "Pass Around the Collision Domain", "situation", "suggestion"),
        RuleSpec("stand_on_course_persistence", "StandOnCoursePersistenceRule", "17(a)(i)", "Stand-On Vessel Keeps Course and Speed", "maneuver", "rule"),
        RuleSpec("readily_apparent_course_change", "ReadilyApparentCourseChangeRule", "8(b)", "Readily Apparent Course Change", "maneuver", "rule"),
        RuleSpec("readily_apparent_speed_change", "ReadilyApparentSpeedChangeRule", "8(b)", "Readily Apparent Speed Change", "maneuver", "rule"),
        RuleSpec("readily_apparent_course_persistence", "ReadilyApparentCoursePersistenceRule", "8(b)", "Course Change Persistence", "maneuver", "rule"),
        RuleSpec("persisting_course_after_course_change", "PersistingCourseAfterCourseChangeRule", "8(b)", "Course Held After the Manoeuvre", "maneuver", "rule"),
        RuleSpec("no_new_situation", "NoNewSituationRule", "8(c)", "No New Situation While Manoeuvring", "maneuver", "rule"),
    )


_HOSTS = (
    (
        "runner_container",
        "Runner container",
        "A monitoring container of its own per monitoring.post_hoc job, so a worker node's slots bound the monitors that run at once.",
        "scenegems_tool/cluster/worker_node/jobs/runner_container.py",
        "cluster",
    ),
    (
        "simulation_job",
        "Simulation job",
        "The simulation job: the engine steps with the simulation, and on the kinematic layer the run ends early once every rule is decided.",
        "scenegems_tool/cluster/worker_node/jobs/simulation_job.py",
        "cluster",
    ),
    (
        "mqtt_service",
        "MQTT monitor service",
        "The workbench's monitoring worker: scenes arrive over MQTT in batches, monitored frames go back. Heartbeat and task acknowledgement every second.",
        "scenegems_tool/subsystems/monitoring/monitoring_worker.py",
        "workbench",
    ),
)

# The four state machines the engine steps, in the order COLREGSMonitor.step runs them, with the module that holds each.
_STATE_MACHINES = (
    ("situation_context_state", "Situation context", "Classifies every vessel pair: head-on, crossing, overtaking or other.", f"{_MONITORING}/situation_context_set_state_machine.py"),
    ("maneuver_state", "Maneuver state", "Tracks each vessel's maneuver: course change, speed change or persisting course.", f"{_MONITORING}/maneuver_state_machine.py"),
    (
        "colregs_state",
        "COLREGS state",
        "Per vessel pair: whether they see each other, have passed each other, are on a collision course or violate a safety domain.",
        f"{_MONITORING}/colregs_state_machine.py",
    ),
    ("rule_state", "Rule state", "Builds the rule conditions that apply to each context and moves every rule result from one step to the next.", f"{_MONITORING}/rule_state_machine.py"),
)

_SITUATION_STATE = "situation_context_state"
_MANEUVER_STATE = "maneuver_state"


def _metamodel() -> Tuple[Tuple[MetamodelNode, ...], Tuple[MetamodelEdge, ...]]:
    nodes = (
        MetamodelNode(
            META_HOST,
            LANE_HOST,
            "Host",
            "A process that carries scenes to a monitor and its monitor result summaries back.",
            KIND_ROLE,
            ("scenes in order, timestamp 0 first", "the COLREGS constants of the scenario", "result: monitored frames or rule outcomes"),
            "Start a MonitorRuntime where scenes are produced and forward its frames.",
        ),
        MetamodelNode(
            META_MONITOR,
            LANE_MONITOR,
            "Monitor implementation",
            "How a run is judged. A campaign names it by id.",
            KIND_INTERFACE,
            ("id: a MonitorImplementation member", "judge(scenes) returns a monitor result summary", "supports_early_stop"),
            "Add a MonitorImplementation member, a MonitorSpec in monitoring_specs.py and the job that runs it.",
            "scenegems_tool/persistence/schema/campaign_tables.py",
        ),
        MetamodelNode(
            META_RUNTIME,
            LANE_ENGINE,
            "Monitor runtime",
            "Steps the engine through a trajectory scene by scene.",
            KIND_COMPONENT,
            ("step(scene) returns a monitored scene with its results", "timestamp 0 resets the runtime", "only the next time step is accepted"),
            None,
            f"{_MONITORING}/colregs_monitor_runtime.py",
        ),
        MetamodelNode(
            META_STATE,
            LANE_ENGINE,
            "State machine",
            "Keeps one kind of monitored state between steps.",
            KIND_COMPONENT,
            ("create_initial_state_set(context)", "step(previous state, next scene) returns the next state"),
            "Add a machine and step it in COLREGSMonitor.step.",
            f"{_MONITORING}/colregs_monitor.py",
        ),
        MetamodelNode(
            META_RULE,
            LANE_RULES,
            "Rule",
            "One monitored COLREGS rule or advisory suggestion, with the condition that decides it.",
            KIND_INTERFACE,
            (
                "COLREGSRule: rule_number, title, kind (rule or suggestion), subject vessel",
                "RuleCondition: evaluates a relation against the COLREGS constants",
                "an entry in a make_*_default_rules map of default_rules.py",
            ),
            "Add a COLREGSRule and its RuleCondition, then list them in default_rules.py and in rule_specs().",
            f"{_MONITORING}/colregs_rules/colregs_rules.py",
        ),
    )
    edges = (
        MetamodelEdge(META_RUNS_ON, META_HOST, META_MONITOR, "hosts", "A host runs one or more monitor implementations.", "uses"),
        MetamodelEdge(META_RUNS, META_MONITOR, META_RUNTIME, "runs", "A monitor that judges runs the engine.", "uses"),
        MetamodelEdge(META_STEPS, META_RUNTIME, META_STATE, "steps", "The runtime steps every state machine for each scene.", "uses"),
        MetamodelEdge(META_CHECKS, META_STATE, META_RULE, "checks", "The rule state decides each rule over the situation and maneuver contexts.", "uses"),
    )
    return nodes, edges


def monitoring_document(measurements: Optional[Mapping[str, MeasuredFacts]] = None) -> ArchitectureDocument:
    monitors = monitor_specs()
    check_covers_enum(MonitorImplementation, (spec.monitor.value for spec in monitors), "monitoring")
    metamodel_nodes, metamodel_edges = _metamodel()

    def node(local, lane, label, description, implements, code, facts=(), tags=()):
        return spec_node(DOCUMENT_ID, local, lane, label, description, implements, facts=(Fact("code", "Code", code, GROUP_PROPERTY), *facts), tags=tags, measurements=measurements)

    nodes = [node(local, LANE_HOST, label, description, META_HOST, code, tags=(tag,)) for local, label, description, code, tag in _HOSTS]
    edges = []
    for spec in monitors:
        nodes.append(node(spec.monitor.value, LANE_MONITOR, spec.label, spec.description, META_MONITOR, spec.code, spec.facts))
        edges.extend(spec_edge(DOCUMENT_ID, host, spec.monitor.value, "hosts", META_RUNS_ON, kind="uses", measurements=measurements) for host in spec.hosts)
    nodes.append(
        node(
            "colregs_monitor",
            LANE_ENGINE,
            "COLREGS monitor",
            "The rule engine. Each step it updates the situation contexts, maneuver states and COLREGS states, checks the rules and suggests maneuvers. The trajectory generator runs the same engine.",
            META_RUNTIME,
            f"{_MONITORING}/colregs_monitor.py",
            tags=("shared",),
        )
    )
    nodes.append(
        node(
            "monitor_runtime",
            LANE_ENGINE,
            "Runtime",
            "Holds the monitored trajectory and accepts only the scene that follows the last by one time step. Timestamp 0 resets it.",
            META_RUNTIME,
            f"{_MONITORING}/colregs_monitor_runtime.py",
        )
    )
    nodes.extend(node(local, LANE_ENGINE, label, description, META_STATE, code) for local, label, description, code in _STATE_MACHINES)
    for spec in monitors:
        if spec.engine:
            edges.append(spec_edge(DOCUMENT_ID, spec.monitor.value, "monitor_runtime", "runs", META_RUNS, kind="uses", measurements=measurements))
    edges.append(spec_edge(DOCUMENT_ID, "monitor_runtime", "colregs_monitor", "runs", META_RUNS, kind="uses", measurements=measurements))
    edges.extend(spec_edge(DOCUMENT_ID, "colregs_monitor", local, "steps", META_STEPS, kind="uses", measurements=measurements) for local, *_ in _STATE_MACHINES)
    for rule in rule_specs():
        name = f"Rule {rule.number}: {rule.title}" if rule.kind == "rule" else f"Suggestion: {rule.title}"
        scope = "per vessel pair (situation context)" if rule.scope == "situation" else "per vessel (maneuver context)"
        facts = (
            Fact("class", "Class", rule.rule_class, GROUP_PROPERTY),
            Fact("kind", "Kind", "advisory, never counts as a failure" if rule.kind == "suggestion" else "normative, a violation is a compliance failure", GROUP_CAPABILITY),
            Fact("scope", "Evaluated", scope, GROUP_CAPABILITY),
        )
        description = f"COLREGS rule {rule.number}." if rule.number else "Advisory guidance, not tied to a numbered rule."
        nodes.append(node(rule.local, LANE_RULES, name, description, META_RULE, f"{_MONITORING}/colregs_rules/colregs_rules.py", facts))
        edges.append(spec_edge(DOCUMENT_ID, _SITUATION_STATE if rule.scope == "situation" else _MANEUVER_STATE, rule.local, "checks", META_CHECKS, kind="uses", measurements=measurements))
    return ArchitectureDocument(
        id=DOCUMENT_ID,
        title="Monitoring",
        summary="The monitor implementations a campaign can choose, the COLREGS rule engine behind them and the rules it checks.",
        lanes=(
            Lane(LANE_HOST, "Host", "Where scenes are produced and monitor result summaries used."),
            Lane(LANE_MONITOR, "Monitor", "How a run is judged."),
            Lane(LANE_ENGINE, "Rule engine", "The state machines the monitor steps."),
            Lane(LANE_RULES, "Rules", "What is checked."),
        ),
        metamodel_nodes=metamodel_nodes,
        metamodel_edges=metamodel_edges,
        nodes=tuple(nodes),
        edges=tuple(edges),
        role=ROLE_SUPPORT,
        takes="scenes, trajectories and runs",
        gives="rule outcomes per vessel pair",
        job_types=("monitoring.post_hoc",),
    ).validate()
