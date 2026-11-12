from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import pytest

from scenegems_tool.persistence.schema import CaseState, MonitorImplementation, PipelineStage, StepKind, TrajectoryGeneratorImplementation, VerdictState
from scenegems_tool.persistence.stores import AssuranceStores, CaseRecord, JobStore, NewCase, NewRunRecord, NewVerdict, RunRecord, WorkerNodeStore
from tests.scenegems_tool.persistence.stores.builders import CONFIG_HASH, ManualClock, make_class_spec, sha256_of


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def worker_node_store(session_factory, clock) -> WorkerNodeStore:
    return WorkerNodeStore(session_factory, clock)


@pytest.fixture
def job_store(session_factory, clock) -> JobStore:
    return JobStore(session_factory, clock)


@pytest.fixture
def stores(session_factory, clock) -> AssuranceStores:
    return AssuranceStores.create(session_factory, clock)


CLASS_A = "2vessel_0obstacle_scenarios/fec0"
CLASS_B = "3vessel_1obstacle_scenarios/fec5"


@pytest.fixture
def campaign(stores):
    """A campaign of two classes: A with quota 3 and failure budget 2, B with quota 2 and budget 1."""
    return stores.campaigns.create_campaign(
        "lab campaign",
        {"name": "lab campaign"},
        CONFIG_HASH,
        [make_class_spec(CLASS_A, quota=3, failure_budget=2), make_class_spec(CLASS_B, quota=2, failure_budget=1, vessels=3, obstacles=1)],
        pinned_fingerprints={"scenegems-simulation": "fp-execution"},
    )


SCENE_0, SCENE_1, TRAJECTORY_DATA_0, TRAJECTORY_DATA_1 = sha256_of("scene 0"), sha256_of("scene 1"), sha256_of("trajectory data 0"), sha256_of("trajectory data 1")
STATE_LOG_0, STATE_LOG_1 = sha256_of("state log 0"), sha256_of("state log 1")
TRAJECTORY_FAILURES = ("OS_0 - TS_1: rule_13", "OS_0 - TS_2: rule_13", "OS_0 - TS_1: rule_16")
TRAJECTORY_OUTCOMES = {"OS_0 - TS_1": {"rule_13": {"failed": 40.0}, "rule_16": {"failed": 12.0}}, "OS_0 - TS_2": {"rule_13": {"failed": 30.0}}}


@dataclass(frozen=True)
class StepOutputs:
    """A campaign with outputs of every step (see the step_outputs fixture)."""

    campaign_id: str
    a0: CaseRecord
    a1: CaseRecord
    a2: CaseRecord
    b0: CaseRecord
    runs: Dict[Tuple[int, int], RunRecord]


def _run_record(case_id: int, run_index: int, repeat_index: int, state_log: Optional[str], complete: bool) -> NewRunRecord:
    return NewRunRecord(
        case_id=case_id,
        run_index=run_index,
        repeat_index=repeat_index,
        trajectory_generator=TrajectoryGeneratorImplementation.STRAIGHT,
        trajectories_complete=complete,
        stack={},
        environment={},
        seed=5,
        artifacts={} if state_log is None else {"state_log": state_log, "trajectories": TRAJECTORY_DATA_0},
    )


@pytest.fixture
def step_outputs(stores, campaign) -> StepOutputs:
    """Cases of the campaign at every step, with outputs, verdicts and run records.

    a0 (class A) completed every step: scene SCENE_0 (scene verdict passed), trajectory data
    TRAJECTORY_DATA_0, complete (trajectory verdict failed on rule_13 and rule_16), runs
    (0, 0) and (0, 1) with state logs STATE_LOG_0 and STATE_LOG_1 (the repeat incomplete) and
    run (1, 0) without one; the simulation verdict of run 0 failed, of run 1 passed. a1 dropped
    at scene generation with an invalid scene SCENE_1, a2 is still generating its scene, b0
    (class B) dropped at trajectory generation with incomplete trajectories
    TRAJECTORY_DATA_1. SCENE_0, TRAJECTORY_DATA_0 and STATE_LOG_0 have artifact records.
    """
    campaign_id = campaign.campaign_id
    a0, a1, a2 = stores.cases.create_cases(campaign_id, [NewCase(class_id=CLASS_A, case_index=index, seed=index) for index in range(3)])
    (b0,) = stores.cases.create_cases(campaign_id, [NewCase(class_id=CLASS_B, case_index=0, seed=9)])
    a0 = stores.cases.move_case(
        a0.case_id, a0.version, stage=PipelineStage.VERDICT, state=CaseState.COMPLETE, scene_artifact=SCENE_0, trajectories_artifact=TRAJECTORY_DATA_0, trajectories_complete=True
    )
    a1 = stores.cases.move_case(a1.case_id, a1.version, state=CaseState.DROPPED, scene_artifact=SCENE_1, reason="the scene generation found no valid scene")
    b0 = stores.cases.move_case(
        b0.case_id,
        b0.version,
        stage=PipelineStage.GENERATE_TRAJECTORIES,
        state=CaseState.DROPPED,
        scene_artifact=SCENE_0,
        trajectories_artifact=TRAJECTORY_DATA_1,
        trajectories_complete=False,
        reason="the trajectory generator found no complete trajectories",
    )
    for artifact_hash, kind in ((SCENE_0, "scene"), (TRAJECTORY_DATA_0, "trajectory_data"), (STATE_LOG_0, "trajectories")):
        stores.artifacts.insert_if_absent(artifact_hash, kind, 100, "application/json")
    runs = {
        (0, 0): stores.results.add_run_record(_run_record(a0.case_id, 0, 0, STATE_LOG_0, True)),
        (0, 1): stores.results.add_run_record(_run_record(a0.case_id, 0, 1, STATE_LOG_1, False)),
        (1, 0): stores.results.add_run_record(_run_record(a0.case_id, 1, 0, None, True)),
    }
    post_hoc = MonitorImplementation.POST_HOC
    stores.results.add_verdict(NewVerdict(case_id=a0.case_id, run_index=0, state=VerdictState.PASSED, monitor=post_hoc, step=StepKind.SCENE))
    stores.results.add_verdict(
        NewVerdict(
            case_id=a0.case_id,
            run_index=0,
            state=VerdictState.FAILED,
            monitor=post_hoc,
            rule_outcomes=TRAJECTORY_OUTCOMES,
            failed_rules=TRAJECTORY_FAILURES,
            first_failure_time_s=12.0,
            step=StepKind.TRAJECTORIES,
        )
    )
    stores.results.add_verdict(
        NewVerdict(case_id=a0.case_id, run_index=0, state=VerdictState.FAILED, monitor=post_hoc, failed_rules=("OS_0 - TS_1: rule_8",), run_record_id=runs[(0, 0)].run_record_id)
    )
    stores.results.add_verdict(NewVerdict(case_id=a0.case_id, run_index=1, state=VerdictState.PASSED, monitor=post_hoc, run_record_id=runs[(1, 0)].run_record_id))
    return StepOutputs(campaign_id, a0, a1, a2, b0, runs)
