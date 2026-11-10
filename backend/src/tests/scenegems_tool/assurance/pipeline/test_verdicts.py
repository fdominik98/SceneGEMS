"""Verdicts from each monitor's result, run records from a simulation result, calibration results."""

from datetime import datetime, timedelta, timezone

import pytest

from scenegems_tool.assurance.pipeline.pipeline_queries import JobFacts
from scenegems_tool.assurance.pipeline.verdicts import (
    RESULT_FIELD_ROLES,
    ResultError,
    new_calibration_result,
    new_run_record,
    new_verdict,
    pending_from_live,
    pending_from_post_hoc,
    pending_unmonitored,
    step_roles,
)
from scenegems_tool.cluster.protocol.jobs import JobState
from scenegems_tool.persistence.schema import MonitorImplementation, RunSource, StepKind, TrajectoryGeneratorImplementation, VerdictState
from scenegems_tool.persistence.stores.result_store import check_verdict

FAILED_RULES = [{"relation": "OS_0 - TS_1", "rule": "Rule 14", "first_failed_at": 12}, {"relation": "OS_0 - TS_2", "rule": "Rule 8", "first_failed_at": 30}]
LOG = {"sha256": "cd" * 32, "size_bytes": 10, "kind": "trajectories"}


def test_a_post_hoc_failure_names_its_rules_and_first_failure():
    pending = pending_from_post_hoc({"rules": {"OS_0 - TS_1": {"Rule 14": {"failed": 12}}}, "failed_rules": FAILED_RULES, "passed": False})
    verdict = new_verdict(7, 0, pending, 3, sensitive=False)
    assert verdict.state == VerdictState.FAILED and verdict.monitor == MonitorImplementation.POST_HOC
    assert verdict.failed_rules == ("OS_0 - TS_1: Rule 14", "OS_0 - TS_2: Rule 8")
    assert verdict.first_failure_time_s == 12.0 and verdict.early_stop_time_s is None and verdict.run_record_id == 3
    assert verdict.rule_outcomes == {"OS_0 - TS_1": {"Rule 14": {"failed": 12}}}
    check_verdict(verdict)


def test_the_encounter_types_travel_from_the_monitor_result_to_the_verdict():
    encounters = {"OS_0 - TS_1": ["HEAD_ON", "OTHER"], "OS_0 - TS_2": ["CROSSING_FROM_PORT"]}
    verdict = new_verdict(7, 0, pending_from_post_hoc({"rules": {}, "failed_rules": [], "encounters": encounters, "passed": True}), None, sensitive=False)
    assert verdict.encounters == encounters
    live = new_verdict(7, 1, pending_from_live({"monitor": {"rules": {}, "failed_rules": [], "encounters": encounters, "passed": True, "stopped_early_at": None}}), None, sensitive=False)
    assert live.encounters == encounters


def test_a_result_without_encounters_gives_a_verdict_without_them():
    """A result of an older worker node, an empty summary and an unmonitored step all have none (stored as null)."""
    assert new_verdict(7, 0, pending_from_post_hoc({"rules": {}, "failed_rules": [], "passed": True}), None, sensitive=False).encounters is None
    assert new_verdict(7, 0, pending_from_post_hoc({"rules": {}, "failed_rules": [], "encounters": {}, "passed": True}), None, sensitive=False).encounters is None
    assert new_verdict(7, 0, pending_unmonitored(), None, sensitive=False).encounters is None


def test_the_vessel_roles_travel_from_the_monitor_result_to_the_verdict():
    roles = {"OS_0 - TS_1": {"CROSSING_FROM_PORT": {"give_way": ["TS_1"], "stand_on": ["OS_0"]}}}
    verdict = new_verdict(7, 0, pending_from_post_hoc({"rules": {}, "failed_rules": [], "encounter_roles": roles, "passed": True}), None, sensitive=False)
    assert verdict.encounter_roles == roles
    live = new_verdict(7, 1, pending_from_live({"monitor": {"rules": {}, "failed_rules": [], "encounter_roles": roles, "passed": True, "stopped_early_at": None}}), None, sensitive=False)
    assert live.encounter_roles == roles


def test_a_result_without_vessel_roles_gives_a_verdict_without_them():
    """A result of an older worker node, a run without an encounter and an unmonitored step all have none (stored as null)."""
    assert new_verdict(7, 0, pending_from_post_hoc({"rules": {}, "failed_rules": [], "passed": True}), None, sensitive=False).encounter_roles is None
    assert new_verdict(7, 0, pending_from_post_hoc({"rules": {}, "failed_rules": [], "encounter_roles": {}, "passed": True}), None, sensitive=False).encounter_roles is None
    assert new_verdict(7, 0, pending_unmonitored(), None, sensitive=False).encounter_roles is None


def test_a_passed_run_has_no_failure_time():
    verdict = new_verdict(7, 0, pending_from_post_hoc({"rules": {}, "failed_rules": [], "passed": True}), None, sensitive=True)
    assert verdict.state == VerdictState.PASSED and verdict.first_failure_time_s is None and verdict.sensitive
    check_verdict(verdict)


def test_the_live_monitor_reports_its_early_stop():
    section = {"rules": {}, "failed_rules": FAILED_RULES[:1], "passed": False, "stopped_early_at": 40}
    verdict = new_verdict(7, 1, pending_from_live({"monitor": section}), None, sensitive=False)
    assert verdict.monitor == MonitorImplementation.LIVE and verdict.early_stop_time_s == 40.0 and verdict.state == VerdictState.FAILED
    check_verdict(verdict)
    assert new_verdict(7, 1, pending_from_live({"monitor": {**section, "stopped_early_at": None}}), None, False).early_stop_time_s is None
    with pytest.raises(ResultError, match="no monitor section"):
        pending_from_live({"steps": 3})
    with pytest.raises(ResultError, match="no passed"):
        pending_from_post_hoc({"rules": {}})


def test_the_empty_monitor_judges_nothing():
    verdict = new_verdict(7, 0, pending_unmonitored(), None, sensitive=False)
    assert (verdict.state, verdict.monitor, verdict.failed_rules) == (VerdictState.UNMONITORED, MonitorImplementation.EMPTY, ())
    check_verdict(verdict)


def test_a_run_record_takes_the_simulation_and_its_job():
    start = datetime(2026, 10, 25, tzinfo=timezone.utc)
    facts = JobFacts("job-1", JobState.SUCCEEDED, None, None, "worker-node-1", {"image": "fp"}, start, start + timedelta(seconds=4), start + timedelta(seconds=10))
    result = {"run_record": {"dt": 0.5, "steps": 20, "repeatability_tier": "exact", "environment": {"wind_vector": [0, 0, 0]}}, "steps": 20, "state_digest": "abc", "trajectories": LOG}
    record = new_run_record(
        7,
        0,
        1,
        TrajectoryGeneratorImplementation.STRAIGHT,
        True,
        {"mode": "replay"},
        {"wind": "config"},
        99,
        result,
        "ef" * 32,
        facts.job_id,
        facts.lease_owner,
        facts.required_fingerprints,
        facts.durations_s(),
        None,
    )
    assert (record.repeat_index, record.seed, record.steps, record.dt, record.state_digest, record.repeatability_tier) == (1, 99, 20, 0.5, "abc", "exact")
    assert record.artifacts == {"trajectories": "ef" * 32, "state_log": "cd" * 32}
    assert record.environment == {"wind_vector": [0, 0, 0]} and record.stack["config"] == {"mode": "replay"} and record.stack["run_record"]["dt"] == 0.5
    assert (record.job_id, record.worker_node_id, record.fingerprints) == ("job-1", "worker-node-1", {"image": "fp"})
    assert record.durations_s == {"queued_s": 4.0, "running_s": 6.0, "total_s": 10.0}
    inline = new_run_record(
        7, 0, 0, TrajectoryGeneratorImplementation.STRAIGHT, True, {}, {"wind": "config"}, 1, {"steps": 3, "trajectories": {"scene_list": []}}, None, "job", None, {}, {}, "bounded"
    )
    assert inline.artifacts == {} and inline.repeatability_tier == "bounded" and inline.environment == {"wind": "config"}


def test_a_calibration_result_keeps_its_envelope():
    result = {"reference": "case#0", "stack": {}, "repeats": 3, "exact": False, "deviation_bound_m": 1.5, "per_vessel": {"0": {"max_m": 1.5}}, "trajectory_digests": ["a", "b", "c"]}
    calibration = new_calibration_result(result, {"mode": "replay"}, {"image": "fp"}, {"wind_vector": [0, 0, 0]}, "campaign")
    assert (calibration.reference_scenario, calibration.repeats, calibration.exact, calibration.deviation_bound_m) == ("case#0", 3, False, 1.5)
    assert calibration.envelope == {"per_vessel": {"0": {"max_m": 1.5}}, "trajectory_digests": ["a", "b", "c"]}
    with pytest.raises(ResultError, match="no exact"):
        new_calibration_result({"reference": "x", "repeats": 2}, {}, {}, {}, "campaign")


def test_a_scene_or_trajectory_verdict_names_its_step_at_run_0():
    pending = pending_from_post_hoc({"rules": {}, "failed_rules": FAILED_RULES[:1], "passed": False})
    verdict = new_verdict(7, 0, pending, None, False, step=StepKind.TRAJECTORIES)
    assert (verdict.step, verdict.run_index, verdict.run_record_id, verdict.state) == (StepKind.TRAJECTORIES, 0, None, VerdictState.FAILED)
    check_verdict(verdict)
    assert new_verdict(7, 1, pending, 3, False).step == StepKind.SIMULATION  # runs keep the simulation step


def test_a_recorded_run_has_no_job_and_no_generator():
    result = {"trajectories": LOG, "steps": 30, "state_digest": None, "run_record": {"dt": 0.1, "repeatability_tier": "bounded", "environment": {"wind": 1}}}
    record = new_run_record(7, 0, 0, None, True, {"vessels": {"0": "ardupilot"}}, {"wind": 1}, 5, result, "ef" * 32, None, None, {}, {"running_s": 60.0}, "bounded", source=RunSource.LIVE_SESSION)
    assert (record.source, record.job_id, record.trajectory_generator, record.dt, record.steps) == (RunSource.LIVE_SESSION, None, None, 0.1, 30)
    assert record.artifacts == {"trajectories": "ef" * 32, "state_log": "cd" * 32}


def test_the_generation_monitors_frames_keep_their_own_roles():
    assert step_roles(StepKind.SCENE)["frames"] == "scene_frames" and step_roles(StepKind.TRAJECTORIES)["frames"] == "trajectory_frames"
    assert RESULT_FIELD_ROLES["frames"] == "frames" and step_roles(StepKind.SCENE)["evaluation_data"] == "scene"
