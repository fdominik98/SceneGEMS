"""The stages a case passes through, the jobs they run, and the case's bookkeeping of them.

Per case, the stages of the steps the campaign runs (config.steps), in chain order:

    scene_generation:
      generate_scene          scene_generation job
      monitor_scene           monitoring.post_hoc job over the scene as a one-scene log (scene_generation.monitor post_hoc)
    trajectory_generation:
      generate_trajectories   trajectory_generation job (monitor_driven_rrt or straight)
      monitor_trajectories    monitoring.post_hoc job over the planned trajectories (trajectories.monitor post_hoc)
    simulation, per run, per repeat:
      simulate                simulation.kinematic job, or simulation.ardupilot_sim or simulation.gazebo for a run on an ArduPilot stack
                              (StageGraph.job_type_of); with the live monitor the job judges the run itself
    simulation, per run:
      monitor                 monitoring.post_hoc job over repeat 0's state log (post_hoc only)
      calibrate               calibration.deviation job over the run's repeats (repeats above one only)
    verdict                   no job: the engine writes the verdicts, from the post-hoc results, the
                              simulation's monitor section (live) or as unmonitored (empty)

A format 1 config runs the full chain without the scene and trajectory monitors, so its cases
pass the stages they always did. The first configured step takes the case's input: the class
content or a functional scenario's reference (scene generation), an item's reference (later
steps). A monitor of a scene or trajectory set runs beside the next step, which needs only the
generated output, not its verdict.

A run's verdict judges its repeat 0; the other repeats exist for the calibration. Every repeat
gets a run record.

A case's progress (scenario_case.progress) records what the engine has handled:

    steps     step name (generate_scene, monitor_scene, simulate:0:1, monitor:0, ...) to the job's
              outcome; an event of a step already there is a duplicate and changes nothing
    runs      per run index: run_records (repeat index to run record id), verdict (the pending
              verdict until the coverage controller completes the case), tier (the stack's
              repeatability tier), calibrated
    verdicts  per monitored generation step (scene, trajectories): its pending verdict; absent
              while there is none, so a format 1 case's progress keeps its shape

The case is ready when its last step has its output, every monitored step its verdict and every
run, with repeats, its calibration. The coverage controller then completes it (writes its
verdicts) or cancels it (above the quota).
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from scenegems_tool.assurance.campaign.campaign_config import ArdupilotStackConfig, CampaignConfig, CampaignStep, RunConfig, StackConfig
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.persistence.schema import MonitorImplementation, PipelineStage, StepKind

# Later stages run first, so started cases finish depth first and their artifacts live briefly. These
# are the offsets without the scene and trajectory monitors; stage_priority_offsets puts those between
# their neighbours.
STAGE_PRIORITY_OFFSET = {
    PipelineStage.GENERATE_SCENE: 0,
    PipelineStage.GENERATE_TRAJECTORIES: 1,
    PipelineStage.SIMULATE: 2,
    PipelineStage.MONITOR: 3,
    PipelineStage.CALIBRATE: 4,
}
STAGE_JOB_TYPES = {
    PipelineStage.GENERATE_SCENE: JobType.SCENE_GENERATION,
    PipelineStage.MONITOR_SCENE: JobType.MONITORING_POST_HOC,
    PipelineStage.GENERATE_TRAJECTORIES: JobType.TRAJECTORY_GENERATION,
    PipelineStage.MONITOR_TRAJECTORIES: JobType.MONITORING_POST_HOC,
    PipelineStage.SIMULATE: JobType.SIMULATION_KINEMATIC,  # the default; a run on an ArduPilot stack uses simulation_job_type
    PipelineStage.MONITOR: JobType.MONITORING_POST_HOC,
    PipelineStage.CALIBRATE: JobType.CALIBRATION_DEVIATION,
}
JOB_STAGES = tuple(STAGE_JOB_TYPES)
PER_RUN_STAGES = (PipelineStage.SIMULATE, PipelineStage.MONITOR, PipelineStage.CALIBRATE)
# The monitor stage of each generation step, and the verdict step it judges
GENERATION_MONITORS = {PipelineStage.MONITOR_SCENE: StepKind.SCENE, PipelineStage.MONITOR_TRAJECTORIES: StepKind.TRAJECTORIES}


def stage_priority_offsets(scene_monitored: bool = False, trajectories_monitored: bool = False) -> Dict[PipelineStage, int]:
    """The priority offset of every stage a campaign runs: its position in the chain, with the monitored generation steps' monitors inserted."""
    chain = [PipelineStage.GENERATE_SCENE]
    if scene_monitored:
        chain.append(PipelineStage.MONITOR_SCENE)
    chain.append(PipelineStage.GENERATE_TRAJECTORIES)
    if trajectories_monitored:
        chain.append(PipelineStage.MONITOR_TRAJECTORIES)
    chain += [PipelineStage.SIMULATE, PipelineStage.MONITOR, PipelineStage.CALIBRATE]
    return {stage: offset for offset, stage in enumerate(chain)}


# The job type of each ArduPilot layer; the job type decides the images (job_images), so a Gazebo run needs Gazebo
ARDUPILOT_LAYER_JOB_TYPES = {"ardupilot_sim": JobType.SIMULATION_ARDUPILOT_SIM, "gazebo": JobType.SIMULATION_GAZEBO}


def simulation_job_type(stack: StackConfig) -> JobType:
    """The job type that simulates a run on this stack: simulation.ardupilot_sim or simulation.gazebo by the ArduPilot layer, simulation.kinematic otherwise."""
    return ARDUPILOT_LAYER_JOB_TYPES[stack.simulation_layer] if isinstance(stack, ArdupilotStackConfig) else JobType.SIMULATION_KINEMATIC


@dataclass(frozen=True)
class Step:
    """One job of a case: its stage, and its run and repeat for the per-run stages."""

    stage: PipelineStage
    run_index: Optional[int] = None
    repeat_index: Optional[int] = None

    def __post_init__(self) -> None:
        if self.stage == PipelineStage.VERDICT:
            raise ValueError("the verdict stage runs no job")
        per_run = self.stage in PER_RUN_STAGES
        if per_run != (self.run_index is not None) or (self.stage == PipelineStage.SIMULATE) != (self.repeat_index is not None):
            raise ValueError(f"step {self.stage.value} with run {self.run_index} and repeat {self.repeat_index}")

    @property
    def name(self) -> str:
        """The step's name in the case's progress: generate_scene, simulate:0:1, monitor:0."""
        return ":".join([self.stage.value] + [str(index) for index in (self.run_index, self.repeat_index) if index is not None])

    @property
    def job_type(self) -> JobType:
        """The stage's job type; a simulate step's is the kinematic one here, StageGraph.job_type_of gives its run's."""
        return STAGE_JOB_TYPES[self.stage]

    def idempotency_key(self, campaign_id: str, case_id: int) -> str:
        """The key of the step's pipeline job and job: campaign:<id>:case:<case id>:<step name>."""
        return f"campaign:{campaign_id}:case:{case_id}:{self.name}"

    def priority(self, campaign_priority: int, offsets: Mapping[PipelineStage, int] = STAGE_PRIORITY_OFFSET) -> int:
        """The job's priority; the scene and trajectory monitors have one only with their graph's offsets (StageGraph.priority_offsets)."""
        return campaign_priority + offsets[self.stage]

    @classmethod
    def of(cls, stage: PipelineStage, run_index: Optional[int], repeat_index: Optional[int]) -> "Step":
        return cls(stage, run_index, repeat_index)


SCENE_STEP = Step(PipelineStage.GENERATE_SCENE)
SCENE_MONITOR_STEP = Step(PipelineStage.MONITOR_SCENE)
TRAJECTORIES_STEP = Step(PipelineStage.GENERATE_TRAJECTORIES)
TRAJECTORIES_MONITOR_STEP = Step(PipelineStage.MONITOR_TRAJECTORIES)


class CaseProgress:
    """A mutable view of a case's progress JSON; to_json gives the value to store."""

    def __init__(self, progress: Optional[Mapping[str, Any]] = None):
        progress = progress or {}
        self.steps: Dict[str, str] = dict(progress.get("steps", {}))
        self.runs: Dict[str, Dict[str, Any]] = {run: dict(state) for run, state in progress.get("runs", {}).items()}
        self.verdicts: Dict[str, Dict[str, Any]] = {step: dict(pending) for step, pending in progress.get("verdicts", {}).items()}

    def to_json(self) -> Dict[str, Any]:
        progress: Dict[str, Any] = {"steps": dict(self.steps), "runs": {run: dict(state) for run, state in sorted(self.runs.items(), key=lambda item: int(item[0]))}}
        if self.verdicts:
            progress["verdicts"] = {step: dict(pending) for step, pending in self.verdicts.items()}
        return progress

    def handled(self, step: Step) -> bool:
        return step.name in self.steps

    def mark(self, step: Step, outcome: str) -> None:
        self.steps[step.name] = outcome

    def run(self, run_index: int) -> Dict[str, Any]:
        return self.runs.setdefault(str(run_index), {})

    def run_record_id(self, run_index: int, repeat_index: int) -> Optional[int]:
        return self.runs.get(str(run_index), {}).get("run_records", {}).get(str(repeat_index))

    def set_run_record(self, run_index: int, repeat_index: int, run_record_id: int) -> None:
        run = self.run(run_index)
        run["run_records"] = {**run.get("run_records", {}), str(repeat_index): run_record_id}

    def run_record_ids(self) -> List[int]:
        return [record_id for run in self.runs.values() for record_id in run.get("run_records", {}).values()]

    def pending_verdict(self, run_index: int) -> Optional[Dict[str, Any]]:
        return self.runs.get(str(run_index), {}).get("verdict")

    def step_verdict(self, step: StepKind) -> Optional[Dict[str, Any]]:
        """The pending verdict of a monitored scene or trajectory step."""
        return self.verdicts.get(step.value)

    def set_step_verdict(self, step: StepKind, pending: Mapping[str, Any]) -> None:
        self.verdicts[step.value] = dict(pending)


class StageGraph:
    """The steps of a case under one campaign config."""

    def __init__(self, config: CampaignConfig):
        self.config = config
        self.steps = tuple(config.steps)
        self.first_step: CampaignStep = config.first_step
        # Runs exist only when the campaign simulates; a format 2 config keeps the default execution section otherwise
        self.runs: tuple = config.execution.runs if config.runs_step(CampaignStep.SIMULATION) else ()
        self.scene_monitored = config.runs_step(CampaignStep.SCENE_GENERATION) and config.scene_generation.monitor == MonitorImplementation.POST_HOC
        self.trajectories_monitored = config.runs_step(CampaignStep.TRAJECTORY_GENERATION) and config.trajectories.monitor == MonitorImplementation.POST_HOC
        self.priority_offsets = stage_priority_offsets(self.scene_monitored, self.trajectories_monitored)

    def runs_step(self, step: CampaignStep) -> bool:
        return step in self.steps

    def is_last(self, step: CampaignStep) -> bool:
        return self.steps[-1] == step

    def first_stage(self) -> PipelineStage:
        """The stage a new case starts at."""
        return {CampaignStep.SCENE_GENERATION: PipelineStage.GENERATE_SCENE, CampaignStep.TRAJECTORY_GENERATION: PipelineStage.GENERATE_TRAJECTORIES, CampaignStep.SIMULATION: PipelineStage.SIMULATE}[
            self.first_step
        ]

    def monitored_steps(self) -> List[StepKind]:
        """The generation steps whose output a monitor judges, in chain order."""
        return [step for step, monitored in ((StepKind.SCENE, self.scene_monitored), (StepKind.TRAJECTORIES, self.trajectories_monitored)) if monitored]

    def run(self, run_index: int) -> RunConfig:
        return self.runs[run_index]

    def job_type_of(self, step: Step) -> JobType:
        """The job type of a step: a simulate step's comes from its run's stack."""
        if step.stage == PipelineStage.SIMULATE:
            return simulation_job_type(self.runs[step.run_index].stack)
        return STAGE_JOB_TYPES[step.stage]

    def stage_jobs(self, stage: PipelineStage) -> List[JobType]:
        """The job types a stage may queue; the simulate stage has one per distinct simulation layer of the runs."""
        if stage not in STAGE_JOB_TYPES:
            return []
        if stage != PipelineStage.SIMULATE or not self.runs:
            return [STAGE_JOB_TYPES[stage]]
        jobs: List[JobType] = []
        for run in self.runs:
            job_type = simulation_job_type(run.stack)
            if job_type not in jobs:
                jobs.append(job_type)
        return jobs

    def run_job_type(self, run_index: int) -> JobType:
        """The run's simulation job type, which decides its images."""
        return simulation_job_type(self.runs[run_index].stack)

    def run_tier(self, run_index: int) -> Optional[str]:
        """The repeatability tier of a run's stack when its result names none: bounded on ArduPilot (replay_mavlink_lockstep), unknown on the kinematic layer."""
        return "bounded" if isinstance(self.runs[run_index].stack, ArdupilotStackConfig) else None

    def simulate_steps(self) -> List[Step]:
        return [Step(PipelineStage.SIMULATE, run_index, repeat) for run_index, run in enumerate(self.runs) for repeat in range(run.repeats)]

    def needs_monitor_job(self, run_index: int) -> bool:
        return self.runs[run_index].monitor == MonitorImplementation.POST_HOC

    def needs_calibration(self, run_index: int) -> bool:
        return self.runs[run_index].repeats > 1

    def simulated(self, progress: CaseProgress, run_index: int) -> bool:
        """Every repeat of the run is simulated."""
        return all(progress.handled(Step(PipelineStage.SIMULATE, run_index, repeat)) for repeat in range(self.runs[run_index].repeats))

    def steps_after_simulation(self, progress: CaseProgress, run_index: int, repeat_index: int) -> List[Step]:
        """The jobs that become due when the given repeat of the run is simulated (and recorded in progress)."""
        due = []
        if repeat_index == 0 and self.needs_monitor_job(run_index):
            due.append(Step(PipelineStage.MONITOR, run_index))
        if self.needs_calibration(run_index) and self.simulated(progress, run_index):
            due.append(Step(PipelineStage.CALIBRATE, run_index))
        return due

    def run_finished(self, progress: CaseProgress, run_index: int) -> bool:
        run = progress.runs.get(str(run_index), {})
        return "verdict" in run and (not self.needs_calibration(run_index) or bool(run.get("calibrated")))

    def ready(self, progress: CaseProgress) -> bool:
        """The last step has its output, every monitored generation step its verdict, every run its verdict and, with repeats, its calibration."""
        if self.runs_step(CampaignStep.SCENE_GENERATION) and not progress.handled(SCENE_STEP):
            return False
        if self.runs_step(CampaignStep.TRAJECTORY_GENERATION) and not progress.handled(TRAJECTORIES_STEP):
            return False
        if any(progress.step_verdict(step) is None for step in self.monitored_steps()):
            return False
        return all(self.run_finished(progress, run_index) for run_index in range(len(self.runs)))

    def stage_of(self, progress: CaseProgress) -> PipelineStage:
        """The earliest stage with work left; verdict once the case is ready."""
        if self.runs_step(CampaignStep.SCENE_GENERATION):
            if not progress.handled(SCENE_STEP):
                return PipelineStage.GENERATE_SCENE
            if self.scene_monitored and not progress.handled(SCENE_MONITOR_STEP):
                return PipelineStage.MONITOR_SCENE
        if self.runs_step(CampaignStep.TRAJECTORY_GENERATION):
            if not progress.handled(TRAJECTORIES_STEP):
                return PipelineStage.GENERATE_TRAJECTORIES
            if self.trajectories_monitored and not progress.handled(TRAJECTORIES_MONITOR_STEP):
                return PipelineStage.MONITOR_TRAJECTORIES
        if not all(progress.handled(step) for step in self.simulate_steps()):
            return PipelineStage.SIMULATE
        indexes = range(len(self.runs))
        if any(self.needs_monitor_job(run_index) and not progress.handled(Step(PipelineStage.MONITOR, run_index)) for run_index in indexes):
            return PipelineStage.MONITOR
        if any(self.needs_calibration(run_index) and not progress.handled(Step(PipelineStage.CALIBRATE, run_index)) for run_index in indexes):
            return PipelineStage.CALIBRATE
        return PipelineStage.VERDICT
