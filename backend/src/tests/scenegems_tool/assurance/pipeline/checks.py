"""Checks every campaign test ends with: counts agree with the cases, quotas are exact, nothing is left running."""

from collections import Counter
from typing import Dict

from scenegems_tool.assurance.pipeline.pipeline_queries import UNFINISHED_JOB_STATES
from scenegems_tool.persistence.schema import CampaignClassState, CaseState
from scenegems_tool.persistence.stores import EXPLORATION_CLASS_ID, EXPLORED_CLASS_PREFIX, AssuranceStores


def assert_consistent(stores: AssuranceStores, campaign_id: str, finished: bool = True) -> Dict[str, int]:
    """The campaign's books agree; returns the case count per state."""
    counted = stores.cases.class_counts_from_cases(campaign_id)
    classes = stores.cases.list_classes(campaign_id)
    for record in classes:
        counts = counted[record.class_id]
        assert (record.complete_count, record.dropped_count, record.in_flight_count) == (counts.complete, counts.dropped, counts.in_flight), record.class_id
    cases = stores.cases.list_cases(campaign_id)
    for class_id in {case.class_id for case in cases}:
        indexes = sorted(case.case_index for case in cases if case.class_id == class_id)
        assert indexes == list(range(len(indexes))), f"the cases of {class_id} are not a prefix of the indexes: {indexes}"
    coverage = {entry.class_id: entry for entry in stores.results.coverage(campaign_id)}
    config = stores.campaigns.config_version(campaign_id).config
    steps = config.get("steps", ["scene_generation", "trajectory_generation", "simulation"])  # format 1 runs the full chain
    runs = len(config["execution"]["runs"]) if "simulation" in steps else 0
    monitored = sum(
        1 for step, section in (("scene_generation", "scene_generation"), ("trajectory_generation", "trajectories")) if step in steps and config.get(section, {}).get("monitor") == "post_hoc"
    )
    explores = "design_space_exploration" in steps
    only_explores = steps == ["design_space_exploration"]
    for record in classes:
        if only_explores and record.class_id.startswith(EXPLORED_CLASS_PREFIX):
            assert (record.state, record.complete_count, record.in_flight_count) == (CampaignClassState.COMPLETE, 0, 0), "an explored FEC of a campaign that only explores is complete without a case"
            continue
        if record.state == CampaignClassState.COMPLETE:
            assert record.complete_count == record.quota, record.class_id
            if explores and record.class_id == EXPLORATION_CLASS_ID:
                continue  # the exploration case has no verdict
            for run_index in range(runs):
                assert coverage[record.class_id].verdict_count(run_index=run_index) == record.quota, (record.class_id, run_index)
        assert record.complete_count <= record.quota
    verdict_cases = Counter(verdict.case_id for verdict in stores.results.list_verdicts(campaign_id, limit=None))
    complete = {case.case_id for case in cases if case.state == CaseState.COMPLETE and not (explores and case.class_id == EXPLORATION_CLASS_ID)}
    assert set(verdict_cases) == (complete if runs + monitored else set()), "verdicts belong to complete cases only, one per run and monitored generation step"
    assert all(count == runs + monitored for count in verdict_cases.values())
    if finished:
        assert stores.pipeline.job_ids_of_campaign(campaign_id, UNFINISHED_JOB_STATES) == []
        assert stores.pipeline.intents_without_job(campaign_id) == []
        assert all(case.state.is_final for case in cases)
    return dict(Counter(case.state.value for case in cases))
