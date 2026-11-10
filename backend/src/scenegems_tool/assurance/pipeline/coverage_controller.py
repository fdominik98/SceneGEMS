"""Which cases a class starts, completes and cuts, so the selected set does not depend on timing.

Cases of a class are numbered 0, 1, 2, ... and started in that order, case k with the seed
campaign seed + k. The outcome of a case (complete, dropped) is a function of its seed, so
the selection below is too:

- A case whose runs all have their verdicts is ready, not complete. Walking the class's cases
  by index, a ready case is completed while fewer than quota cases are complete, and the
  walk stops at the first case still running. Once quota cases are complete the class is
  complete. A complete class has exactly its quota of complete cases, the first quota by
  index that did not drop or fail. Active cases above that point are cancelled, a guard
  only: the start rule below never starts them.
- A class is abandoned when its dropped and failed cases exceed its failure budget. A class
  with an unlimited failure budget (None) is never abandoned: it replaces every drop until
  its quota is complete, or the campaign's stop conditions or the operator end it.
- A class keeps at most quota cases complete or in flight, so no case runs that may not be
  needed. A dropped or failed case is replaced once it is final, while the failure budget
  lasts, so started cases never exceed quota + failure budget and the case set stays a
  prefix of the indexes. The outcome is independent of timing: a class is abandoned
  exactly when, in index order, more cases than its budget drop before quota cases complete.
- An item class (item/<n>, an output of an earlier step or an uploaded file) has quota 1 and
  failure budget 0: the same item gives the same outcome again, so it is not retried.

- The exploration class of a campaign that explores the design space (exploration) has quota 1
  and failure budget 0 too: one case, the exploration. The classes it adds (explored/<n>) are
  decided like catalog classes, with the quota and failure budget of the config.

Backpressure: a new case starts only while every stage has fewer queued jobs (and intents)
of the campaign than its cap; how many start is bounded by the cap of the stage new cases
start at (the first step cases run, or the exploration for the exploration case).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from scenegems_tool.assurance.campaign.campaign_config import QueueDepthCaps
from scenegems_tool.assurance.pipeline.stage_graph import JOB_STAGES
from scenegems_tool.persistence.schema import CampaignClassState, CaseState, PipelineStage
from scenegems_tool.persistence.stores import CaseRecord, ClassRecord


def is_ready(case: CaseRecord) -> bool:
    """Every run of the active case has its verdict pending: the controller may complete it."""
    return case.state == CaseState.ACTIVE and case.stage == PipelineStage.VERDICT


@dataclass(frozen=True)
class ClassDecision:
    complete: Tuple[int, ...] = ()  # ready cases to complete now, in index order
    cancel: Tuple[int, ...] = ()  # active cases to cancel: above the quota, or the class is abandoned
    close: Optional[CampaignClassState] = None  # complete or abandoned
    reason: Optional[str] = None


def decide_class(cases: Sequence[CaseRecord], quota: int, failure_budget: Optional[int], dropped: int) -> ClassDecision:
    """The decision for one open class, from all its cases (any order) and its dropped count (dropped and failed); failure_budget None is unlimited."""
    ordered = sorted(cases, key=lambda case: case.case_index)
    complete = sum(1 for case in ordered if case.state == CaseState.COMPLETE)
    to_complete: List[int] = []
    boundary: Optional[int] = None  # index of the case that brought the class to its quota
    count = 0
    for case in ordered:
        if case.state == CaseState.COMPLETE:
            count += 1
        elif case.state.is_final:
            continue
        elif is_ready(case) and count < quota:
            to_complete.append(case.case_id)
            count += 1
        else:
            break
        if count >= quota:
            boundary = case.case_index
            break
    if boundary is not None:
        cut = tuple(case.case_id for case in ordered if case.case_index > boundary and case.state == CaseState.ACTIVE)
        return ClassDecision(tuple(to_complete), cut, CampaignClassState.COMPLETE, f"{quota} complete cases up to index {boundary}")
    if failure_budget is not None and dropped > failure_budget:
        rest = tuple(case.case_id for case in ordered if case.state == CaseState.ACTIVE and case.case_id not in to_complete)
        reason = f"{dropped} dropped or failed cases exceed the failure budget of {failure_budget} ({complete + len(to_complete)} of {quota} complete)"
        return ClassDecision(tuple(to_complete), rest, CampaignClassState.ABANDONED, reason)
    return ClassDecision(tuple(to_complete))


def startable(record: ClassRecord) -> int:
    """How many more cases the open class may start now: up to its quota complete or in flight, while its failure budget holds."""
    budget_left = record.failure_budget_left
    if record.state != CampaignClassState.OPEN or (budget_left is not None and budget_left < 0):
        return 0
    return max(0, record.quota - record.complete_count - record.in_flight_count)


@dataclass
class Backpressure:
    """The campaign's queued jobs per stage against the config's caps."""

    caps: QueueDepthCaps
    queued: Dict[PipelineStage, int] = field(default_factory=dict)
    first_stage: PipelineStage = PipelineStage.GENERATE_SCENE  # the stage new cases start at

    def full_stages(self) -> List[PipelineStage]:
        return [stage for stage in JOB_STAGES if self.queued.get(stage, 0) >= self.caps.cap(stage)]

    def room_for_new_cases(self) -> int:
        """New cases that fit: each adds a job of the first stage, and no stage may be at its cap."""
        if self.full_stages():
            return 0
        return self.caps.cap(self.first_stage) - self.queued.get(self.first_stage, 0)


def plan_new_cases(classes: Sequence[ClassRecord], next_indexes: Mapping[str, int], room: int) -> List[Tuple[str, int]]:
    """(class id, case index) of the cases to start: round robin over the classes in their order, each in index order, at most room."""
    budgets = {record.class_id: startable(record) for record in classes}
    indexes = {record.class_id: next_indexes.get(record.class_id, 0) for record in classes}
    planned: List[Tuple[str, int]] = []
    while len(planned) < room and any(budgets.values()):
        for record in classes:
            if len(planned) >= room:
                break
            if budgets[record.class_id] > 0:
                planned.append((record.class_id, indexes[record.class_id]))
                indexes[record.class_id] += 1
                budgets[record.class_id] -= 1
    return planned
