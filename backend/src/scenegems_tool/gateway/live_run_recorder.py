"""Live sessions of the workbench recorded as workbench entries (design doc 6.4).

The gateway runs inside master-api, whose build_master hands it a LiveRunRecorder on the master's
assurance stores, artifact store and pipeline engine (cluster/master/server.py). When a live
simulation starts, the recorder stores the loaded trajectories and creates a workbench entry
(origin live_session, steps [simulation], one run of one repeat judged post_hoc, frames kept) with
them as its one input item, item/0. When the run ends (completed, stopped, torn down,
disconnected) it stores the simulated states as the run's state log, a Trajectories document, and
records the run through PipelineEngine.record_external_run, whose post-hoc monitor job gives the
verdict and the frames. A run without a simulated state, or one whose recording failed, stops its
entry, which would otherwise stay running without a case. The browser follows all of it through
`run_recording` messages; a gateway started on its own has no recorder and says so (unavailable).

Threads: the live session reports from the event loop and from its MQTT client's thread.
LiveSessionRecording and LiveRunRecording only collect states under a lock and hand everything
else to the master's event loop (the gateway's own loop: both listeners of the master share it),
where the database and file work runs in worker threads and record_external_run takes the
engine's turn.
"""

import asyncio
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set

import anyio

from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from scenegems_tool.gateway.protocol import RunRecordingMessage, RunRecordingStatus, make_run_recording_message
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig, SimulationInstanceConfig

if TYPE_CHECKING:
    from scenegems_tool.assurance.pipeline.case_machine import RecordedRun
    from scenegems_tool.assurance.pipeline.pipeline_engine import PipelineEngine
    from scenegems_tool.persistence.artifacts.recorded_artifacts import RecordedArtifacts
    from scenegems_tool.persistence.stores import AssuranceStores

logger = logging.getLogger(__name__)

ITEM_CLASS_ID = "item/0"
INPUT_ROLE = "input:0"  # the entry's reference to its input item (design doc 6.3)
JSON_MEDIA_TYPE = "application/json"
MAX_SEED = 2**31 - 1
MAX_NAME_LENGTH = 256
UNAVAILABLE_MESSAGE = "this gateway runs without a master, so it has nowhere to save the run"
NO_STATE_MESSAGE = "the run ended before it simulated a state"

Report = Callable[[RunRecordingMessage], None]


@dataclass(frozen=True)
class LiveRunSetup:
    """What the session knows of its runs when it is set up: the loaded trajectories and the instance."""

    scenario_name: str  # the loaded file's name
    trajectories: Trajectories  # as the session simulates them
    simulation_config: SimulationInstanceConfig
    time_step: int

    def stack(self) -> Dict[str, Any]:
        """The run's stack per vessel, as the session configured it."""
        config = self.simulation_config
        vessels = {}
        for agent_id, vessel in config.vessels.items():
            vessels[agent_id] = {
                "context": vessel.context.value,
                "asv_software": vessel.stack.asv_software.value,
                "control_layer": vessel.stack.control_layer.value,
                "simulation_layer": vessel.stack.simulation_layer.value,
                "adapter_ids": list(vessel.adapter_ids),
                "agent_name": None if vessel.connection is None else vessel.connection.agent_name,
            }
        return {"simulation_layer": config.simulation_layer.value, "speedup": int(config.speedup), "vessels": vessels}

    def environment(self) -> Dict[str, Any]:
        """The environment in the shape of a campaign run's environment section."""
        return environment_settings(self.simulation_config.environment)

    def repeatability_tier(self) -> Optional[str]:
        """The resolver's tier of the instance at its speedup; none for real vessels and Mission Planner."""
        from scenegems_tool.vessel_stack.registry.catalog import default_resolver

        tier = default_resolver().resolve_instance(self.simulation_config).repeatability_tier
        return None if tier is None else tier.value


def environment_settings(environment: EnvironmentConfig) -> Dict[str, Any]:
    wave = environment.wave
    return {
        "wind_vector": [float(component) for component in environment.wind_vector],
        "waves": (
            {"amplitude": float(wave.amplitude), "period": float(wave.period), "steepness": float(wave.steepness), "direction": [float(component) for component in wave.direction]}
            if environment.waves_requested
            else None
        ),
    }


@dataclass(frozen=True)
class OpenedEntry:
    """The workbench entry of a live run and the reference of its input item (wire form)."""

    campaign_id: str
    item: Dict[str, Any]


class LiveRunRecorder:
    """Creates the workbench entries of live runs and records their runs; its coroutines run on the master's event loop."""

    def __init__(
        self,
        stores: "AssuranceStores",
        artifacts: "RecordedArtifacts",
        pipeline: "PipelineEngine",
        max_bytes: Optional[int] = None,
        announce: Optional[Callable[[Set[str]], None]] = None,
        seeds: Callable[[], int] = lambda: secrets.randbelow(MAX_SEED + 1),
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.stores = stores
        self.artifacts = artifacts
        self.pipeline = pipeline
        self.max_bytes = max_bytes
        self._announce = announce
        self._seeds = seeds
        self._clock = clock

    async def open_entry(self, setup: LiveRunSetup) -> OpenedEntry:
        """Stores the loaded trajectories and creates the run's workbench entry, started."""
        entry = await anyio.to_thread.run_sync(self._open, setup)
        self._changed(entry.campaign_id)
        self.pipeline.wake()
        return entry

    async def record_run(self, entry: OpenedEntry, setup: LiveRunSetup, states: List[ConcreteScene], durations_s: Optional[Dict[str, float]] = None) -> "RecordedRun":
        """Stores the states as the run's state log and records the run on the entry; ValueError without a state."""
        from scenegems_tool.assurance.pipeline.case_machine import ExternalRun

        if not states:
            raise ValueError(NO_STATE_MESSAGE)
        state_log, tier = await anyio.to_thread.run_sync(self._state_log, setup, states)
        run = ExternalRun(
            state_log=state_log,
            stack=setup.stack(),
            environment=setup.environment(),
            dt=float(setup.time_step),
            steps=len(states) - 1,
            repeatability_tier=tier,
            durations_s=dict(durations_s or {}),
        )
        return await self.pipeline.record_external_run(entry.campaign_id, run, class_id=ITEM_CLASS_ID)

    async def stop_entry(self, campaign_id: str) -> None:
        """Stops an entry that got no recorded run, so it does not stay running without a case."""
        from scenegems_tool.persistence.schema import CampaignDesiredState

        await anyio.to_thread.run_sync(self.stores.campaigns.set_desired_state, campaign_id, CampaignDesiredState.STOPPED)
        self._changed(campaign_id)
        self.pipeline.wake()

    # Worker threads

    def _open(self, setup: LiveRunSetup) -> OpenedEntry:
        from scenegems_tool.assurance.campaign import campaign_config_from_dict, validate_campaign_config
        from scenegems_tool.assurance.campaign.campaign_config import with_domain_defaults
        from scenegems_tool.persistence.schema import ArtifactHolderKind, CampaignDesiredState, CampaignKind, CampaignOrigin

        item = self._store(setup.trajectories)
        # The entry judges its run with the cluster's domain configuration, as every other workbench entry
        saved = self.stores.domain.current()
        config = campaign_config_from_dict(with_domain_defaults(self._config(setup, item), None if saved is None else saved.contents()))
        validated = validate_campaign_config(config, artifact_exists=lambda sha256: self.artifacts.record(sha256) is not None, read_artifact=self.artifacts.store.read)
        campaign = self.stores.campaigns.create_campaign(
            validated.config.name,
            validated.config_json,
            validated.config_hash,
            validated.classes,
            desired_state=CampaignDesiredState.RUNNING,
            kind=CampaignKind.WORKBENCH,
            origin=CampaignOrigin.LIVE_SESSION,
        )
        self.artifacts.records.add_reference(item["sha256"], ArtifactHolderKind.CAMPAIGN, campaign.campaign_id, INPUT_ROLE, campaign.campaign_id)
        return OpenedEntry(campaign.campaign_id, item)

    def _config(self, setup: LiveRunSetup, item: Dict[str, Any]) -> Dict[str, Any]:
        name = f"Live session: {setup.scenario_name} ({self._clock().strftime('%Y-%m-%d %H:%M')})"[:MAX_NAME_LENGTH]
        return {
            "format": 2,
            "name": name,
            "steps": ["simulation"],
            "input": {"items": [{"name": f"Loaded trajectories of {setup.scenario_name}"[:MAX_NAME_LENGTH], "ref": item, "source": {"file": setup.scenario_name[:512]}}]},
            "execution": {"runs": [{"name": "live session", "environment": setup.environment(), "monitor": "post_hoc"}]},
            "policy": {"keep_frames": True, "seed": self._seeds()},
        }

    def _state_log(self, setup: LiveRunSetup, states: List[ConcreteScene]):
        return self._store(Trajectories(list(states), setup.time_step)), setup.repeatability_tier()

    def _store(self, trajectories: Trajectories) -> Dict[str, Any]:
        """Stores a Trajectories document; its reference in wire form."""
        from scenegems_tool.cluster.protocol.artifacts import ArtifactContent, ArtifactKind, encode_document

        data = encode_document(trajectories.to_dict(), ArtifactContent.JSON)
        recorded = self.artifacts.put(data, ArtifactKind.TRAJECTORIES.value, JSON_MEDIA_TYPE, max_bytes=self.max_bytes)
        return {"sha256": recorded.record.artifact_hash, "size_bytes": recorded.stored.size_bytes, "kind": ArtifactKind.TRAJECTORIES.value, "media_type": JSON_MEDIA_TYPE, "pointer": None}

    def _changed(self, campaign_id: str) -> None:
        if self._announce is None:
            return
        try:
            self._announce({campaign_id})
        except Exception:
            logger.exception("Cannot announce the change of entry %s", campaign_id)


class LiveRunRecording:
    """One run of a live session, from its start to its recorded run (or its stopped entry).

    add_state and end are safe from any thread; the recording itself runs on the loop.
    """

    def __init__(self, recorder: LiveRunRecorder, setup: LiveRunSetup, loop: asyncio.AbstractEventLoop, report: Report):
        self.recorder = recorder
        self.setup = setup
        self.loop = loop
        self.report = report
        self._lock = threading.Lock()
        self._states: List[ConcreteScene] = []
        self._ended = asyncio.Event()
        self._end_reason: Optional[str] = None
        self._started_at: Optional[float] = None
        self._ended_at: Optional[float] = None
        self.future = asyncio.run_coroutine_threadsafe(self._record(), loop)

    @property
    def is_ended(self) -> bool:
        return self._end_reason is not None

    def add_state(self, scene: ConcreteScene) -> None:
        with self._lock:
            if self._end_reason is not None:
                return
            if self._started_at is None:
                self._started_at = time.monotonic()
            self._states.append(scene)

    def end(self, reason: str) -> None:
        with self._lock:
            if self._end_reason is not None:
                return
            self._end_reason = reason
            self._ended_at = time.monotonic()
        try:
            self.loop.call_soon_threadsafe(self._ended.set)
        except RuntimeError:  # the loop is closed: the master stops
            logger.warning("The live run ended (%s) after the event loop closed; it is not recorded", reason)

    async def _record(self) -> Optional["RecordedRun"]:
        self._report("recording")
        try:
            entry = await self.recorder.open_entry(self.setup)
        except Exception as error:
            logger.exception("Cannot create the workbench entry of a live run")
            self.end("failed")
            self._report("failed", message=f"the workbench entry could not be created: {_reason(error)}")
            return None
        self._report("recording", entry.campaign_id)
        await self._ended.wait()
        with self._lock:
            states, reason = list(self._states), self._end_reason
            durations = {} if self._started_at is None or self._ended_at is None else {"running_s": round(self._ended_at - self._started_at, 3)}
        if not states:
            await self._stop(entry)
            self._report("failed", entry.campaign_id, message=f"{NO_STATE_MESSAGE} ({reason}), so its entry is stopped")
            return None
        try:
            recorded = await self.recorder.record_run(entry, self.setup, states, durations)
        except Exception as error:
            logger.exception("Cannot record the live run on entry %s", entry.campaign_id)
            await self._stop(entry)
            self._report("failed", entry.campaign_id, message=f"the run could not be recorded ({_reason(error)}), so its entry is stopped")
            return None
        monitored = "the post-hoc monitor judges it" if recorded.monitor_key is not None else "it is not monitored"
        self._report("saved", entry.campaign_id, recorded.case_id, f"{len(states)} states ({reason}); {monitored}")
        return recorded

    async def _stop(self, entry: OpenedEntry) -> None:
        try:
            await self.recorder.stop_entry(entry.campaign_id)
        except Exception:
            logger.exception("Cannot stop the workbench entry %s of a live run", entry.campaign_id)

    def _report(self, status: RunRecordingStatus, campaign_id: Optional[str] = None, case_id: Optional[int] = None, message: Optional[str] = None) -> None:
        try:
            self.report(make_run_recording_message(status, campaign_id, case_id, message))
        except Exception:
            logger.exception("Cannot report the live run's recording")


def _reason(error: Exception) -> str:
    reasons = getattr(error, "reasons", None)
    if reasons:
        return "; ".join(str(reason) for reason in reasons)
    return str(error).strip() or error.__class__.__name__


class LiveSessionRecording:
    """Follows the runs of one live simulation session (its LiveRunListener) and records each one.

    Without a recorder (the gateway on its own) every run is reported unavailable. Reports reach
    the browser through the loop, since the session's send queue is not thread-safe.
    """

    def __init__(self, recorder: Optional[LiveRunRecorder], setup: LiveRunSetup, loop: asyncio.AbstractEventLoop, send: Report):
        self.recorder = recorder
        self.setup = setup
        self.loop = loop
        self._send = send
        self._lock = threading.Lock()
        self._run: Optional[LiveRunRecording] = None
        self._unrecorded_run = False  # a run reported unavailable is under way
        self._closed = False
        self.recordings: List[LiveRunRecording] = []

    def run_started(self) -> None:
        with self._lock:
            if self._closed or self._unrecorded_run or (self._run is not None and not self._run.is_ended):
                return
            if self.recorder is None:
                self._unrecorded_run = True
                self._report(make_run_recording_message("unavailable", message=UNAVAILABLE_MESSAGE))
                return
            self._run = LiveRunRecording(self.recorder, self.setup, self.loop, self._report)
            self.recordings.append(self._run)

    def state_simulated(self, clock: float, scene: ConcreteScene) -> None:  # noqa: ARG002 (the states come in clock order)
        with self._lock:
            run = self._run
        if run is not None:
            run.add_state(scene)

    def run_ended(self) -> None:
        self._end("completed", closing=False)

    def session_ended(self, reason: str) -> None:
        self._end(reason, closing=True)

    def _end(self, reason: str, closing: bool) -> None:
        with self._lock:
            run, self._run = self._run, None
            self._unrecorded_run = False
            self._closed = self._closed or closing
        if run is not None:
            run.end(reason)

    def _report(self, message: RunRecordingMessage) -> None:
        try:
            self.loop.call_soon_threadsafe(self._send, message)
        except RuntimeError:  # the loop is closed
            logger.warning("Cannot report the live run's recording (%s): the event loop is closed", message["status"])
