"""The coverage controller's rules, and the selected set under any completion order."""

import random
from dataclasses import replace
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pytest

from scenegems_tool.assurance.campaign.campaign_config import QueueDepthCaps
from scenegems_tool.assurance.pipeline.coverage_controller import Backpressure, decide_class, plan_new_cases, startable
from scenegems_tool.persistence.schema import CampaignClassState, CaseState, PipelineStage
from scenegems_tool.persistence.stores import CaseRecord, ClassRecord

NOW = datetime(2026, 10, 25, tzinfo=timezone.utc)


def make_case(index: int, state: CaseState = CaseState.ACTIVE, ready: bool = False) -> CaseRecord:
    stage = PipelineStage.VERDICT if ready or state == CaseState.COMPLETE else PipelineStage.SIMULATE
    return CaseRecord(index + 100, "campaign", "class", index, index, 1, stage, state, 1, None, None, None, {}, None, NOW, NOW, None if state == CaseState.ACTIVE else NOW)


def make_class(
    quota: int = 3, budget: Optional[int] = 2, complete: int = 0, dropped: int = 0, in_flight: int = 0, state: CampaignClassState = CampaignClassState.OPEN, class_id: str = "class"
) -> ClassRecord:
    return ClassRecord("campaign", class_id, "0" * 64, 2, 0, quota, budget, complete, dropped, in_flight, state, None, NOW, NOW, None)


# Decisions


def test_a_ready_case_completes_only_when_every_lower_case_is_final():
    cases = [make_case(0), make_case(1, ready=True)]
    assert decide_class(cases, quota=2, failure_budget=1, dropped=0).complete == ()
    cases[0] = make_case(0, CaseState.DROPPED)
    decision = decide_class(cases, quota=2, failure_budget=1, dropped=1)
    assert decision.complete == (101,) and decision.close is None


def test_the_class_completes_at_its_quota_and_cuts_what_runs_above():
    cases = [make_case(0, CaseState.COMPLETE), make_case(1, CaseState.DROPPED), make_case(2, ready=True), make_case(3), make_case(4, ready=True)]
    decision = decide_class(cases, quota=2, failure_budget=2, dropped=1)
    assert decision.complete == (102,)
    assert decision.cancel == (103, 104)  # a ready case above the quota is cut too
    assert decision.close == CampaignClassState.COMPLETE
    assert "up to index 2" in decision.reason


def test_the_class_is_abandoned_once_its_drops_exceed_the_budget():
    cases = [make_case(0, CaseState.DROPPED), make_case(1, CaseState.FAILED), make_case(2, ready=True), make_case(3)]
    decision = decide_class(cases, quota=3, failure_budget=1, dropped=2)
    assert decision.close == CampaignClassState.ABANDONED
    assert decision.complete == (102,) and decision.cancel == (103,)
    assert "exceed the failure budget of 1" in decision.reason


def test_a_class_at_its_budget_stays_open():
    cases = [make_case(0, CaseState.DROPPED), make_case(1)]
    assert decide_class(cases, quota=1, failure_budget=1, dropped=1).close is None


def test_a_class_with_an_unlimited_budget_is_never_abandoned():
    cases = [make_case(index, CaseState.DROPPED if index % 2 else CaseState.FAILED) for index in range(50)] + [make_case(50)]
    decision = decide_class(cases, quota=1, failure_budget=None, dropped=50)
    assert decision.close is None and decision.cancel == ()
    cases[-1] = make_case(50, ready=True)
    decision = decide_class(cases, quota=1, failure_budget=None, dropped=50)
    assert decision.complete == (150,) and decision.close == CampaignClassState.COMPLETE


# Starting cases


def test_a_class_runs_its_quota_and_replaces_a_drop_only_once_it_is_final():
    assert startable(make_class(quota=3, budget=2)) == 3  # no case beyond the quota
    assert startable(make_class(quota=3, budget=2, in_flight=3)) == 0
    assert startable(make_class(quota=3, budget=2, dropped=1, in_flight=2)) == 1  # the drop is replaced
    assert startable(make_class(quota=3, budget=2, complete=2, in_flight=1)) == 0
    assert startable(make_class(quota=3, budget=0)) == 3
    assert startable(make_class(quota=3, budget=1, dropped=2)) == 0  # out of budget
    assert startable(make_class(state=CampaignClassState.COMPLETE)) == 0


def test_an_unlimited_budget_replaces_every_drop():
    assert make_class(budget=None, dropped=7).failure_budget_left is None
    assert startable(make_class(quota=3, budget=None, dropped=40, complete=1, in_flight=1)) == 1
    assert startable(make_class(quota=3, budget=None, dropped=40, complete=1, in_flight=2)) == 0
    assert startable(make_class(quota=3, budget=None, dropped=40, state=CampaignClassState.COMPLETE)) == 0


def test_new_cases_go_round_robin_in_index_order():
    classes = [make_class(quota=1, budget=0, class_id="a"), make_class(quota=3, budget=0, class_id="b")]
    assert plan_new_cases(classes, {"b": 5}, room=3) == [("a", 0), ("b", 5), ("b", 6)]
    assert plan_new_cases(classes, {}, room=10) == [("a", 0), ("b", 0), ("b", 1), ("b", 2)]


def test_backpressure_stops_new_cases_while_any_stage_is_at_its_cap():
    caps = QueueDepthCaps(generate_scene=4, simulate=2)
    assert Backpressure(caps, {PipelineStage.GENERATE_SCENE: 1}).room_for_new_cases() == 3
    pressure = Backpressure(caps, {PipelineStage.SIMULATE: 2})
    assert pressure.full_stages() == [PipelineStage.SIMULATE] and pressure.room_for_new_cases() == 0


# The selected set does not depend on the order cases finish in


def _run_class(outcomes: Dict[int, str], quota: int, budget: Optional[int], rng: random.Random, room: int) -> tuple:
    """Plays a class with the given outcome per index (complete or dropped), finishing in-flight cases in a random order."""
    cases: Dict[int, CaseRecord] = {}
    state = CampaignClassState.OPEN
    while state == CampaignClassState.OPEN:
        complete = sum(1 for case in cases.values() if case.state == CaseState.COMPLETE)
        dropped = sum(1 for case in cases.values() if case.state == CaseState.DROPPED)
        in_flight = sum(1 for case in cases.values() if case.state == CaseState.ACTIVE)
        record = make_class(quota, budget, complete, dropped, in_flight)
        for index in range(len(cases), len(cases) + min(room, startable(record))):
            cases[index] = make_case(index)
        running = [case for case in cases.values() if case.state == CaseState.ACTIVE and case.stage != PipelineStage.VERDICT]
        if running:
            case = rng.choice(running)
            outcome = outcomes.get(case.case_index, "complete")
            cases[case.case_index] = replace(case, stage=PipelineStage.VERDICT) if outcome == "complete" else replace(case, state=CaseState.DROPPED)
        dropped = sum(1 for case in cases.values() if case.state == CaseState.DROPPED)
        decision = decide_class(list(cases.values()), quota, budget, dropped)
        by_id = {case.case_id: case for case in cases.values()}
        for case_id in decision.complete:
            cases[by_id[case_id].case_index] = replace(by_id[case_id], state=CaseState.COMPLETE)
        for case_id in decision.cancel:
            cases[by_id[case_id].case_index] = replace(by_id[case_id], state=CaseState.CANCELLED)
        if decision.close is not None:
            state = decision.close
        assert running or decision.close is not None, "the class stopped moving"
    selected = tuple(sorted(case.case_index for case in cases.values() if case.state == CaseState.COMPLETE))
    if state == CampaignClassState.COMPLETE:
        assert not any(case.state == CaseState.CANCELLED for case in cases.values()), "a case above the quota was started"
    return state, selected


def _expected(outcomes: Dict[int, str], quota: int, budget: Optional[int]) -> tuple:
    selected: List[int] = []
    drops = 0
    index = 0
    while len(selected) < quota:
        if outcomes.get(index, "complete") == "complete":
            selected.append(index)
        else:
            drops += 1
            if budget is not None and drops > budget:
                return CampaignClassState.ABANDONED
        index += 1
    return CampaignClassState.COMPLETE, tuple(selected)


@pytest.mark.parametrize(
    "outcomes, quota, budget",
    [
        ({}, 5, 2),
        ({1: "dropped", 4: "dropped"}, 5, 3),
        ({0: "dropped", 1: "dropped", 2: "dropped", 6: "dropped"}, 4, 4),
        ({2: "dropped", 3: "dropped", 5: "dropped"}, 3, 2),
        ({0: "dropped"}, 1, 0),
        ({index: "dropped" for index in range(12)}, 2, None),  # an unlimited budget outlasts any run of drops
        ({1: "dropped", 3: "dropped", 4: "dropped", 5: "dropped", 9: "dropped"}, 4, None),
    ],
)
def test_the_selected_cases_do_not_depend_on_the_completion_order(outcomes, quota, budget):
    expected = _expected(outcomes, quota, budget)
    for seed in range(40):
        for room in (1, 3, 100):
            state, selected = _run_class(outcomes, quota, budget, random.Random(seed), room)
            if expected == CampaignClassState.ABANDONED:
                assert state == CampaignClassState.ABANDONED, (seed, room)
            else:
                assert (state, selected) == expected, (seed, room)


def test_an_item_class_runs_its_one_case_once():
    assert startable(make_class(quota=1, budget=0, class_id="item/0")) == 1
    assert startable(make_class(quota=1, budget=0, class_id="item/0", in_flight=1)) == 0
    assert startable(make_class(quota=1, budget=0, class_id="item/0", dropped=1)) == 0  # never a second run of the same item


def test_backpressure_counts_new_cases_at_the_first_stage():
    caps = QueueDepthCaps(generate_scene=16, simulate=3, monitor=2)
    assert Backpressure(caps, {PipelineStage.SIMULATE: 1}, PipelineStage.SIMULATE).room_for_new_cases() == 2
    assert Backpressure(caps, {PipelineStage.GENERATE_TRAJECTORIES: 4}, PipelineStage.GENERATE_TRAJECTORIES).room_for_new_cases() == 12
    pressure = Backpressure(caps, {PipelineStage.MONITOR_SCENE: 2})  # the scene monitor shares the monitor's cap
    assert pressure.full_stages() == [PipelineStage.MONITOR_SCENE] and pressure.room_for_new_cases() == 0
