"""Validation of a campaign config against the class catalog, the artifact store and the vessel stack resolver.

A config is accepted only as a whole: the input must match the first step it runs (catalog
classes or functional scenarios given as content for scene generation, scene items for
trajectory generation, trajectory items for simulation), every scope entry must name
classes the catalog has (a pattern must match at least one), no class may be named by two
entries, every input reference must name an artifact the store has, and every run's stack
must be available on the resolver for an unattended run in its environment. Sections of
steps the campaign does not run are not checked (no runs are resolved without the
simulation step). Every problem is reported with its reason; nothing is dropped silently.

The result carries what creating the campaign needs: the config as JSON and its hash, and
the classes with their pinned content hashes, quotas and failure budgets: catalog classes
in scope order, then the functional scenarios given as content, then the items.
"""

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from scenegems_tool.assurance.campaign.campaign_config import (
    ArdupilotStackConfig,
    CampaignConfig,
    CampaignConfigError,
    CampaignStep,
    CustomStackConfig,
    InputArtifactKind,
    InputRef,
    RunConfig,
    StackConfig,
    budget_limit,
)
from scenegems_tool.assurance.campaign.campaign_inputs import InputContentError, item_class_spec, scenario_class_spec
from scenegems_tool.assurance.campaign.class_catalog import ClassCatalog
from scenegems_tool.cluster.node.jobs.simulation_runners.kinematic_runner import KinematicMode
from scenegems_tool.persistence.stores import ClassSpec
from scenegems_tool.vessel_stack.asv_software.replay.replay_specs import REPLAY_MAVLINK_LOCKSTEP
from scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_specs import USV_NAVIGATION_MAVLINK_LOCKSTEP
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig, SimulationInstanceConfig, VesselConfig, VesselStackConfig, WaveConfig
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from scenegems_tool.vessel_stack.registry.resolver import StackResolver

OWN_SHIP, TARGET_SHIP = "own_ship", "target_ship"

ArtifactExists = Callable[[str], bool]  # whether the artifact store has the artifact with this sha256
ReadArtifact = Callable[[str], bytes]  # the content of the artifact with this sha256

# The item kinds a campaign takes by its first step; one that starts with scene generation takes no items
ITEM_KINDS_OF_FIRST_STEP = {
    CampaignStep.TRAJECTORY_GENERATION: (InputArtifactKind.SCENE,),
    CampaignStep.SIMULATION: (InputArtifactKind.TRAJECTORY_DATA, InputArtifactKind.TRAJECTORIES),
}


class CampaignConfigRejected(CampaignConfigError):
    """The config is well formed, but the catalog or the resolver refuses it."""


@dataclass(frozen=True)
class RunStacks:
    """The stacks of one run as the resolver accepted them."""

    run_index: int
    vessels: Dict[str, VesselStackConfig]  # own_ship, and target_ship for the other vessels
    repeatability_tier: Optional[str]  # exact, bounded or none
    environment: Dict  # the environment the run applies (wind, waves), for the run record; the seed is per case
    warnings: Tuple[str, ...]


@dataclass(frozen=True)
class ValidatedCampaign:
    config: CampaignConfig
    config_json: Dict
    config_hash: str
    classes: Tuple[ClassSpec, ...]  # catalog classes in scope order (each once), then scenario classes, then item classes
    runs: Tuple[RunStacks, ...]  # empty when the campaign does not simulate

    @property
    def total_quota(self) -> int:
        return sum(spec.quota for spec in self.classes)


# The lockstep MAVLink adapter of each ASV software on ArduPilot, as the ardupilot runner's instance names them (mavlink_lockstep_runner.mavlink_instance)
ARDUPILOT_ADAPTERS = {AsvSoftwareId.REPLAY: REPLAY_MAVLINK_LOCKSTEP.id, AsvSoftwareId.USV_NAVIGATION: USV_NAVIGATION_MAVLINK_LOCKSTEP.id}


def _layers(stack: StackConfig) -> Tuple[ControlLayerId, SimulationLayerId]:
    if isinstance(stack, ArdupilotStackConfig):
        return ControlLayerId.ARDUPILOT, SimulationLayerId(stack.simulation_layer)
    if isinstance(stack, CustomStackConfig):
        return ControlLayerId.CUSTOM, SimulationLayerId(stack.simulation_layer)
    return ControlLayerId.NONE, SimulationLayerId.KINEMATIC


def vessel_stacks(stack: StackConfig) -> Dict[str, VesselStackConfig]:
    """The triple of the own ship and of the target ships for a run's stack: every vessel replays, and in mode usv_navigation the own ship runs USV Navigation."""
    control_layer, simulation_layer = _layers(stack)
    replay = VesselStackConfig(AsvSoftwareId.REPLAY, control_layer, simulation_layer)
    if stack.mode == KinematicMode.USV_NAVIGATION:
        return {OWN_SHIP: VesselStackConfig(AsvSoftwareId.USV_NAVIGATION, control_layer, simulation_layer), TARGET_SHIP: replay}
    return {OWN_SHIP: replay, TARGET_SHIP: replay}


def _vessel_config(agent_id: str, stack: VesselStackConfig, run_stack: StackConfig) -> VesselConfig:
    """A vessel of the run's instance; on ArduPilot the lockstep adapter is named, as the ardupilot runner's instance names it."""
    adapters = (ARDUPILOT_ADAPTERS[stack.asv_software],) if isinstance(run_stack, ArdupilotStackConfig) else ()
    return VesselConfig(agent_id=agent_id, stack=stack, adapter_ids=adapters)


def _environment(run: RunConfig) -> EnvironmentConfig:
    waves = run.environment.waves
    wave = WaveConfig(amplitude=0.0, period=0.0, steepness=0.0, direction=np.zeros(2))
    if waves is not None:
        wave = WaveConfig(amplitude=waves.amplitude, period=waves.period, steepness=waves.steepness, direction=np.array(waves.direction, dtype=float))
    return EnvironmentConfig(wind_vector=np.array(run.environment.wind_vector, dtype=float), wave=wave)


def _calm_only(run: RunConfig) -> List[str]:
    """Why a run on an ArduPilot stack cannot carry this environment: the ArduPilot simulation jobs run calm water, so wind and waves would be dropped silently."""
    environment = run.environment
    reasons = []
    if any(component != 0.0 for component in environment.wind_vector):
        reasons.append("the ArduPilot stacks run without wind: the ArduPilot simulation jobs apply no environment, so environment.wind_vector must stay zero")
    if environment.waves is not None:
        reasons.append("the ArduPilot stacks run without waves: the ArduPilot simulation jobs apply no environment, so environment.waves must stay absent")
    return reasons


def resolve_run(run: RunConfig, run_index: int, resolver: StackResolver) -> Tuple[Optional[RunStacks], List[str]]:
    """The run's stacks on the resolver, as an unattended run; the reasons when it refuses them."""
    label = f"execution.runs.{run_index}" + (f" ({run.name})" if run.name else "")
    stacks = vessel_stacks(run.stack)
    reasons = _calm_only(run) if isinstance(run.stack, ArdupilotStackConfig) else []
    instance = SimulationInstanceConfig(
        simulation_layer=SimulationLayerId(run.stack.simulation_layer),
        environment=_environment(run),
        vessels={agent_id: _vessel_config(agent_id, stack, run.stack) for agent_id, stack in stacks.items()},
        speedup=run.stack.speedup if isinstance(run.stack, ArdupilotStackConfig) else 1,
    )
    resolution = resolver.resolve_instance(instance, attended=False)
    reasons += list(resolution.errors)
    if reasons or not resolution.accepted:
        return None, [f"{label}: {error}" for error in reasons]
    tier = resolution.repeatability_tier
    environment = {key: value for key, value in resolution.effective_environment().items() if key != "seed"}
    return RunStacks(run_index, stacks, None if tier is None else tier.value, environment, resolution.warnings), []


def resolve_scope(config: CampaignConfig, catalog: ClassCatalog) -> Tuple[Tuple[ClassSpec, ...], List[str]]:
    """The classes of the scope in order, each once, with their entry's quota and failure budget."""
    reasons: List[str] = []
    chosen: Dict[str, Tuple[int, ClassSpec]] = {}
    for entry_index, entry in enumerate(config.scope):
        named = []
        for class_id in entry.fecs:
            if class_id in catalog:
                named.append(catalog.get(class_id))
            else:
                reasons.append(f"scope.{entry_index}: no FEC {class_id!r} in the catalog")
        for pattern in entry.patterns:
            matched = catalog.expand(pattern)
            if not matched:
                reasons.append(f"scope.{entry_index}: the pattern {pattern!r} matches no FEC")
            named.extend(matched)
        for scenario_class in named:
            earlier = chosen.get(scenario_class.class_id)
            if earlier is not None:
                if earlier[0] != entry_index:
                    reasons.append(f"scope.{entry_index}: FEC {scenario_class.class_id!r} is in scope.{earlier[0]} already")
                continue
            spec = ClassSpec(
                class_id=scenario_class.class_id,
                content_hash=scenario_class.content_hash,
                vessel_count=scenario_class.vessel_count,
                obstacle_count=scenario_class.obstacle_count,
                quota=entry.quota,
                failure_budget=budget_limit(entry.failure_budget),
            )
            chosen[scenario_class.class_id] = (entry_index, spec)
    return tuple(spec for _, spec in chosen.values()), reasons


def check_input(config: CampaignConfig) -> List[str]:
    """The input matches the first step: catalog classes or functional scenarios for scene generation, items of the right kind after it."""
    first, reasons = config.first_step, []
    scenarios, items = config.input.functional_scenarios, config.input.items
    if first == CampaignStep.SCENE_GENERATION:
        if not config.scope and not scenarios:
            reasons.append("input: a campaign that starts with scene_generation needs scope entries or input.functional_scenarios")
        if items:
            reasons.append("input.items: a campaign that starts with scene_generation takes catalog FECs or functional scenarios, not items")
        return reasons
    if config.scope:
        reasons.append(f"scope: a campaign that starts with {first.value} takes input.items, not catalog FECs")
    if scenarios:
        reasons.append(f"input.functional_scenarios: a campaign that starts with {first.value} takes input.items, not functional scenarios")
    if not items:
        reasons.append(f"input.items: a campaign that starts with {first.value} needs at least one item")
    kinds = ITEM_KINDS_OF_FIRST_STEP[first]
    for index, item in enumerate(items):
        if item.ref.kind not in kinds:
            reasons.append(f"input.items.{index} ({item.name}): a campaign that starts with {first.value} takes {' or '.join(kind.value for kind in kinds)} items, not {item.ref.kind.value}")
    return reasons


def resolve_input(config: CampaignConfig, artifact_exists: Optional[ArtifactExists], read_artifact: Optional[ReadArtifact]) -> Tuple[Tuple[ClassSpec, ...], List[str]]:
    """The classes of the functional scenarios given as content and of the items, read from the artifact store."""
    entries: List[Tuple[str, InputRef, Callable[[bytes], ClassSpec]]] = []
    for index, scenario in enumerate(config.input.functional_scenarios):
        entries.append((f"input.functional_scenarios.{index} ({scenario.name})", scenario.ref, lambda content, scenario=scenario: scenario_class_spec(scenario, content)))
    for index, item in enumerate(config.input.items):
        entries.append((f"input.items.{index} ({item.name})", item.ref, lambda content, index=index, item=item: item_class_spec(index, item, content)))
    if not entries:
        return (), []
    if artifact_exists is None or read_artifact is None:
        return (), ["input: there is no artifact store to check the input references against"]
    classes, reasons = [], []
    for label, ref, make_class in entries:
        if not artifact_exists(ref.sha256):
            reasons.append(f"{label}: no artifact {ref.sha256} in the artifact store")
            continue
        try:
            classes.append(make_class(read_artifact(ref.sha256)))
        except InputContentError as error:
            reasons.append(f"{label}: {error}")
    return tuple(classes), reasons


def validate_campaign_config(
    config: CampaignConfig,
    catalog: Optional[ClassCatalog] = None,
    resolver: Optional[StackResolver] = None,
    artifact_exists: Optional[ArtifactExists] = None,
    read_artifact: Optional[ReadArtifact] = None,
) -> ValidatedCampaign:
    """Checks the config against the catalog, the artifact store and the resolver; raises CampaignConfigRejected with every reason.

    artifact_exists and read_artifact reach the master's artifact store; a config with
    functional scenarios or items given is rejected without them.
    """
    catalog = catalog or ClassCatalog.default()
    reasons = check_input(config)
    scope_classes, scope_reasons = resolve_scope(config, catalog)
    input_classes, input_reasons = resolve_input(config, artifact_exists, read_artifact)
    reasons += scope_reasons + input_reasons
    runs = []
    if config.runs_step(CampaignStep.SIMULATION):
        resolver = resolver or default_resolver()
        for run_index, run in enumerate(config.execution.runs):
            resolved, run_reasons = resolve_run(run, run_index, resolver)
            reasons.extend(run_reasons)
            if resolved is not None:
                runs.append(resolved)
    if reasons:
        raise CampaignConfigRejected(reasons)
    config_json = config.to_json()
    return ValidatedCampaign(config=config, config_json=config_json, config_hash=config.config_hash(), classes=scope_classes + input_classes, runs=tuple(runs))
