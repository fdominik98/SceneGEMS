"""The payload of each pipeline job, from the campaign's config, the case's input and its earlier results.

    scene_generation        a catalog class's content from the catalog (checked against the hash
                            the campaign pinned), or a functional scenario given as content as its
                            reference (kind functional_scenario, which the node resolves); the
                            domain contents, the timeout, enforce_low_tcpa, the case seed
    monitoring.post_hoc     (monitor_scene) the scene result's evaluation_data as scene, a
                            reference when the result holds one
    trajectory_generation   the scene result's evaluation_data as scenario_content (a reference
                            when the result holds one, otherwise its JSON text), or an input
                            item's scene reference; the generator choice in params, the case
                            seed, the timeout
    monitoring.post_hoc     (monitor_trajectories) the planned trajectories, as the simulation
                            gets them
    simulation              runner kinematic: the trajectory result's trajectories (a reference into its
                            trajectory_data with pointer /trajectories, or the inline list), or an
                            input item's trajectories reference; the stack's mode and parameters,
                            the run's seed (the case seed unless the run fixes one), the live
                            monitor options
                            runner ardupilot: the same trajectories for a run on an ArduPilot stack: its simulation layer,
                            speedup, geofence, dt, steps and the run seed; the observed run comes back
                            as trajectories (include_trajectories), with the live monitor options when
                            the run is judged live and no state rows (the trajectories are the state log)
    monitoring.post_hoc     (monitor) the simulation result's trajectories, the COLREGS constants
    calibration.deviation   the trajectories of the run's repeats

Every monitoring payload sets include_frames from policy.keep_frames. An item's reference goes
into the payload as it is, except that a trajectory_data item without a pointer gets
/trajectories, so the simulation takes its trajectories. Results come inline (before the
artifact store) or with references in their declared fields; both work. Every payload is
checked with its job type's model (references for shape only) before the engine writes the
intent, so a payload the master would refuse never reaches the queue.
"""

import hashlib
from typing import Any, Collection, Dict, Mapping, Optional, Sequence, Tuple

from pydantic import ValidationError

from scenegems_tool.assurance.campaign.campaign_config import ArdupilotStackConfig, CampaignConfig, FunctionalScenarioInput, InputArtifactKind, InputItem, InputRef, RunConfig
from scenegems_tool.assurance.campaign.campaign_inputs import input_of_class
from scenegems_tool.assurance.campaign.class_catalog import ClassCatalog
from scenegems_tool.assurance.pipeline.stage_graph import StageGraph, Step
from scenegems_tool.cluster.fingerprints.comparison import fingerprints_of
from scenegems_tool.cluster.fingerprints.components import ComponentId, SimulationRunner, images_of
from scenegems_tool.cluster.protocol.artifacts import ArtifactContent, encode_document, is_reference
from scenegems_tool.cluster.protocol.jobs import JobRequirements, JobSubmission, JobType
from scenegems_tool.persistence.schema import MonitorImplementation, TrajectoryGeneratorImplementation

TRAJECTORIES_POINTER = "/trajectories"


class PayloadError(ValueError):
    """A payload that cannot be built from the case's results, or that its job type's model refuses."""


def _wire(reference: Any) -> Dict[str, Any]:
    return reference.model_dump(mode="json") if hasattr(reference, "model_dump") else dict(reference)


def _required(result: Mapping[str, Any], field: str, stage: str) -> Any:
    value = result.get(field)
    if value is None:
        raise PayloadError(f"the {stage} result has no {field}")
    return value


def scenario_content_of(scene_result: Mapping[str, Any]) -> Any:
    """trajectory_generation's scenario_content: the scene reference as it is, or the inline scene as JSON text."""
    evaluation_data = _required(scene_result, "evaluation_data", "scene generation")
    if is_reference(evaluation_data):
        return _wire(evaluation_data)
    if isinstance(evaluation_data, str):
        return evaluation_data
    return encode_document(evaluation_data, ArtifactContent.TEXT).decode("utf-8")  # the text a reference to it would resolve to


def trajectories_of_trajectory_result(trajectory_result: Mapping[str, Any]) -> Any:
    """The generated trajectories: a reference into trajectory_data at /trajectories, or the inline trajectories."""
    trajectory_data = _required(trajectory_result, "trajectory_data", "trajectory generation")
    if is_reference(trajectory_data):
        reference = _wire(trajectory_data)
        reference["pointer"] = (reference.get("pointer") or "") + TRAJECTORIES_POINTER
        return reference
    trajectories = trajectory_data.get("trajectories")
    if trajectories is None:
        raise PayloadError("the trajectory generation result's trajectory_data has no trajectories")
    return trajectories


def trajectories_of_simulation_result(simulation_result: Mapping[str, Any]) -> Any:
    """A simulation's state log, inline or as its reference."""
    trajectories = _required(simulation_result, "trajectories", "simulation")
    return _wire(trajectories) if is_reference(trajectories) else trajectories


def input_reference(ref: InputRef) -> Dict[str, Any]:
    """An input's reference in the wire form of a payload field."""
    return ref.model_dump(mode="json")


def item_trajectories(item: InputItem) -> Dict[str, Any]:
    """A simulation's trajectories from an item: its reference, into /trajectories for a whole trajectory_data document."""
    if item.ref.kind not in (InputArtifactKind.TRAJECTORY_DATA, InputArtifactKind.TRAJECTORIES):
        raise PayloadError(f"item {item.name} is a {item.ref.kind.value}, not trajectories")
    reference = input_reference(item.ref)
    if item.ref.kind == InputArtifactKind.TRAJECTORY_DATA and not item.ref.pointer:
        reference["pointer"] = TRAJECTORIES_POINTER
    return reference


def validate_payload(job_type: JobType, payload: Mapping[str, Any]) -> Tuple[ComponentId, ...]:
    """Checks the payload with its job type's model, as the master does at submission, and returns the components it needs; raises PayloadError."""
    from scenegems_tool.cluster.node.jobs.job_types import payload_components

    try:
        return payload_components(job_type, payload)
    except ValidationError as error:
        problems = "; ".join(f"{'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}" for issue in error.errors(include_url=False, include_input=False))
        raise PayloadError(f"invalid {job_type.value} payload: {problems}") from error


def required_fingerprints(components: Collection[ComponentId], pinned: Mapping[str, str]) -> Dict[str, str]:
    """The pinned fingerprints of the images of these components, keyed by repository; a pin under another tag (an older release's) holds."""
    return fingerprints_of(images_of(components), pinned)


class PayloadBuilder:
    def __init__(self, config: CampaignConfig, catalog: Optional[ClassCatalog] = None):
        self.config = config
        self.catalog = catalog or ClassCatalog.default()
        self.graph = StageGraph(config)
        self.priority_offsets = self.graph.priority_offsets
        self._contents: Dict[str, str] = {}

    # Payloads

    def scene_generation(self, class_id: str, content_hash: str, case_seed: int) -> Dict[str, Any]:
        """A catalog class's content, or the reference of a functional scenario given as content."""
        domain = self.config.domain
        scenario = input_of_class(self.config, class_id)
        if scenario is None:
            content: Any = self.class_content(class_id, content_hash)
        elif isinstance(scenario, FunctionalScenarioInput):
            if scenario.ref.sha256 != content_hash:
                raise PayloadError(f"FEC {class_id} names functional scenario {scenario.ref.sha256}, but the campaign pinned {content_hash}")
            content = input_reference(scenario.ref)
        else:
            raise PayloadError(f"FEC {class_id} is an item; scene generation takes catalog FECs and functional scenarios")
        return {
            "functional_scenario_content": content,
            "colregs_constraints_content": domain.colregs_constants,
            "vessel_types_content": domain.vessel_types,
            "obstacle_types_content": domain.obstacle_types,
            "timeout_s": domain.scene_generation_timeout_s,
            "enforce_low_tcpa": domain.enforce_low_tcpa,
            "seed": case_seed,
        }

    def trajectory_generation(self, case_seed: int, scene_result: Mapping[str, Any]) -> Dict[str, Any]:
        return self._trajectory_generation(case_seed, scenario_content_of(scene_result))

    def trajectory_generation_of_item(self, case_seed: int, item: InputItem) -> Dict[str, Any]:
        """Trajectory generation over an input item: a scene or a scene generation's EvaluationData."""
        if item.ref.kind != InputArtifactKind.SCENE:
            raise PayloadError(f"item {item.name} is a {item.ref.kind.value}, not a scene")
        return self._trajectory_generation(case_seed, input_reference(item.ref))

    def _trajectory_generation(self, case_seed: int, scenario_content: Any) -> Dict[str, Any]:
        trajectories = self.config.trajectories
        if trajectories.generator == TrajectoryGeneratorImplementation.STRAIGHT:
            params: Dict[str, Any] = {"generator": trajectories.generator.value, "timespan": trajectories.timespan_s}
        else:
            params = {"generator": trajectories.generator.value, **trajectories.params}
        return {
            "scenario_content": scenario_content,
            "colregs_constraints_content": self.config.domain.colregs_constants,
            "params": params,
            "seed": case_seed,
            "timeout_s": trajectories.timeout_s,
        }

    def simulation(self, case_seed: int, run_index: int, trajectory_result: Mapping[str, Any]) -> Dict[str, Any]:
        return self._simulation(case_seed, run_index, trajectories_of_trajectory_result(trajectory_result))

    def simulation_of_item(self, case_seed: int, run_index: int, item: InputItem) -> Dict[str, Any]:
        """A run over an input item's trajectories."""
        return self._simulation(case_seed, run_index, item_trajectories(item))

    def _simulation(self, case_seed: int, run_index: int, trajectories: Any) -> Dict[str, Any]:
        run = self.config.execution.runs[run_index]
        if isinstance(run.stack, ArdupilotStackConfig):
            return self._ardupilot_simulation(run, run.stack, run.seed_for(case_seed), trajectories)
        stack = run.stack
        payload: Dict[str, Any] = {"runner": SimulationRunner.KINEMATIC.value, "mode": stack.mode.value, "trajectories": trajectories, "seed": run.seed_for(case_seed)}
        if stack.usv_navigation is not None:
            payload["usv_navigation"] = stack.usv_navigation.model_dump(mode="json")
        if stack.dt is not None:
            payload["dt"] = stack.dt
        if stack.steps is not None:
            payload["steps"] = stack.steps
        if run.monitor == MonitorImplementation.LIVE:
            payload.update(monitor="live", early_stop=run.early_stop, colregs_constraints_content=self.config.domain.colregs_constants)
        return payload

    def _ardupilot_simulation(self, run: RunConfig, stack: ArdupilotStackConfig, seed: int, trajectories: Any) -> Dict[str, Any]:
        """The ardupilot runner's payload of a run: the observed run always comes back as trajectories (what the post-hoc monitor, the calibration and the frames take)."""
        payload: Dict[str, Any] = {
            "runner": SimulationRunner.ARDUPILOT.value,
            "simulation_layer": stack.simulation_layer,
            "trajectories": trajectories,
            "geofence": stack.geofence.model_dump(mode="json"),
            "speedup": stack.speedup,
            "seed": seed,
            "include_states": False,  # the sample rows would be a second state log next to the trajectories
            "include_trajectories": True,
        }
        if stack.dt is not None:
            payload["dt"] = stack.dt
        if stack.steps is not None:
            payload["steps"] = stack.steps
        if run.monitor == MonitorImplementation.LIVE:
            payload.update(monitor="live", colregs_constraints_content=self.config.domain.colregs_constants)
        return payload

    def post_hoc_monitoring(self, scenario_id: str, simulation_result: Mapping[str, Any]) -> Dict[str, Any]:
        return self._monitoring(scenario_id, trajectories=trajectories_of_simulation_result(simulation_result))

    def scene_monitoring(self, scenario_id: str, scene_result: Mapping[str, Any]) -> Dict[str, Any]:
        """The scene monitor: the generated scene judged as a one-scene log."""
        evaluation_data = _required(scene_result, "evaluation_data", "scene generation")
        return self._monitoring(scenario_id, scene=_wire(evaluation_data) if is_reference(evaluation_data) else evaluation_data)

    def trajectory_monitoring(self, scenario_id: str, trajectory_result: Mapping[str, Any]) -> Dict[str, Any]:
        """The trajectory monitor: the planned trajectories, as the simulation would get them."""
        return self._monitoring(scenario_id, trajectories=trajectories_of_trajectory_result(trajectory_result))

    def _monitoring(self, scenario_id: str, **judged: Any) -> Dict[str, Any]:
        return {
            **judged,
            "colregs_constraints_content": self.config.domain.colregs_constants,
            "scenario_id": scenario_id,
            "include_frames": self.config.policy.keep_frames,
        }

    def calibration(self, reference: str, stack: Mapping[str, Any], simulation_results: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        return {"trajectories": [trajectories_of_simulation_result(result) for result in simulation_results], "stack": dict(stack), "reference": reference}

    # Submissions

    def submission(self, step: Step, payload: Dict[str, Any], key: str, pinned: Mapping[str, str]) -> JobSubmission:
        """The job of a step, checked: its payload, the campaign's labels and nodes, its components and the pinned fingerprints of their images, its priority."""
        job_type = self.graph.job_type_of(step)
        components = validate_payload(job_type, payload)
        resources = self.config.resources
        requirements = JobRequirements(labels=dict(resources.required_labels), components=list(components), fingerprints=required_fingerprints(components, pinned))
        return JobSubmission(
            job_type=job_type,
            payload=payload,
            requirements=requirements,
            priority=step.priority(resources.priority, self.priority_offsets),
            idempotency_key=key,
            allowed_nodes=list(resources.nodes),
        )

    # Helpers

    def class_content(self, class_id: str, content_hash: str) -> str:
        content = self._contents.get(class_id)
        if content is None:
            content = self.catalog.get(class_id).read_content()
            self._contents[class_id] = content
        found = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if found != content_hash:
            raise PayloadError(f"FEC {class_id} has changed in the catalog since the campaign pinned it (content hash {found}, pinned {content_hash})")
        return content


def stack_key(config: CampaignConfig, run_index: int) -> Dict[str, Any]:
    """The run's stack as calibration results are keyed by it: the stack section of the run's config."""
    return config.execution.runs[run_index].stack.model_dump(mode="json")


def environment_of(config: CampaignConfig, run_index: int) -> Dict[str, Any]:
    return config.execution.runs[run_index].environment.model_dump(mode="json")
