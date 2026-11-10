"""JSON views of campaigns and their FECs, cases, jobs, results and events for the operator API.

Plain dictionaries with ISO times (UTC, as stored), in the style of views.py. Enum values
are their wire strings, and a verdict count map is keyed by the run index as a string.

The API calls what the stores call a class a FEC (functional equivalence class): fec_id,
fecs, fecs_open and so on, and the event kinds fec_complete and fec_abandoned (stored as
class_complete and class_abandoned).

A list row (campaign_row_view) also says what the campaign's config says: the steps it runs, its input
and the campaigns its items came from, read from the stored config JSON so that this module needs no
config model (which pulls in numpy and the job type modules the master keeps out of its startup).
"""

import json
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set

from scenegems_tool.persistence.stores import (
    CampaignEventRecord,
    CampaignRecord,
    CampaignTotals,
    CaseRecord,
    ClassCoverage,
    ClassRecord,
    ConfigVersionRecord,
    JobRecord,
    OutputRecord,
    PipelineJobRecord,
    RunRecord,
    StepFindings,
    VerdictRecord,
)

STEP_NAMES = ("scene_generation", "trajectory_generation", "simulation")  # the chain, as the config and the API name its steps

VERDICT_COLUMNS = (
    "verdict_id",
    "fec_id",
    "case_id",
    "case_index",
    "step",
    "run_index",
    "state",
    "monitor",
    "failed_rules",
    "first_failure_time_s",
    "margin",
    "sensitive",
    "early_stop_time_s",
    "encounters",
    "created_at",
)


def iso(value: Optional[datetime]) -> Optional[str]:
    return None if value is None else value.isoformat()


def campaign_view(campaign: CampaignRecord) -> Dict[str, Any]:
    return {
        "campaign_id": campaign.campaign_id,
        "name": campaign.name,
        "desired_state": campaign.desired_state.value,
        "actual_state": campaign.actual_state.value,
        "state_reason": campaign.state_reason,
        "kind": campaign.kind.value,
        "origin": None if campaign.origin is None else campaign.origin.value,  # None for campaigns made before Phase 6
        "config_version": campaign.config_version,
        "pinned_fingerprints": campaign.pinned_fingerprints,
        "created_at": iso(campaign.created_at),
        "updated_at": iso(campaign.updated_at),
        "started_at": iso(campaign.started_at),
        "finished_at": iso(campaign.finished_at),
    }


def config_steps(config: Mapping[str, Any]) -> List[str]:
    """The steps a stored config runs; a format 1 config, which stores none, runs the full chain."""
    return list(config.get("steps") or STEP_NAMES)


def config_input(config: Mapping[str, Any]) -> Dict[str, Any]:
    """The first step and how many items the config's input names: the items of a later start and the functional scenarios given as content."""
    given = config.get("input") or {}
    return {"first_step": config_steps(config)[0], "item_count": len(given.get("items") or []) + len(given.get("functional_scenarios") or [])}


def config_made_from(config: Mapping[str, Any]) -> List[str]:
    """The campaigns the config's items came from, in the order of the items, each once."""
    ids: List[str] = []
    for item in (config.get("input") or {}).get("items") or []:
        campaign_id = (item.get("source") or {}).get("campaign_id")
        if campaign_id is not None and campaign_id not in ids:
            ids.append(campaign_id)
    return ids


def config_monitored(config: Mapping[str, Any], step: str) -> bool:
    """Whether the config monitors a step. A generation step is monitored when its monitor is not empty (a format 1 config stores none); the simulation when any run's is."""
    if step == "scene_generation":
        return (config.get("scene_generation") or {}).get("monitor", "empty") != "empty"
    if step == "trajectory_generation":
        return (config.get("trajectories") or {}).get("monitor", "empty") != "empty"
    return any(run.get("monitor", "post_hoc") != "empty" for run in (config.get("execution") or {}).get("runs") or [])


def config_view(config: Mapping[str, Any]) -> Dict[str, Any]:
    """What a list row and a detail say about the campaign's config: steps, input and made_from."""
    return {"steps": config_steps(config), "input": config_input(config), "made_from": config_made_from(config)}


def totals_view(totals: CampaignTotals) -> Dict[str, Any]:
    """Cases by state and verdicts by step and state, with the enum values as keys."""
    return {
        "cases": {state.value: count for state, count in totals.cases.items()},
        "verdicts": {step.value: {state.value: count for state, count in states.items()} for step, states in totals.verdicts.items()},
    }


def campaign_row_view(campaign: CampaignRecord, config: Optional[Mapping[str, Any]], totals: CampaignTotals) -> Dict[str, Any]:
    """A list row: the summary with the config's steps, input and made_from, and the totals, so the list needs no detail call per row."""
    return {**campaign_view(campaign), **config_view(config or {}), "totals": totals_view(totals)}


def verdict_counts(coverage: ClassCoverage) -> Dict[str, Dict[str, int]]:
    return {str(run_index): {state.value: count for state, count in states.items()} for run_index, states in coverage.verdicts.items()}


def class_view(record: ClassRecord, coverage: Optional[ClassCoverage] = None) -> Dict[str, Any]:
    return {
        "fec_id": record.class_id,
        "state": record.state.value,
        "state_reason": record.state_reason,
        "content_hash": record.content_hash,
        "vessel_count": record.vessel_count,
        "obstacle_count": record.obstacle_count,
        "quota": record.quota,
        "failure_budget": record.failure_budget,
        "failure_budget_left": record.failure_budget_left,
        "complete": record.complete_count,
        "dropped": record.dropped_count,
        "in_flight": record.in_flight_count,
        "verdicts": {} if coverage is None else verdict_counts(coverage),
        "created_at": iso(record.created_at),
        "updated_at": iso(record.updated_at),
        "finished_at": iso(record.finished_at),
    }


def classes_view(records: Sequence[ClassRecord], coverage: Iterable[ClassCoverage]) -> List[Dict[str, Any]]:
    by_class = {entry.class_id: entry for entry in coverage}
    return [class_view(record, by_class.get(record.class_id)) for record in records]


def campaign_detail_view(campaign: CampaignRecord, classes: List[Dict[str, Any]], config: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """The campaign with its FECs (counts and verdicts per run and state) and their totals; given its config, also steps, input and made_from."""
    verdicts: Dict[str, int] = {}
    for entry in classes:
        for states in entry["verdicts"].values():
            for state, count in states.items():
                verdicts[state] = verdicts.get(state, 0) + count
    view = campaign_view(campaign)
    if config is not None:
        view.update(config_view(config))
    view["totals"] = {
        "fecs": len(classes),
        "fecs_open": sum(1 for entry in classes if entry["state"] == "open"),
        "fecs_complete": sum(1 for entry in classes if entry["state"] == "complete"),
        "fecs_abandoned": sum(1 for entry in classes if entry["state"] == "abandoned"),
        "quota": sum(entry["quota"] for entry in classes),
        "complete": sum(entry["complete"] for entry in classes),
        "dropped": sum(entry["dropped"] for entry in classes),
        "in_flight": sum(entry["in_flight"] for entry in classes),
        "verdicts": verdicts,
    }
    view["fecs"] = classes
    return view


def case_view(case: CaseRecord) -> Dict[str, Any]:
    return {
        "case_id": case.case_id,
        "campaign_id": case.campaign_id,
        "fec_id": case.class_id,
        "case_index": case.case_index,
        "seed": case.seed,
        "config_version": case.config_version,
        "stage": case.stage.value,
        "state": case.state.value,
        "scene_artifact": case.scene_artifact,
        "trajectories_artifact": case.trajectories_artifact,
        "trajectories_complete": case.trajectories_complete,
        "input_artifact": case.input_artifact,
        "input_source": case.input_source,
        "reason": case.reason,
        "created_at": iso(case.created_at),
        "updated_at": iso(case.updated_at),
        "finished_at": iso(case.finished_at),
    }


def case_job_view(pipeline_job: PipelineJobRecord, job: Optional[JobRecord]) -> Dict[str, Any]:
    """A case's job: the pipeline link, and the job's state without its payload and result (GET /cluster/jobs/<id> has those)."""
    view: Dict[str, Any] = {
        "stage": pipeline_job.stage.value,
        "run_index": pipeline_job.run_index,
        "repeat_index": pipeline_job.repeat_index,
        "idempotency_key": pipeline_job.idempotency_key,
        "job_id": pipeline_job.job_id,
        "intent": pipeline_job.is_intent,
        "created_at": iso(pipeline_job.created_at),
        "submitted_at": iso(pipeline_job.submitted_at),
        "job": None,
    }
    if job is not None:
        view["job"] = {
            "job_type": job.job_type.value,
            "state": job.state.value,
            "priority": job.priority,
            "attempt": job.attempt,
            "failed_attempts": job.failed_attempts,
            "max_attempts": job.max_attempts,
            "lease_owner": job.lease_owner,
            "available_at": iso(job.available_at),
            "started_at": iso(job.started_at),
            "finished_at": iso(job.finished_at),
            "error": job.error,
        }
    return view


def run_record_view(record: RunRecord) -> Dict[str, Any]:
    return {
        "run_record_id": record.run_record_id,
        "case_id": record.case_id,
        "case_index": record.case_index,
        "campaign_id": record.campaign_id,
        "fec_id": record.class_id,
        "run_index": record.run_index,
        "repeat_index": record.repeat_index,
        "trajectory_generator": None if record.trajectory_generator is None else record.trajectory_generator.value,  # None for a recorded live session
        "source": record.source.value,
        "trajectories_complete": record.trajectories_complete,
        "stack": record.stack,
        "repeatability_tier": record.repeatability_tier,
        "environment": record.environment,
        "seed": record.seed,
        "dt": record.dt,
        "steps": record.steps,
        "state_digest": record.state_digest,
        "artifacts": record.artifacts,
        "job_id": record.job_id,
        "node_id": record.node_id,
        "fingerprints": record.fingerprints,
        "durations_s": record.durations_s,
        "created_at": iso(record.created_at),
    }


def verdict_view(verdict: VerdictRecord) -> Dict[str, Any]:
    return {
        "verdict_id": verdict.verdict_id,
        "case_id": verdict.case_id,
        "case_index": verdict.case_index,
        "campaign_id": verdict.campaign_id,
        "fec_id": verdict.class_id,
        "step": verdict.step.value,
        "run_index": verdict.run_index,
        "run_record_id": verdict.run_record_id,
        "state": verdict.state.value,
        "monitor": verdict.monitor.value,
        "rule_outcomes": verdict.rule_outcomes,
        "failed_rules": list(verdict.failed_rules),
        "first_failure_time_s": verdict.first_failure_time_s,
        "margin": verdict.margin,
        "sensitive": verdict.sensitive,
        "early_stop_time_s": verdict.early_stop_time_s,
        "encounters": verdict.encounters,
        "encounter_roles": verdict.encounter_roles,
        "created_at": iso(verdict.created_at),
    }


def verdict_row(verdict: VerdictRecord) -> List[Any]:
    """The verdict as a CSV row in VERDICT_COLUMNS order: failed rules joined with a semicolon, encounters as compact JSON, empty cells for nulls."""
    values = verdict_view(verdict)
    values["failed_rules"] = ";".join(verdict.failed_rules)
    if verdict.encounters is not None:
        values["encounters"] = json.dumps(verdict.encounters, separators=(",", ":"))
    return ["" if values[column] is None else values[column] for column in VERDICT_COLUMNS]


# Event kinds and detail keys the API names after FECs; the stored ones keep their names
EVENT_KIND_NAMES = {"class_complete": "fec_complete", "class_abandoned": "fec_abandoned"}
EVENT_DETAIL_KEYS = {"classes": "fecs"}


def event_view(event: CampaignEventRecord) -> Dict[str, Any]:
    detail = {EVENT_DETAIL_KEYS.get(key, key): value for key, value in event.detail.items()} if isinstance(event.detail, Mapping) else event.detail
    return {"event_id": event.event_id, "at": iso(event.at), "kind": EVENT_KIND_NAMES.get(event.kind.value, event.kind.value), "fec_id": event.class_id, "detail": detail}


def output_verdict_view(output: OutputRecord) -> Optional[Dict[str, Any]]:
    """The step's verdict of an output, in short: enough for the monitor result summary of a row, the rule outcomes stay with the verdict route."""
    if output.verdict_state is None:
        return None
    return {
        "state": output.verdict_state.value,
        "failed_rules": list(output.failed_rules),
        "first_failure_time_s": output.first_failure_time_s,
        "encounters": output.encounters,
        "encounter_roles": output.encounter_roles,
    }


def output_view(output: OutputRecord, source_exists: Callable[[str], bool] = lambda campaign_id: True) -> Dict[str, Any]:
    """An output of a step. The artifact is None while the step has none or once its record is gone; an input source whose campaign was deleted since reads as {}."""
    artifact = output.artifact
    reference = None
    if artifact is not None and artifact.size_bytes is not None and artifact.kind is not None:
        reference = {"sha256": artifact.sha256, "size_bytes": artifact.size_bytes, "kind": artifact.kind, "media_type": artifact.media_type, "pointer": artifact.pointer}
    source = output.input_source
    if source is not None and source.get("campaign_id") is not None and not source_exists(source["campaign_id"]):
        source = {}
    return {
        "case_id": output.case_id,
        "case_index": output.case_index,
        "fec_id": output.class_id,
        "state": output.state.value,
        "reason": output.reason,
        "artifact": reference,
        "valid": output.valid,
        "complete": output.complete,
        "run_index": output.run_index,
        "repeat_index": output.repeat_index,
        "run_record_id": output.run_record_id,
        "verdict": output_verdict_view(output),
        "input_source": source,
    }


def source_campaigns(outputs: Iterable[OutputRecord]) -> Set[str]:
    """The campaigns the outputs' input sources name."""
    return {output.input_source["campaign_id"] for output in outputs if output.input_source is not None and output.input_source.get("campaign_id") is not None}


def findings_view(step: str, findings: StepFindings) -> Dict[str, Any]:
    """The findings of a step, which echo the step as the API names it (scene_generation, not scene)."""
    verdicts = {state.value: count for state, count in findings.verdicts.items()}
    return {
        "step": step,
        "monitored": findings.monitored,
        "cases": {state.value: count for state, count in findings.cases.items()},
        "outputs": {"count": findings.outputs_count, "valid": findings.outputs_valid, "complete": findings.outputs_complete},
        "verdicts": {"passed": verdicts.get("passed", 0), "failed": verdicts.get("failed", 0), "unmonitored": verdicts.get("unmonitored", 0)},
        "failed_rules": [
            {"rule": rule.rule, "count": rule.count, "first_failure_time_s": {"min": rule.first_failure_time_min_s, "median": rule.first_failure_time_median_s}} for rule in findings.failed_rules
        ],
        "encounter_types": findings.encounter_types,
        "fecs": [{"fec_id": entry.class_id, "cases": entry.cases, "passed": entry.passed, "failed": entry.failed} for entry in findings.classes],
        "durations_s": {"median": findings.duration_median_s, "p90": findings.duration_p90_s},
    }


def validated_campaign_view(validated: Any) -> Dict[str, Any]:
    """What validating a config found: its hash, the FECs it selects and the runs it plans (a ValidatedCampaign; nothing is stored)."""
    return {
        "valid": True,
        "name": validated.config.name,
        "config_hash": validated.config_hash,
        "fecs": [
            {
                "fec_id": spec.class_id,
                "content_hash": spec.content_hash,
                "vessel_count": spec.vessel_count,
                "obstacle_count": spec.obstacle_count,
                "quota": spec.quota,
                "failure_budget": spec.failure_budget,
            }
            for spec in validated.classes
        ],
        "cases_planned": validated.total_quota,
        "runs": [
            {"run_index": stacks.run_index, "name": validated.config.execution.runs[stacks.run_index].name, "repeatability_tier": stacks.repeatability_tier, "warnings": list(stacks.warnings)}
            for stacks in validated.runs
        ],
    }


def config_version_view(version: ConfigVersionRecord) -> Dict[str, Any]:
    return {"version": version.version, "config_hash": version.config_hash, "created_at": iso(version.created_at), "config": version.config}
