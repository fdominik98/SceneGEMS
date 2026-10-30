"""The campaign config: what a campaign runs, as an immutable, hashed pydantic model.

Sections:
    format          1 (the default), 2 or 3
    steps           format 2: the consecutive part of the chain scene_generation, trajectory_generation,
                    simulation the campaign runs, in chain order; all three by default
    scope           FECs, functional equivalence classes (catalog ids or folder patterns), each entry
                    with a quota and a failure budget (a number of cases, or unlimited: the FEC is never
                    abandoned); format 3 lists them under fecs, formats 1 and 2 under classes
    input           format 2: functional scenarios given as content (a campaign that starts with scene
                    generation) or items, outputs of earlier steps or uploaded files (one that starts later)
    domain          COLREGS constants, vessel types and obstacle types as content (defaults: the
                    cluster's domain configuration when the master fills them in, else the default
                    presets of backend/assets/domain_config/), the scene generation timeout, enforce_low_tcpa
    scene_generation  format 2: the monitor of the generated scenes (post_hoc or empty)
    trajectories    the generator: monitor_driven_rrt with its search parameters (the wire keys of
                    TrajectoryGenerationParams) or straight with its timespan; the timeout; format 2:
                    the monitor of the planned trajectories (post_hoc or empty)
    execution       the runs of every case: a stack (kinematic, or ArduPilot SITL or Gazebo replay), an
                    environment, a seed, repeats, the monitor
    resources       the nodes it may use (all when none are named), required node labels, queue depth
                    caps per stage, priority
    policy          retention, whether to keep frames, the campaign seed, stop conditions

Unknown fields are rejected everywhere. YAML is read with a safe loader that also rejects
duplicate keys. The hash is the sha256 of the config's canonical JSON with every default
filled in, so it pins the domain content too. Content strings get LF line endings, so a
config hashes the same from a Windows and a Linux checkout.

A format 1 config is the full chain with the fields it always had: it takes none of the
format 2 fields, and its JSON (and so its hash) leaves them out, so a campaign created
before format 2 keeps its stored hash. Sections of steps a campaign does not run are kept
but not used. Format 3 is format 2 with a scope entry's FECs under fecs instead of
classes; formats 1 and 2 keep the name classes in their JSON, so their hashes stay.

The campaign seed (policy.seed) is the base the case seeds count up from: case k of a class
gets the campaign seed + k, an item's one case the campaign seed + its item number
(case_seed). Every step of a case uses its case seed: scene generation, trajectory
generation and every run, unless the run fixes its own seed (RunConfig.seed_for).
"""

from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Dict, Literal, Mapping, Optional, Tuple, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, ValidatorFunctionWrapHandler, WrapValidator, field_validator, model_validator

from scenegems_tool.assurance.campaign.domain_presets import DOMAIN_KEYS, default_preset_file, normalize_newlines, read_domain_file
from scenegems_tool.cluster.node.daemon.configuration.node_configuration import DEFAULT_REFERENCE_GEOFENCE
from scenegems_tool.cluster.node.jobs.simulation_kinematic_job import KinematicMode, UsvNavigationPayload
from scenegems_tool.cluster.node.jobs.trajectory_generation_job import PARAM_KEYS
from scenegems_tool.cluster.protocol.artifacts import JSON_MEDIA_TYPE, SHA256_PATTERN
from scenegems_tool.persistence.canonical_json import canonical_json_sha256
from scenegems_tool.persistence.schema import MonitorImplementation, PipelineStage, StepKind, TrajectoryGeneratorImplementation
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_types import TrajectoryGenerationParams

CONFIG_FORMAT = 1  # the format of a config that names none
LATEST_FORMAT = 3  # the format the console writes
MAX_SEED = 2**31 - 1  # seeds are 31-bit, so every consumer (numpy included) takes them
ITEM_CLASS_PREFIX = "item/"  # the class of input.items[n] is item/<n>

DEFAULT_COLREGS_CONSTANTS_FILE = default_preset_file("colregs_constants")
DEFAULT_VESSEL_TYPES_FILE = default_preset_file("vessel_types")
DEFAULT_OBSTACLE_TYPES_FILE = default_preset_file("obstacle_types")

# The generator choice travels in the trajectory parameters on the wire (P4.2); here it is its own field
GENERATOR_CHOICE_KEYS = frozenset({"generator", "timespan"})
SEARCH_PARAM_KEYS = frozenset(PARAM_KEYS) - GENERATOR_CHOICE_KEYS


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# Steps


class CampaignStep(str, Enum):
    """The steps of the chain, in chain order."""

    SCENE_GENERATION = "scene_generation"
    TRAJECTORY_GENERATION = "trajectory_generation"
    SIMULATION = "simulation"

    @property
    def step_kind(self) -> StepKind:
        """The step as verdicts and outputs name it."""
        return {CampaignStep.SCENE_GENERATION: StepKind.SCENE, CampaignStep.TRAJECTORY_GENERATION: StepKind.TRAJECTORIES, CampaignStep.SIMULATION: StepKind.SIMULATION}[self]


CHAIN = tuple(CampaignStep)


# Failure budget

UNLIMITED_FAILURE_BUDGET = "unlimited"  # the failure budget of a class that is never abandoned
_CASE_COUNT: TypeAdapter[int] = TypeAdapter(Annotated[int, Field(ge=0)])


def _case_count_or_unlimited(value: Any, handler: ValidatorFunctionWrapHandler) -> Any:
    """Validates a failure budget as a number of cases or unlimited, so an error names the field once and not each union member."""
    if value == UNLIMITED_FAILURE_BUDGET:
        return handler(value)
    try:
        return _CASE_COUNT.validate_python(value)
    except ValidationError as error:
        raise ValueError(f"a failure budget is a number of cases from 0 up or {UNLIMITED_FAILURE_BUDGET!r}, not {value!r}") from error


# The dropped and failed cases a class may use up before it is abandoned; unlimited: it is never abandoned
FailureBudget = Annotated[Union[int, Literal["unlimited"]], WrapValidator(_case_count_or_unlimited)]


def budget_limit(failure_budget: Union[int, str]) -> Optional[int]:
    """The dropped and failed cases a class may use up before it is abandoned; None for an unlimited failure budget."""
    return failure_budget if isinstance(failure_budget, int) else None


def _generation_step_monitor(monitor: MonitorImplementation) -> MonitorImplementation:
    if monitor == MonitorImplementation.LIVE:
        raise ValueError("a generated scene or trajectory set is monitored post_hoc or not at all (empty)")
    return monitor


# Scope


class ScopeEntry(ConfigModel):
    """FECs by id (`3vessel_0obstacle_scenarios/functional_model5`) or pattern, with their quota and failure budget.

    A pattern without a slash matches catalog folders (`3vessel_*_scenarios`), one with a
    slash matches FEC ids (`2vessel_*/functional_model1`), both with shell wildcards. Formats 1
    and 2 call the list classes; CampaignConfig reads and writes that name for them.
    """

    fecs: Tuple[str, ...] = ()
    patterns: Tuple[str, ...] = ()
    quota: int = Field(ge=1)  # complete cases (with a verdict per run) the FEC needs
    failure_budget: FailureBudget = 0  # dropped and failed cases the FEC may use up before it is abandoned

    @model_validator(mode="after")
    def _names_fecs(self) -> "ScopeEntry":
        if not self.fecs and not self.patterns:
            raise ValueError("a scope entry needs fecs (classes before format 3) or patterns")
        return self


# Input


class InputArtifactKind(str, Enum):
    FUNCTIONAL_SCENARIO = "functional_scenario"  # a functional scenario (.problem text)
    SCENE = "scene"  # a scene or a scene generation's EvaluationData
    TRAJECTORY_DATA = "trajectory_data"  # a trajectory generation's TrajectoryData
    TRAJECTORIES = "trajectories"  # Trajectories: planned trajectories or a run's state log


class InputRef(ConfigModel):
    """An artifact in the master's store, in the wire form of cluster/protocol/artifacts.ArtifactRef.

    Its own model because the protocol's artifact kinds have no functional scenario yet.
    """

    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: int = Field(ge=0)
    kind: InputArtifactKind
    media_type: str = JSON_MEDIA_TYPE
    pointer: Optional[str] = None  # JSON pointer into the document, such as /trajectories; the whole document when None

    @field_validator("pointer")
    @classmethod
    def _pointer_syntax(cls, pointer: Optional[str]) -> Optional[str]:
        if pointer is not None and pointer != "" and not pointer.startswith("/"):
            raise ValueError("a JSON pointer starts with '/'")
        return pointer


class FunctionalScenarioInput(ConfigModel):
    """A functional scenario given as content: a class of its own, id scenario/<name>, its content pinned by the reference's hash."""

    name: str = Field(min_length=1, max_length=200, pattern=r"^[^/]+$")
    ref: InputRef
    quota: int = Field(ge=1)
    failure_budget: FailureBudget = 0

    @field_validator("ref")
    @classmethod
    def _a_functional_scenario(cls, ref: InputRef) -> InputRef:
        if ref.kind != InputArtifactKind.FUNCTIONAL_SCENARIO:
            raise ValueError(f"a functional scenario's reference has kind functional_scenario, not {ref.kind.value}")
        return ref


class ItemSource(ConfigModel):
    """Where an item came from: an output of a step of an earlier campaign, or an uploaded file."""

    campaign_id: Optional[str] = Field(default=None, min_length=1, max_length=36)
    case_id: Optional[int] = Field(default=None, ge=1)
    step: Optional[CampaignStep] = None
    file: Optional[str] = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def _one_source(self) -> "ItemSource":
        output = (self.campaign_id, self.case_id, self.step)
        if self.file is not None:
            if any(value is not None for value in output):
                raise ValueError("an item comes from a file or from a campaign's output, not both")
        elif any(value is None for value in output):
            raise ValueError("an item's source is {campaign_id, case_id, step} or {file}")
        return self


class InputItem(ConfigModel):
    """A scene (for trajectory generation) or trajectories (for simulation): a class of its own, id item/<index>, quota 1."""

    name: str = Field(min_length=1, max_length=256)
    ref: InputRef
    source: ItemSource


class InputConfig(ConfigModel):
    functional_scenarios: Tuple[FunctionalScenarioInput, ...] = ()
    items: Tuple[InputItem, ...] = ()

    @field_validator("functional_scenarios")
    @classmethod
    def _distinct_names(cls, scenarios: Tuple[FunctionalScenarioInput, ...]) -> Tuple[FunctionalScenarioInput, ...]:
        names = [scenario.name for scenario in scenarios]
        twice = sorted({name for name in names if names.count(name) > 1})
        if twice:
            raise ValueError(f"functional scenario names must be distinct: {twice}")
        return scenarios


# Domain


class DomainConfig(ConfigModel):
    colregs_constants: str = Field(default_factory=lambda: read_domain_file(DEFAULT_COLREGS_CONSTANTS_FILE))  # YAML content
    vessel_types: str = Field(default_factory=lambda: read_domain_file(DEFAULT_VESSEL_TYPES_FILE))
    obstacle_types: str = Field(default_factory=lambda: read_domain_file(DEFAULT_OBSTACLE_TYPES_FILE))
    scene_generation_timeout_s: int = Field(default=60, gt=0)  # the generation's own time limit
    enforce_low_tcpa: bool = False

    @field_validator("colregs_constants", "vessel_types", "obstacle_types")
    @classmethod
    def _yaml_mapping(cls, content: str) -> str:
        content = normalize_newlines(content)
        try:
            parsed = yaml.safe_load(content)
        except yaml.YAMLError as error:
            raise ValueError(f"not valid YAML ({error})") from error
        if not isinstance(parsed, dict) or not parsed:
            raise ValueError("expected a YAML mapping with at least one entry")
        return content


# Scene generation


class SceneGenerationConfig(ConfigModel):
    monitor: MonitorImplementation = MonitorImplementation.EMPTY  # post_hoc judges each scene as a one-scene log

    _monitor = field_validator("monitor")(_generation_step_monitor)


# Trajectories


class TrajectoriesConfig(ConfigModel):
    generator: TrajectoryGeneratorImplementation = TrajectoryGeneratorImplementation.MONITOR_DRIVEN_RRT
    # monitor_driven_rrt only: search parameters by their wire keys (timeStep, maxIterations, ...); search defaults when absent
    params: Dict[str, Union[bool, int, float]] = Field(default_factory=dict)
    timespan_s: Optional[float] = Field(default=None, gt=0)  # straight only, required there: how far every vessel goes straight on
    timeout_s: float = Field(default=1800.0, gt=0)  # how long a trajectory generation job may take
    monitor: MonitorImplementation = MonitorImplementation.EMPTY  # format 2: post_hoc judges the planned trajectories

    _monitor = field_validator("monitor")(_generation_step_monitor)

    @model_validator(mode="after")
    def _parameters_of_the_generator(self) -> "TrajectoriesConfig":
        if self.generator == TrajectoryGeneratorImplementation.STRAIGHT:
            if self.timespan_s is None:
                raise ValueError("the straight generator needs timespan_s")
            if self.params:
                raise ValueError("the straight generator takes no search parameters")
            return self
        if self.timespan_s is not None:
            raise ValueError("timespan_s applies to the straight generator only")
        unknown = sorted(set(self.params) - SEARCH_PARAM_KEYS)
        if unknown:
            raise ValueError(f"unknown search parameters {unknown}; known are {sorted(SEARCH_PARAM_KEYS)}")
        try:
            TrajectoryGenerationParams.from_wire(dict(self.params))
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid search parameters ({error})") from error
        return self


# Execution


class WaveSettings(ConfigModel):
    amplitude: float = Field(ge=0)
    period: float = Field(ge=0)
    steepness: float = Field(ge=0)
    direction: Tuple[float, float]  # propagation vector [east, north]; its norm is the wave speed


class EnvironmentSettings(ConfigModel):
    wind_vector: Tuple[float, float, float] = (0.0, 0.0, 0.0)  # [east, north, up] m/s
    waves: Optional[WaveSettings] = None


class KinematicStackConfig(ConfigModel):
    """A run on the kinematic layer: every vessel replays, or the own ship runs USV Navigation.

    The stacks on the ArduPilot layers are ArdupilotStackConfig; StackConfig is the union on simulation_layer.
    """

    simulation_layer: Literal["kinematic"] = "kinematic"
    mode: KinematicMode = KinematicMode.REPLAY
    usv_navigation: Optional[UsvNavigationPayload] = None  # usv_navigation only; derived from each scene when absent
    dt: Optional[float] = Field(default=None, gt=0)  # the trajectories' time step when absent
    steps: Optional[int] = Field(default=None, ge=1)  # the trajectories' timespan when absent

    @model_validator(mode="after")
    def _usv_navigation_needs_its_mode(self) -> "KinematicStackConfig":
        if self.usv_navigation is not None and self.mode != KinematicMode.USV_NAVIGATION:
            raise ValueError("usv_navigation parameters apply only to mode usv_navigation")
        return self


ARDUPILOT_LAYERS = ("ardupilot_sim", "gazebo")  # the simulation layers of ArdupilotStackConfig, as ArduPilotSimulationLayer names them
DEFAULT_GEOFENCE_LATITUDE, DEFAULT_GEOFENCE_LONGITUDE, DEFAULT_GEOFENCE_RADIUS_M = DEFAULT_REFERENCE_GEOFENCE  # the workbench's reference area


class GeofenceSettings(ConfigModel):
    """The reference area that maps the scenes' local frame to SITL's home positions; the workbench's default when absent."""

    latitude: float = Field(default=DEFAULT_GEOFENCE_LATITUDE, ge=-90, le=90)
    longitude: float = Field(default=DEFAULT_GEOFENCE_LONGITUDE, ge=-180, le=180)
    radius_meters: float = Field(default=DEFAULT_GEOFENCE_RADIUS_M, gt=0)


class ArdupilotStackConfig(ConfigModel):
    """A run on ArduPilot SITL (ardupilot_sim) or on SITL against a Gazebo world (gazebo): every vessel replays its trajectory.

    The ASV software is replay over the replay_mavlink_lockstep adapter, in the bounded repeatability
    tier, as simulation.ardupilot_sim and simulation.gazebo run it. The job applies no environment, so a run on this stack is calm.
    """

    simulation_layer: Literal["ardupilot_sim", "gazebo"]
    mode: Literal["replay"] = "replay"
    speedup: int = Field(default=1, ge=1)  # SITL's requested pace, as the resolver checks it
    dt: Optional[float] = Field(default=None, gt=0)  # the trajectories' time step when absent; whole seconds
    steps: Optional[int] = Field(default=None, ge=1)  # the trajectories' timespan when absent
    geofence: GeofenceSettings = Field(default_factory=GeofenceSettings)

    @field_validator("dt")
    @classmethod
    def _whole_seconds(cls, dt: Optional[float]) -> Optional[float]:
        if dt is not None and not float(dt).is_integer():
            raise ValueError("the observed trajectories and the live monitor need a whole number of seconds as dt")
        return dt


def _stack_by_layer(value: Any, handler: ValidatorFunctionWrapHandler) -> Any:
    """Validates a stack as the model of its simulation_layer (kinematic when it names none), so an error names the field under stack and not a union member."""
    if isinstance(value, (KinematicStackConfig, ArdupilotStackConfig)):
        return value
    layer = value.get("simulation_layer", "kinematic") if isinstance(value, Mapping) else None
    if layer != "kinematic" and layer not in ARDUPILOT_LAYERS and isinstance(value, Mapping):
        raise ValueError(f"unknown simulation_layer {layer!r}; a stack runs on kinematic, {', '.join(ARDUPILOT_LAYERS)}")
    return (ArdupilotStackConfig if layer in ARDUPILOT_LAYERS else KinematicStackConfig).model_validate(value)


StackConfig = Annotated[Union[KinematicStackConfig, ArdupilotStackConfig], WrapValidator(_stack_by_layer)]


class RunConfig(ConfigModel):
    name: Optional[str] = None
    stack: StackConfig = Field(default_factory=KinematicStackConfig)
    environment: EnvironmentSettings = Field(default_factory=EnvironmentSettings)
    seed: Optional[int] = Field(default=None, ge=0, le=MAX_SEED)  # one run seed for every case; the case seed when absent
    repeats: int = Field(default=1, ge=1)  # runs with the same seed, for calibration
    monitor: MonitorImplementation = MonitorImplementation.POST_HOC
    early_stop: bool = False  # live only: stop the run once every rule is decided

    @model_validator(mode="after")
    def _early_stop_needs_the_live_monitor(self) -> "RunConfig":
        if self.early_stop and self.monitor != MonitorImplementation.LIVE:
            raise ValueError("early_stop needs the live monitor")
        if self.early_stop and isinstance(self.stack, ArdupilotStackConfig):
            raise ValueError("the ArduPilot stacks do not stop early: the lockstep run always finishes")
        return self

    def seed_for(self, case_seed_value: int) -> int:
        """The seed the run uses for a case: its own when it fixes one, else the case seed."""
        return self.seed if self.seed is not None else case_seed_value


class ExecutionConfig(ConfigModel):
    runs: Tuple[RunConfig, ...] = Field(default_factory=lambda: (RunConfig(),), min_length=1)


# Resources


class QueueDepthCaps(ConfigModel):
    """Queued jobs of the campaign per stage; a new case starts only while every stage is under its cap."""

    generate_scene: int = Field(default=16, ge=1)
    generate_trajectories: int = Field(default=16, ge=1)
    simulate: int = Field(default=32, ge=1)
    monitor: int = Field(default=32, ge=1)
    calibrate: int = Field(default=8, ge=1)

    def cap(self, stage: PipelineStage) -> int:
        """The cap of a stage; the scene and trajectory monitors share the monitor's, since all three run monitoring.post_hoc."""
        if stage == PipelineStage.VERDICT:
            raise ValueError("the verdict stage queues no jobs")
        if stage in (PipelineStage.MONITOR_SCENE, PipelineStage.MONITOR_TRAJECTORIES):
            return self.monitor
        return getattr(self, stage.value)


class ResourcesConfig(ConfigModel):
    nodes: Tuple[str, ...] = ()  # node ids the campaign's jobs may run on; empty: every node, also those that join later
    required_labels: Dict[str, str] = Field(default_factory=dict)  # every job of the campaign needs these node labels
    queue_depth: QueueDepthCaps = Field(default_factory=QueueDepthCaps)
    priority: int = 0  # base priority of the campaign's jobs; later stages run above it

    @field_validator("nodes")
    @classmethod
    def _distinct_node_ids(cls, nodes: Tuple[str, ...]) -> Tuple[str, ...]:
        if any(not node.strip() for node in nodes):
            raise ValueError("a node id must not be empty")
        if len(set(nodes)) != len(nodes):
            raise ValueError("node ids must be distinct")
        return nodes


# Policy


class RetentionPolicy(str, Enum):
    ALL = "all"  # keep every artifact
    FAILURES = "failures"  # trajectories and state logs only of failed verdicts and failed cases
    VERDICTS_ONLY = "verdicts_only"  # no artifacts once a case has its verdicts


class StopConditions(ConfigModel):
    max_cases: Optional[int] = Field(default=None, ge=1)  # no new cases after this many over all classes
    max_failed_verdicts: Optional[int] = Field(default=None, ge=1)  # drain once this many verdicts failed
    max_duration_s: Optional[float] = Field(default=None, gt=0)  # drain after this long running


class PolicyConfig(ConfigModel):
    retention: RetentionPolicy = RetentionPolicy.ALL
    keep_frames: bool = False  # store the monitor's frames as artifacts
    seed: int = Field(default=0, ge=0, le=MAX_SEED)  # the campaign seed: the base the case seeds count up from
    stop: StopConditions = Field(default_factory=StopConditions)


# The config


# A scope entry's FECs: fecs from format 3 on, classes in formats 1 and 2 (and in their JSON, so their hashes stay)
FEC_KEY = "fecs"
LEGACY_FEC_KEY = "classes"
LEGACY_FORMATS = (1, 2)


def _renamed_scope(scope: Any, old: str, new: str) -> Any:
    """The scope entries with the key old renamed to new; anything that is not a list of mappings as it is, for validation to report."""
    if not isinstance(scope, (list, tuple)):
        return scope
    return [{(new if key == old else key): value for key, value in entry.items()} if isinstance(entry, Mapping) else entry for entry in scope]


# The format 2 fields; a format 1 config takes none of them and its JSON leaves them out
FORMAT_2_FIELDS = ("steps", "input", "scene_generation")
FORMAT_2_TRAJECTORY_FIELDS = ("monitor",)
FORMAT_1_EXCLUDED: Dict[str, Any] = {**{name: True for name in FORMAT_2_FIELDS}, "trajectories": set(FORMAT_2_TRAJECTORY_FIELDS)}


class CampaignConfig(ConfigModel):
    format: Literal[1, 2, 3] = CONFIG_FORMAT
    name: str = Field(min_length=1, max_length=256)
    description: str = ""
    steps: Tuple[CampaignStep, ...] = CHAIN
    scope: Tuple[ScopeEntry, ...] = ()  # catalog FECs; a format 1 config needs at least one entry
    input: InputConfig = Field(default_factory=InputConfig)
    domain: DomainConfig = Field(default_factory=DomainConfig)
    scene_generation: SceneGenerationConfig = Field(default_factory=SceneGenerationConfig)
    trajectories: TrajectoriesConfig = Field(default_factory=TrajectoriesConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    resources: ResourcesConfig = Field(default_factory=ResourcesConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)

    @model_validator(mode="before")
    @classmethod
    def _fec_key_of_the_format(cls, data: Any) -> Any:
        """Takes a scope entry's FECs under the name of the config's format: classes in formats 1 and 2, fecs from format 3 on."""
        config_format = data.get("format", CONFIG_FORMAT) if isinstance(data, Mapping) else None
        if config_format not in (*LEGACY_FORMATS, LATEST_FORMAT) or not isinstance(data.get("scope"), (list, tuple)):
            return data  # an unknown format is reported by the format field
        legacy = config_format in LEGACY_FORMATS
        wrong = FEC_KEY if legacy else LEGACY_FEC_KEY
        misnamed = [str(index) for index, entry in enumerate(data["scope"]) if isinstance(entry, Mapping) and wrong in entry]
        if misnamed:
            hint = "fecs need format 3; formats 1 and 2 call them classes" if legacy else "format 3 calls them fecs, not classes"
            raise ValueError(f"scope.{', scope.'.join(misnamed)}: {hint}")
        return {**data, "scope": _renamed_scope(data["scope"], LEGACY_FEC_KEY, FEC_KEY)} if legacy else data

    @field_validator("steps")
    @classmethod
    def _consecutive_steps(cls, steps: Tuple[CampaignStep, ...]) -> Tuple[CampaignStep, ...]:
        if not steps:
            raise ValueError("a campaign runs at least one step")
        positions = [CHAIN.index(step) for step in steps]
        if positions != list(range(positions[0], positions[0] + len(steps))):
            raise ValueError(f"steps must be consecutive and in chain order ({', '.join(step.value for step in CHAIN)}), got {[step.value for step in steps]}")
        return steps

    @model_validator(mode="after")
    def _fields_of_the_format(self) -> "CampaignConfig":
        if self.format == 1:
            newer = [name for name in FORMAT_2_FIELDS if name in self.model_fields_set]
            newer += [f"trajectories.{name}" for name in FORMAT_2_TRAJECTORY_FIELDS if name in self.trajectories.model_fields_set]
            if newer:
                raise ValueError(f"{', '.join(newer)} need format 2")
            if not self.scope:
                raise ValueError("a format 1 config needs at least one scope entry")
        return self

    @property
    def first_step(self) -> CampaignStep:
        return self.steps[0]

    def runs_step(self, step: CampaignStep) -> bool:
        return step in self.steps

    def to_json(self) -> Dict[str, Any]:
        """The config as JSON with every default filled in: what the database stores and the hash covers.

        A format 1 config leaves the format 2 fields out, so its hash is the one it always had;
        formats 1 and 2 write a scope entry's FECs as classes, as they always did.
        """
        data = self.model_dump(mode="json", exclude=FORMAT_1_EXCLUDED) if self.format == 1 else self.model_dump(mode="json")
        if self.format in LEGACY_FORMATS:
            data["scope"] = _renamed_scope(data["scope"], FEC_KEY, LEGACY_FEC_KEY)
        return data

    def config_hash(self) -> str:
        return canonical_json_sha256(self.to_json())

    def case_seed(self, class_id: str, case_index: int) -> int:
        return case_seed(self.policy.seed, class_id, case_index)


# Seeds


def case_seed(campaign_seed: int, class_id: str, case_index: int) -> int:
    """The seed of a case: the campaign seed plus the case index, within 31 bits.

    Case k of every class gets campaign seed + k. An item class (item/<n>) has one case and
    counts from its item number instead, so the items of a campaign get seeds apart.
    """
    if case_index < 0:
        raise ValueError(f"case indexes start at 0, got {case_index}")
    offset = case_index
    item = class_id[len(ITEM_CLASS_PREFIX) :] if class_id.startswith(ITEM_CLASS_PREFIX) else ""
    if item.isdigit():
        offset += int(item)
    return (campaign_seed + offset) % (MAX_SEED + 1)


# Loading


class CampaignConfigError(ValueError):
    """A config that does not load or is not valid; reasons lists every problem found."""

    def __init__(self, reasons):
        self.reasons = tuple(reasons)
        super().__init__("; ".join(self.reasons))


class _UniqueKeyLoader(yaml.SafeLoader):
    """yaml.safe_load that refuses a mapping with a key twice instead of keeping the last value."""


def _construct_unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False):
    keys = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in keys:
            raise yaml.constructor.ConstructorError("while constructing a mapping", node.start_mark, f"found the key {key!r} twice", key_node.start_mark)
        keys.add(key)
    return loader.construct_mapping(node, deep=deep)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


def _reasons(error: ValidationError) -> Tuple[str, ...]:
    return tuple(f"{'.'.join(str(part) for part in issue['loc']) or 'config'}: {issue['msg']}" for issue in error.errors())


def campaign_config_from_dict(data: Mapping[str, Any]) -> CampaignConfig:
    try:
        return CampaignConfig.model_validate(dict(data))
    except ValidationError as error:
        raise CampaignConfigError(_reasons(error)) from error


def with_domain_defaults(data: Mapping[str, Any], domain_defaults: Optional[Mapping[str, str]]) -> Dict[str, Any]:
    """The config's sections with the domain contents it leaves out taken from domain_defaults (the cluster's domain configuration).

    A domain section that is not a mapping is left as it is, so validation reports it.
    """
    filled = dict(data)
    if not domain_defaults:
        return filled
    domain = filled.get("domain", {})
    if not isinstance(domain, dict):
        return filled
    filled["domain"] = {**{key: domain_defaults[key] for key in DOMAIN_KEYS if key in domain_defaults and key not in domain}, **domain}
    return filled


def parse_campaign_config(text: str, domain_defaults: Optional[Mapping[str, str]] = None) -> CampaignConfig:
    """A config from YAML text (JSON is YAML too); domain contents it leaves out come from domain_defaults when given, else the default presets."""
    try:
        data = yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506 (a SafeLoader subclass)
    except yaml.YAMLError as error:
        raise CampaignConfigError([f"not valid YAML: {error}"]) from error
    if not isinstance(data, dict):
        raise CampaignConfigError(["a campaign config is a mapping of its sections"])
    return campaign_config_from_dict(with_domain_defaults(data, domain_defaults))


def load_campaign_config(path: Union[str, Path]) -> CampaignConfig:
    return parse_campaign_config(Path(path).read_text(encoding="utf-8"))
