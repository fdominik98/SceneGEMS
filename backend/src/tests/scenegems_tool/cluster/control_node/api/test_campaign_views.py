"""The views of a campaign as the operator API answers them: what the detail's totals count."""

from datetime import datetime, timezone

from scenegems_tool.cluster.control_node.api.campaign_views import campaign_detail_view
from scenegems_tool.persistence.schema import CampaignActualState, CampaignDesiredState
from scenegems_tool.persistence.stores import EXPLORATION_CLASS_ID, EXPLORED_CLASS_PREFIX, CampaignRecord

AT = datetime(2026, 11, 24, 14, 30, tzinfo=timezone.utc)
CAMPAIGN = CampaignRecord("c1", "moos planner", CampaignDesiredState.RUNNING, CampaignActualState.COMPLETED, None, 1, {}, AT, AT, AT, AT)


def fec(fec_id, state="open", quota=1, complete=0, dropped=0, in_flight=0, verdicts=None):
    """A FEC as class_view writes it, with the fields the totals read."""
    return {"fec_id": fec_id, "state": state, "quota": quota, "complete": complete, "dropped": dropped, "in_flight": in_flight, "verdicts": verdicts or {}}


def test_the_totals_sum_the_fecs_and_their_verdicts_over_every_run():
    classes = [
        fec("2vessel_0obstacle_scenarios/fec0", "complete", quota=2, complete=2, verdicts={"0": {"passed": 1, "failed": 1}, "1": {"passed": 2}}),
        fec("2vessel_0obstacle_scenarios/fec1", "abandoned", quota=2, dropped=3),
        fec("2vessel_0obstacle_scenarios/fec2", quota=3, complete=1, in_flight=2, verdicts={"0": {"failed": 1}}),
    ]
    view = campaign_detail_view(CAMPAIGN, classes)
    assert view["totals"] == {
        "fecs": 3,
        "fecs_open": 1,
        "fecs_complete": 1,
        "fecs_abandoned": 1,
        "quota": 7,
        "complete": 3,
        "dropped": 3,
        "in_flight": 2,
        "verdicts": {"passed": 3, "failed": 2},
    }
    assert view["fecs"] == classes and view["name"] == "moos planner"


def test_the_totals_leave_out_the_class_of_the_design_space_exploration_which_stays_listed():
    # The campaign in which every scenario case failed or dropped: its one complete case was the exploration's
    exploration = fec(EXPLORATION_CLASS_ID, "complete", quota=1, complete=1)
    explored = [fec(f"{EXPLORED_CLASS_PREFIX}{index:05d}", "abandoned", quota=1, dropped=1) for index in range(28)]
    view = campaign_detail_view(CAMPAIGN, [exploration, *explored])
    assert view["totals"] == {
        "fecs": 28,
        "fecs_open": 0,
        "fecs_complete": 0,
        "fecs_abandoned": 28,
        "quota": 28,
        "complete": 0,
        "dropped": 28,
        "in_flight": 0,
        "verdicts": {},
    }
    assert [entry["fec_id"] for entry in view["fecs"]][0] == EXPLORATION_CLASS_ID and len(view["fecs"]) == 29


def test_an_entry_that_is_still_exploring_has_no_fec_and_no_case_to_count():
    view = campaign_detail_view(CAMPAIGN, [fec(EXPLORATION_CLASS_ID, quota=1, in_flight=1)])
    assert (view["totals"]["fecs"], view["totals"]["quota"], view["totals"]["in_flight"]) == (0, 0, 0)
