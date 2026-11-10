"""The pipeline engine on a real database, with the real control plane and a fake fleet.

A Harness holds the stores, a ControlPlane (fixed expected fingerprints, no timers), the
engine on it, a FakeExecutor that claims from the job store, a manual clock and an event
loop. drive() alternates engine ticks and executor rounds until the campaign is finished.
crash() ends an engine's lock connection as a dead control node's would, and replace_engine()
starts the engine of a restarted control node; every engine's lock is released at the end.
"""

import asyncio
import hashlib
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Mapping, Optional, Union

import pytest

from scenegems_tool.assurance.campaign import campaign_config_from_dict, validate_campaign_config
from scenegems_tool.assurance.pipeline.pipeline_engine import EngineSettings, PipelineEngine, TickReport, WorkerNodeAvailability
from scenegems_tool.cluster.control_node.control_plane import ControlPlane
from scenegems_tool.cluster.control_node.scheduling.fingerprint_policy import ExpectedFingerprints
from scenegems_tool.persistence.schema import CampaignDesiredState
from scenegems_tool.persistence.stores import AssuranceStores, CampaignRecord, JobStore, WorkerNodeStore
from tests.scenegems_tool.assurance.pipeline.fake_executor import EXPECTED, FakeExecutor
from tests.scenegems_tool.persistence.stores.builders import ManualClock

CLASS_A = "2vessel_0obstacle_scenarios/fec0"
CLASS_B = "2vessel_0obstacle_scenarios/fec1"
CLASS_C = "3vessel_0obstacle_scenarios/fec0"


def config_dict(classes=(CLASS_A,), quota: int = 2, failure_budget: Union[int, str] = 2, runs: Optional[List[Dict[str, Any]]] = None, **sections: Any) -> Dict[str, Any]:
    """A small campaign: the classes with one quota and budget, straight trajectories unless sections say otherwise."""
    config: Dict[str, Any] = {
        "name": "pipeline test",
        "scope": [{"classes": list(classes), "quota": quota, "failure_budget": failure_budget}],
        "trajectories": {"generator": "straight", "timespan_s": 10},
        "execution": {"runs": runs or [{"monitor": "post_hoc"}]},
        "policy": {"seed": 7},
    }
    config.update(sections)
    return config


def format2_dict(steps, classes=(CLASS_A,), quota: int = 2, failure_budget: Union[int, str] = 2, runs: Optional[List[Dict[str, Any]]] = None, **sections: Any) -> Dict[str, Any]:
    """config_dict in format 2 with the given steps; a campaign that starts after scene generation has no scope."""
    config = config_dict(classes, quota, failure_budget, runs)
    config.update(format=2, steps=list(steps))
    if steps[0] != "scene_generation":
        del config["scope"]
    config.update(sections)
    return config


def input_ref(data: bytes, kind: str, pointer: Optional[str] = None, media_type: str = "application/json") -> Dict[str, Any]:
    """An input reference to the given content, as a format 2 config names it."""
    return {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data), "kind": kind, "media_type": media_type, "pointer": pointer}


def create_campaign(stores: AssuranceStores, config: Mapping[str, Any], desired: CampaignDesiredState = CampaignDesiredState.RUNNING) -> CampaignRecord:
    validated = validate_campaign_config(campaign_config_from_dict(config))
    return stores.campaigns.create_campaign(validated.config.name, validated.config_json, validated.config_hash, validated.classes, desired_state=desired)


@dataclass
class Harness:
    stores: AssuranceStores
    job_store: JobStore
    worker_node_store: WorkerNodeStore
    clock: ManualClock
    loop: asyncio.AbstractEventLoop
    plane: ControlPlane
    executor: FakeExecutor
    settings: EngineSettings
    engine: PipelineEngine = None
    worker_nodes: List[WorkerNodeAvailability] = field(default_factory=list)
    reports: List[TickReport] = field(default_factory=list)
    tick_seconds: float = 0.0  # wall time spent in engine ticks
    engines: List[PipelineEngine] = field(default_factory=list)  # every engine made, for the release at the end

    def new_engine(self, settings: Optional[EngineSettings] = None) -> PipelineEngine:
        """An engine on the same database, as a control node process builds it."""
        engine = PipelineEngine(
            self.stores,
            self.job_store,
            submit=self.plane.submit,
            cancel=self.plane.cancel,
            expected=self.plane.expected.current,
            worker_nodes=lambda: list(self.worker_nodes),
            clock=self.clock,
            settings=settings or self.settings,
        )
        self.engines.append(engine)
        return engine

    def crash(self, engine: Optional[PipelineEngine] = None) -> None:
        """The engine's control node dies: its lock connection ends, nothing else is cleaned up."""
        (engine or self.engine).leadership.release()

    def replace_engine(self, settings: Optional[EngineSettings] = None) -> PipelineEngine:
        """The control node dies and restarts: the old engine crashes, a new one takes over."""
        self.crash()
        self.engine = self.new_engine(settings)
        return self.engine

    def release_all(self) -> None:
        for engine in self.engines:
            engine.leadership.release()

    def run(self, coroutine):
        return self.loop.run_until_complete(coroutine)

    def tick(self, engine: Optional[PipelineEngine] = None) -> TickReport:
        started = time.perf_counter()
        report = self.run((engine or self.engine).tick())
        self.tick_seconds += time.perf_counter() - started
        self.reports.append(report)
        return report

    def settle(self, engine: Optional[PipelineEngine] = None, limit: int = 50) -> TickReport:
        """Ticks until a tick read no event and submitted nothing."""
        for _ in range(limit):
            report = self.tick(engine)
            if report.stopped or (report.events_read == 0 and report.submitted == 0 and report.cases_started == 0 and report.cancelled == 0):
                return report
        raise AssertionError(f"the engine did not settle in {limit} ticks")

    def campaign(self, campaign_id: str) -> CampaignRecord:
        return self.stores.campaigns.get_campaign(campaign_id)

    def drive(self, campaign_id: str, rounds: int = 200, rng: Optional[random.Random] = None, per_round: Optional[int] = None, engine: Optional[PipelineEngine] = None) -> CampaignRecord:
        """Engine ticks and executor rounds until the campaign is finished or nothing moves."""
        for _ in range(rounds):
            self.settle(engine)
            campaign = self.campaign(campaign_id)
            if campaign.actual_state.is_final:
                return campaign
            if self.executor.run(per_round, rng) == 0:
                self.settle(engine)
                campaign = self.campaign(campaign_id)
                if campaign.actual_state.is_final or self.executor.run(per_round, rng) == 0:
                    return campaign
        return self.campaign(campaign_id)


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def make_harness(session_factory, clock, loop):
    harnesses: List[Harness] = []

    def make(references: bool = False, scripts=None, settings: EngineSettings = EngineSettings(stall_after_s=30.0), **executor_options) -> Harness:
        stores = AssuranceStores.create(session_factory, clock)
        worker_node_store, job_store = WorkerNodeStore(session_factory, clock), JobStore(session_factory, clock)
        plane = ControlPlane("pipeline-control-node", worker_node_store, job_store, ExpectedFingerprints.fixed(EXPECTED), clock=clock)
        executor = FakeExecutor(stores, job_store, worker_node_store, references=references, scripts=scripts, **executor_options)
        harness = Harness(stores, job_store, worker_node_store, clock, loop, plane, executor, settings)
        harness.worker_nodes = [WorkerNodeAvailability(executor.worker_node)]
        harness.engine = harness.new_engine()
        harnesses.append(harness)
        return harness

    yield make
    for harness in harnesses:
        harness.release_all()


@pytest.fixture
def harness(make_harness) -> Harness:
    return make_harness()
