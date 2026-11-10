"""Plain text tables and summaries for the campaign CLI."""

from typing import Any, Dict, List, Optional, Sequence


def table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """Left aligned columns separated by two spaces; numbers are right aligned."""
    cells = [[_text(value) for value in row] for row in rows]
    widths = [max([len(header)] + [len(row[column]) for row in cells]) for column, header in enumerate(headers)]
    numeric = [bool(rows) and all(isinstance(row[column], (int, float)) and not isinstance(row[column], bool) for row in rows) for column in range(len(headers))]

    def line(values: Sequence[str]) -> str:
        return "  ".join(value.rjust(width) if right else value.ljust(width) for value, width, right in zip(values, widths, numeric)).rstrip()

    return "\n".join([line(list(headers))] + [line(row) for row in cells])


def _text(value: Any) -> str:
    return "-" if value is None else str(value)


def verdicts_of(entry: Dict[str, Any]) -> Dict[str, int]:
    """A FEC's verdict counts per state, summed over its runs."""
    counts: Dict[str, int] = {}
    for states in entry["verdicts"].values():
        for state, count in states.items():
            counts[state] = counts.get(state, 0) + count
    return counts


def campaign_row(campaign: Dict[str, Any]) -> List[Any]:
    """A line of the campaign list; a control node before Phase 6 sends no kind, origin or steps."""
    steps = ",".join(campaign["steps"]) if campaign.get("steps") else None
    return [campaign["campaign_id"], campaign["name"], campaign.get("kind"), campaign.get("origin"), steps, campaign["desired_state"], campaign["actual_state"], campaign["created_at"]]


def campaign_summary(campaign: Dict[str, Any]) -> str:
    lines = [
        f"campaign {campaign['name']} ({campaign['campaign_id']})",
        f"desired {campaign['desired_state']}, actual {campaign['actual_state']}" + (f" ({campaign['state_reason']})" if campaign.get("state_reason") else ""),
        f"config version {campaign['config_version']}, created {campaign['created_at']}"
        + (f", started {campaign['started_at']}" if campaign.get("started_at") else "")
        + (f", finished {campaign['finished_at']}" if campaign.get("finished_at") else ""),
    ]
    totals = campaign.get("totals")
    if totals:
        verdicts = ", ".join(f"{state} {count}" for state, count in sorted(totals["verdicts"].items())) or "none yet"
        lines.append(f"FECs {totals['fecs']}: open {totals['fecs_open']}, complete {totals['fecs_complete']}, abandoned {totals['fecs_abandoned']}")
        lines.append(f"cases: {totals['complete']} complete of quota {totals['quota']}, {totals['dropped']} dropped, {totals['in_flight']} in flight")
        lines.append(f"monitor result summaries: {verdicts}")
    return "\n".join(lines)


OUTPUT_HEADERS = ["FEC", "index", "case", "state", "valid", "complete", "run", "repeat", "monitor result summary", "artifact", "from"]


def _short(sha256: Optional[str]) -> Optional[str]:
    return None if sha256 is None else sha256[:12]


def _source(source: Optional[Dict[str, Any]]) -> Optional[str]:
    """Where an output's input came from: campaign and case, the file, or a deleted entry."""
    if source is None:
        return None
    if "campaign_id" in source:
        return f"{source['campaign_id']}#{source.get('case_id')}"
    return source.get("file", "deleted")


def output_row(output: Dict[str, Any]) -> List[Any]:
    verdict = output.get("verdict")
    verdict_text = None if verdict is None else verdict["state"] + (f" ({';'.join(verdict['failed_rules'])})" if verdict["failed_rules"] else "")
    artifact = output.get("artifact")
    return [
        output["fec_id"],
        output["case_index"],
        output["case_id"],
        output["state"],
        output["valid"],
        output["complete"],
        output["run_index"],
        output["repeat_index"],
        verdict_text,
        _short(None if artifact is None else artifact["sha256"]),
        _source(output.get("input_source")),
    ]


def findings_summary(findings: Dict[str, Any]) -> str:
    """The findings of one step as text: cases, outputs, verdicts, failed rules, FECs and durations."""
    cases = ", ".join(f"{state} {count}" for state, count in sorted(findings["cases"].items())) or "none"
    outputs = findings["outputs"]
    lines = [
        f"{findings['step']}: {'monitored' if findings['monitored'] else 'not monitored (statistics only)'}",
        f"cases: {cases}",
        f"outputs: {outputs['count']}, valid {outputs['valid']}, complete {outputs['complete']}",
    ]
    if findings["monitored"]:
        verdicts = findings["verdicts"]
        lines.append(f"monitor result summaries: passed {verdicts['passed']}, failed {verdicts['failed']}, unmonitored {verdicts['unmonitored']}")
    durations = findings["durations_s"]
    if durations["median"] is not None:
        lines.append(f"job duration s: median {durations['median']:.1f}, p90 {durations['p90']:.1f}")
    if findings.get("encounter_types"):  # absent from an older control node
        lines.append("encounters (vessel pairs by first type): " + ", ".join(f"{name} {count}" for name, count in findings["encounter_types"].items()))
    if findings["failed_rules"]:
        lines.append("")
        lines.append(
            table(
                ["failed rule", "count", "first failure s (min)", "first failure s (median)"],
                [[r["rule"], r["count"], r["first_failure_time_s"]["min"], r["first_failure_time_s"]["median"]] for r in findings["failed_rules"]],
            )
        )
    if findings["fecs"]:
        lines.append("")
        lines.append(table(["FEC", "cases", "passed", "failed"], [[c["fec_id"], c["cases"], c["passed"], c["failed"]] for c in findings["fecs"]]))
    return "\n".join(lines)


def _budget_left(entry: Dict[str, Any]) -> Any:
    """The FEC's failure budget left, or unlimited."""
    return "unlimited" if entry["failure_budget_left"] is None else entry["failure_budget_left"]


def coverage_table(classes: List[Dict[str, Any]]) -> str:
    states = sorted({state for entry in classes for state in verdicts_of(entry)})
    headers = ["FEC", "state", "quota", "complete", "dropped", "in flight", "budget left"] + states
    rows = []
    for entry in classes:
        counts = verdicts_of(entry)
        rows.append([entry["fec_id"], entry["state"], entry["quota"], entry["complete"], entry["dropped"], entry["in_flight"], _budget_left(entry)] + [counts.get(state, 0) for state in states])
    return table(headers, rows)
