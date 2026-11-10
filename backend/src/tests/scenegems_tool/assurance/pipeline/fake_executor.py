"""A fake fleet for the pipeline engine: it claims queued jobs from the real JobStore, as a worker node does, and reports scripted results.

Results have P4.2's shapes. With references the declared result fields are stored in an
in-memory artifact store and replaced by their references, as the worker node runner does with the
artifact store (P4.3), and each upload is recorded with the job's reference to it, as the
control node's artifact route does. The executor resolves the references of every payload it
runs, so a payload that names an artifact nobody stored fails the test.

What a job returns is scripted per case (class id, case index) with a CaseScript: an invalid
scene, a partial or missing trajectory, a failed verdict (of every monitor, or of the scene,
trajectory or run monitor alone), a failure of some stage (retryable or not), the FECs a
design space exploration finds and why it stopped. Unscripted
cases pass every stage; an unscripted exploration finds three FECs. A case of an input class gets its input from the artifact store: the
scenario's text, an item's scene or trajectories, as the worker node resolves them.
"""

import hashlib
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Collection, Dict, List, Mapping, Optional, Tuple

from scenegems_tool.cluster.fingerprints.components import DESIGN_SPACE_EXPLORATION_IMAGE, MONITORING_IMAGE, SCENARIO_EXECUTION_IMAGE, SCENE_GENERATION_IMAGE, TRAJECTORY_GENERATION_IMAGE
from scenegems_tool.cluster.protocol.artifacts import ArtifactRef, is_reference, json_pointer, resolve_references, store_results
from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobType
from scenegems_tool.cluster.protocol.messages import JobResult
from scenegems_tool.cluster.worker_node.jobs.job_types import artifact_input_fields, artifact_result_fields
from scenegems_tool.persistence.schema import ArtifactHolderKind, PipelineStage
from scenegems_tool.persistence.stores import AssuranceStores, JobStore, Lease, WorkerNodeStore
from tests.scenegems_tool.cluster.payloads import trajectories_data
from tests.scenegems_tool.cluster.stack_images import GAZEBO_IMAGE, SITL_IMAGE
from tests.scenegems_tool.persistence.stores.builders import make_hello

EXPECTED = {
    DESIGN_SPACE_EXPLORATION_IMAGE: "fp-exploration",
    SCENE_GENERATION_IMAGE: "fp-scene",
    TRAJECTORY_GENERATION_IMAGE: "fp-trajectory",
    SCENARIO_EXECUTION_IMAGE: "fp-execution",
    MONITORING_IMAGE: "fp-monitoring",
    SITL_IMAGE: "fp-sitl",
    GAZEBO_IMAGE: "fp-gazebo",
}
LEASE_S = 30.0
ALL_SLOTS = {job_type: 100000 for job_type in JobType}
FAILED_RULE = {"relation": "OS_0 - TS_1", "rule": "Rule 14", "first_failed_at": 4}
EVERY_STAGE = tuple(stage for stage in PipelineStage if stage != PipelineStage.VERDICT)


@dataclass
class CaseScript:
    scene_valid: bool = True
    trajectories: str = "complete"  # complete, partial (valid, not complete) or none
    passed: bool = True  # every monitor's verdict (the runs', and the scene's and trajectories' when monitored)
    monitor_passed: Dict[PipelineStage, bool] = field(default_factory=dict)  # a monitor stage's own verdict, over passed
    fail: Optional[PipelineStage] = None  # this stage's job fails for good (not retryable)
    retryable_failures: Dict[PipelineStage, int] = field(default_factory=dict)  # this many retryable failures first
    tier: str = "exact"  # the repeatability tier the simulation reports
    omit_tier: bool = False  # the simulation reports none
    stopped_early_at: Optional[int] = None  # the live monitor's early stop
    explored: Optional[List[str]] = None  # the exploration case: the FEC texts it finds (three FECs when None)
    stop_reason: str = "exhausted"  # the exploration case: why the exploration stopped


class FakeArtifactStore:
    """Content-addressed documents in memory: what the control node's artifact store will hold."""

    def __init__(self) -> None:
        self.documents: Dict[str, bytes] = {}

    def put(self, field, data: bytes) -> ArtifactRef:
        sha = hashlib.sha256(data).hexdigest()
        self.documents[sha] = data
        media_type = "text/plain; charset=utf-8" if field.content.value == "text" else "application/json"  # as the worker node's artifact transport names it
        return ArtifactRef(sha256=sha, size_bytes=len(data), kind=field.kind, media_type=media_type)

    def load(self, reference: ArtifactRef) -> bytes:
        return self.documents[reference.sha256]


@dataclass
class Report:
    job_id: str
    stage: PipelineStage
    outcome: JobOutcome
    case: Tuple[str, int]


class FakeExecutor:
    def __init__(
        self,
        stores: AssuranceStores,
        job_store: JobStore,
        worker_node_store: WorkerNodeStore,
        references: bool = False,
        scripts: Optional[Mapping[Tuple[str, int], CaseScript]] = None,
        worker_node_id: str = "fake-worker-node",
        fingerprints: Optional[Dict[str, str]] = None,
        slots: Optional[Dict[JobType, int]] = None,
        labels: Optional[Dict[str, str]] = None,
        components: Optional[Collection[str]] = None,
    ):
        self.stores = stores
        self.jobs = job_store
        self.worker_node_id = worker_node_id
        self.references = references
        self.scripts: Dict[Tuple[str, int], CaseScript] = dict(scripts or {})
        self.artifacts = FakeArtifactStore()
        self.reports: List[Report] = []
        self.attempts: Dict[str, int] = {}
        self.payloads: Dict[str, Dict[str, Any]] = {}
        self.worker_node = worker_node_store.register(make_hello(worker_node_id, slots=slots or ALL_SLOTS, fingerprints=fingerprints or EXPECTED, labels=labels, components=components))

    # Claiming and reporting

    def claim_all(self, limit: Optional[int] = None, job_types=None) -> List[Lease]:
        """Leases (and accepts) every queued job that is available, up to limit."""
        leases = []
        while limit is None or len(leases) < limit:
            lease = self.jobs.claim_next(self.worker_node_id, LEASE_S, job_types)
            if lease is None:
                break
            leases.append(self.jobs.accept(lease.lease_id, LEASE_S))
        return leases

    def run(self, limit: Optional[int] = None, rng: Optional[random.Random] = None, job_types=None) -> int:
        """Claims every available job and reports their results, in a shuffled order when rng is given."""
        leases = self.claim_all(limit, job_types)
        if rng is not None:
            rng.shuffle(leases)
        for lease in leases:
            self.report(lease)
        return len(leases)

    def report(self, lease: Lease) -> Report:
        job = lease.job
        pipeline_job = self.stores.pipeline.get_by_job_id(job.job_id)
        assert pipeline_job is not None, f"job {job.job_id} is not a pipeline job"
        case = self.stores.cases.get_case(pipeline_job.case_id)
        key = (case.class_id, case.case_index)
        script = self.scripts.get(key, CaseScript())
        payload = resolve_references(job.payload, artifact_input_fields(job.job_type), self.artifacts.load)
        self.payloads[job.job_id] = payload
        stage = pipeline_job.stage
        attempts = self.attempts[job.job_id] = self.attempts.get(job.job_id, 0) + 1
        if script.fail == stage:
            return self._finish(lease, stage, key, JobOutcome.FAILED, error=f"scripted failure of {stage.value}", retryable=False)
        if attempts <= script.retryable_failures.get(stage, 0):
            return self._finish(lease, stage, key, JobOutcome.FAILED, error=f"scripted retryable failure {attempts} of {stage.value}", retryable=True)
        result = RESULTS[stage](self, script, case, payload)
        if self.references:
            result = store_results(result, artifact_result_fields(job.job_type), self.artifacts.put)
            self._record_uploads(job, result)
        return self._finish(lease, stage, key, JobOutcome.SUCCEEDED, result=result)

    def _record_uploads(self, job, result: Mapping[str, Any]) -> None:
        """What the control node's artifact route does on an upload: the artifact's record and the job's reference to it."""
        for declared in artifact_result_fields(job.job_type):
            stored = result.get(declared.name)
            for value in stored if declared.many and isinstance(stored, list) else [stored]:
                if is_reference(value):
                    self.stores.artifacts.insert_if_absent(value["sha256"], value["kind"], value["size_bytes"], value["media_type"])
                    self.stores.artifacts.add_reference(value["sha256"], ArtifactHolderKind.JOB, job.job_id, f"result:{declared.name}")

    def _finish(self, lease: Lease, stage: PipelineStage, key, outcome: JobOutcome, result: Optional[dict] = None, error: Optional[str] = None, retryable: bool = False) -> Report:
        job = lease.job
        self.jobs.report_result(JobResult(lease_id=lease.lease_id, job_id=job.job_id, idempotency_key=job.idempotency_key, outcome=outcome, result=result or {}, error=error, retryable=retryable))
        report = Report(job.job_id, stage, outcome, key)
        self.reports.append(report)
        return report

    def document(self, reference: Mapping[str, Any]) -> Any:
        """The content of a reference, as the worker node would resolve it."""
        import json

        return json_pointer(json.loads(self.artifacts.documents[reference["sha256"]]), reference.get("pointer"))


# Results per stage, in the shapes of P4.2


def _input_text(executor: FakeExecutor, case) -> str:
    return executor.artifacts.documents[case.input_artifact].decode("utf-8")


def fec_text(index: int, target_ships: int = 1, obstacles: int = 0) -> str:
    """A functional scenario as an exploration returns it, as far as the counts read it: the own ship, the target ships and the obstacles."""
    lines = [f"// FEC {index}", "declare os.", "OS(os)."]
    lines += [f"TS(ts{number})." for number in range(1, target_ships + 1)]
    lines += [f"StaticObstacle(obst{number})." for number in range(1, obstacles + 1)]
    return "\n".join(lines) + "\n"


DEFAULT_EXPLORED = [fec_text(0), fec_text(1), fec_text(2, target_ships=2, obstacles=1)]


def _exploration(executor: FakeExecutor, script: CaseScript, case, payload) -> Dict[str, Any]:
    assert payload["random_seed"] == case.seed, "the exploration runs with the exploration case's seed"
    assert payload["problem"] and payload["scopes"], "the exploration gets the specification and the scope's entries"
    texts = DEFAULT_EXPLORED if script.explored is None else script.explored
    from scenegems_tool.subsystems.design_space_exploration.design_space import count_instances

    counts = [count_instances(text) for text in texts]
    return {
        "stop_reason": script.stop_reason,
        "complete": script.stop_reason in ("exhausted", "unsatisfiable"),
        "models_found": len(texts),
        "max_models": payload.get("max_models"),
        "random_seed": payload["random_seed"],
        "elapsed_s": 1.0,
        "message": "the partial model is inconsistent" if script.stop_reason == "unsatisfiable" else None,
        "fecs": [{"index": index, "vessel_count": vessels, "obstacle_count": obstacles} for index, (vessels, obstacles) in enumerate(counts)],
        "functional_scenarios": list(texts),
    }


def _scene(executor: FakeExecutor, script: CaseScript, case, payload) -> Dict[str, Any]:
    assert payload["seed"] == case.seed, "scene generation runs with the case seed"
    if case.class_id.startswith("explored/"):
        assert payload["functional_scenario_content"] == _input_text(executor, case), "scene generation gets the explored FEC's functional scenario"
    if case.class_id.startswith("scenario/"):
        assert payload["functional_scenario_content"] == _input_text(executor, case), "scene generation gets the scenario given as content"
    evaluation_data = {"best_scene": {"case": f"{case.class_id}#{case.case_index}"}, "random_seed": payload["seed"]}
    return {"request_id": "fake", "valid": script.scene_valid, "evaluation_data": evaluation_data}


def _trajectories(executor: FakeExecutor, script: CaseScript, case, payload) -> Dict[str, Any]:
    if case.class_id.startswith("item/"):
        assert payload["scenario_content"] == _input_text(executor, case), "trajectory generation gets the item's scene"
    else:
        assert f"{case.class_id}#{case.case_index}" in payload["scenario_content"], "trajectory generation gets the case's scene"
    if script.trajectories == "none":
        return {"request_id": "fake", "valid": False, "complete": False, "trajectory_data": None, "error_message": "no path"}
    trajectory_data = {"trajectories": trajectories_data(), "algorithm_desc": payload["params"].get("generator"), "random_seed": payload["seed"]}
    return {"request_id": "fake", "valid": True, "complete": script.trajectories == "complete", "trajectory_data": trajectory_data, "error_message": None}


def _outcomes(script: CaseScript, stage: PipelineStage = PipelineStage.MONITOR) -> Dict[str, Any]:
    passed = script.monitor_passed.get(stage, script.passed)
    rules = {"OS_0 - TS_1": {"Rule 14": {"passed": 0} if passed else {"failed": FAILED_RULE["first_failed_at"]}}}
    failed = [] if passed else [dict(FAILED_RULE)]
    roles = {"OS_0 - TS_1": {"HEAD_ON": {"give_way": ["OS_0", "TS_1"], "stand_on": []}}}
    return {"rules": rules, "failed_rules": failed, "encounters": {"OS_0 - TS_1": ["HEAD_ON", "OTHER"]}, "encounter_roles": roles, "passed": passed}


def _simulation(executor: FakeExecutor, script: CaseScript, case, payload) -> Dict[str, Any]:
    assert payload["trajectories"]["scene_list"], "the simulation gets the generated trajectories"
    digest = hashlib.sha256(f"{case.seed}:{payload['seed']}".encode("utf-8")).hexdigest()
    if "simulation_layer" in payload:
        return _ardupilot_simulation(script, payload, digest)
    run_record = {
        "stack": payload["mode"],
        "dt": 1.0,
        "steps": 10,
        "run_seed": payload["seed"],
        "repeatability_tier": script.tier,
        "environment": {"wind_vector": [0.0, 0.0, 0.0]},
        "state_digest": digest,
    }
    if script.omit_tier:
        del run_record["repeatability_tier"]
    result: Dict[str, Any] = {"run_record": run_record, "steps": 10, "state_digest": digest, "trajectories": trajectories_data()}
    if payload.get("monitor") == "live":
        result["monitor"] = {"scenes": 11, "monitored_scenes": 11, "time_step": 1, **_outcomes(script, PipelineStage.SIMULATE), "stopped_early_at": script.stopped_early_at}
    return result


def _ardupilot_simulation(script: CaseScript, payload, digest: str) -> Dict[str, Any]:
    """A result of the simulation job's ardupilot runner as the job reports it: a bounded run record, the state digest, the observed run as trajectories and no state rows."""
    assert payload["include_trajectories"] is True and payload["include_states"] is False and payload["geofence"]["radius_meters"] > 0
    run_record = {
        "stack": ["replay on ardupilot"],
        "dt": 1.0,
        "steps": 10,
        "speedup": payload["speedup"],
        "run_seed": payload["seed"],
        "repeatability_tier": "bounded",
        "environment": {"wind_vector": None, "waves": None},
        "state_digest": digest,
    }
    if script.omit_tier:
        del run_record["repeatability_tier"]
    result: Dict[str, Any] = {"run_record": run_record, "steps": 10, "achieved_speedup": 1.5, "state_digest": digest, "trajectories": trajectories_data()}
    if payload.get("monitor") == "live":
        assert payload["colregs_constraints_content"] and "early_stop" not in payload, "the live monitor of an ArduPilot run has the COLREGS constants and no early stop"
        result["monitor"] = {"scenes": 11, "monitored_scenes": 11, "time_step": 1, **_outcomes(script, PipelineStage.SIMULATE), "stopped_early_at": None}
    return result


def _monitoring(executor: FakeExecutor, script: CaseScript, case, payload, stage: PipelineStage = PipelineStage.MONITOR) -> Dict[str, Any]:
    if stage == PipelineStage.MONITOR_SCENE:
        assert payload["scene"]["best_scene"]["case"] == f"{case.class_id}#{case.case_index}" and "trajectories" not in payload, "the scene monitor gets the case's scene"
    else:
        assert payload["trajectories"]["scene_list"], "the monitor gets a state log or the planned trajectories"
    result = {"scenes": 11, "monitored_scenes": 11, "time_step": 1, **_outcomes(script, stage)}
    if payload.get("include_frames"):
        result["frames"] = [{"frame": index} for index in range(3)]
    return result


def _calibration(executor: FakeExecutor, script: CaseScript, case, payload) -> Dict[str, Any]:
    repeats = payload["trajectories"]
    assert all(repeat["scene_list"] for repeat in repeats)
    exact = payload["stack"].get("simulation_layer") == "kinematic"  # an ArduPilot stack is bounded: its repeats differ
    return {
        "reference": payload["reference"],
        "stack": payload["stack"],
        "repeats": len(repeats),
        "exact": exact,
        "trajectory_digests": ["d" * 64] * len(repeats),
        "alignment": "scenario_time",
        "deviation_bound_m": 0.0 if exact else 0.8,
        "per_vessel": {"0": {"max_m": 0.0, "rms_m": 0.0, "compared_duration_s": 10.0, "compared_samples": 11}},
        "samples_per_repeat": [11] * len(repeats),
    }


RESULTS: Dict[PipelineStage, Callable[..., Dict[str, Any]]] = {
    PipelineStage.EXPLORE_DESIGN_SPACE: _exploration,
    PipelineStage.GENERATE_SCENE: _scene,
    PipelineStage.MONITOR_SCENE: lambda *arguments: _monitoring(*arguments, stage=PipelineStage.MONITOR_SCENE),
    PipelineStage.GENERATE_TRAJECTORIES: _trajectories,
    PipelineStage.MONITOR_TRAJECTORIES: lambda *arguments: _monitoring(*arguments, stage=PipelineStage.MONITOR_TRAJECTORIES),
    PipelineStage.SIMULATE: _simulation,
    PipelineStage.MONITOR: _monitoring,
    PipelineStage.CALIBRATE: _calibration,
}
