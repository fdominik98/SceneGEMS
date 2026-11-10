"""Resolver: does a stack combination exist, what does it support, and is a request valid on it.

For a requested (ASV system, control layer, simulation layer) the resolver looks up the
two adapters that connect the three layers. Where several adapters connect the same two
layers, the registry's default is taken unless the vessel selects another one by id
(VesselConfig.adapter_ids). A missing adapter makes the combination
unavailable, with the reason of the ruled-out connection when the design declares one.
When the chain exists, its capabilities are the weakest link over its three layers and two
adapters. A request (environment, speedup, attended or not) is then checked against them:
unsupported wind or waves, and a speedup the chain cannot run, are rejected with a reason
and never dropped silently.

A real vessel of an instance is resolved too, on its own layers (real_vessel control and
simulation): it is outside the shared simulation layer and the requested environment, but its
limits (real time, no lockstep, workbench only) are part of the instance's weakest link.
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, AnySpec, SpecStatus
from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities, EnvironmentSupport, RepeatabilityTier, weakest_link
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, LayerRef, Role, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig, SimulationInstanceConfig, VesselStackConfig
from scenegems_tool.vessel_stack.registry.adapter_registry import AdapterRegistry

_REAL_VESSEL_LAYERS = (ControlLayerId.REAL_VESSEL, SimulationLayerId.REAL_VESSEL)


class StackUnavailableError(ValueError):
    def __init__(self, reasons: Iterable[str]):
        self.reasons = tuple(reasons)
        super().__init__("; ".join(self.reasons))


@dataclass(frozen=True)
class ChainResolution:
    stack: VesselStackConfig
    specs: Tuple[AnySpec, ...]  # registered layers and adapters on the chain, from ASV system down
    complete: bool  # every layer and adapter of the chain exists, implemented or planned
    reasons: Tuple[str, ...]  # why the combination cannot be used now; empty when available

    @property
    def available(self) -> bool:
        return self.complete and not self.reasons

    @property
    def planned_specs(self) -> Tuple[AnySpec, ...]:
        return tuple(spec for spec in self.specs if spec.status == SpecStatus.PLANNED)

    @property
    def adapters(self) -> Tuple[AdapterSpec, ...]:
        return tuple(spec for spec in self.specs if isinstance(spec, AdapterSpec))

    @property
    def asv_adapter(self) -> Optional[AdapterSpec]:
        """The adapter from the ASV system to the control layer, which decides how the ASV system is run."""
        return next((adapter for adapter in self.adapters if adapter.from_role == Role.ASV_SYSTEM), None)

    @property
    def capabilities(self) -> Optional[Capabilities]:
        """Weakest link over the chain; None when the chain does not exist."""
        if not self.complete:
            return None
        return weakest_link(spec.capabilities for spec in self.specs)

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons)

    @property
    def design_status(self) -> str:
        """The availability the design promises once every planned adapter exists."""
        capabilities = self.capabilities
        if capabilities is None:
            return "no"
        return "yes, interactive only" if capabilities.interactive_only else "yes"

    @property
    def status(self) -> str:
        if self.available:
            return "available"
        if self.complete:
            phases = sorted({spec.planned_phase for spec in self.planned_specs if spec.planned_phase is not None})
            return f"planned (phase {', '.join(str(phase) for phase in phases)})" if phases else "planned"
        return "unavailable"


@dataclass(frozen=True)
class InstanceResolution:
    instance: SimulationInstanceConfig
    chains: Mapping[str, ChainResolution]  # by agent id, real vessels included
    capabilities: Optional[Capabilities]  # weakest link over every vessel chain, since all share one clock
    errors: Tuple[str, ...]
    warnings: Tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return not self.errors

    @property
    def reason(self) -> str:
        return "; ".join(self.errors)

    @property
    def repeatability_tier(self) -> Optional[RepeatabilityTier]:
        """Tier of this run at the requested speedup."""
        if self.capabilities is None:
            return None
        return self.capabilities.repeatability_at(self.instance.speedup)

    def require(self) -> "InstanceResolution":
        if self.errors:
            raise StackUnavailableError(self.errors)
        return self

    def effective_environment(self) -> Dict[str, Any]:
        """Environment the run applies, for the run record. Only an accepted request has one."""
        environment = self.instance.environment
        wave = environment.wave
        return {
            "wind_vector": [float(component) for component in environment.wind_vector] if environment.wind_requested else None,
            "waves": (
                {"amplitude": wave.amplitude, "period": wave.period, "steepness": wave.steepness, "direction": [float(component) for component in wave.direction]}
                if environment.waves_requested
                else None
            ),
            "seed": environment.seed,
        }


class StackResolver:
    def __init__(self, registry: AdapterRegistry):
        self.registry = registry

    def resolve(self, stack: VesselStackConfig, adapter_ids: Iterable[str] = ()) -> ChainResolution:
        """Resolve one triple. adapter_ids selects alternatives to the default adapter of a connection."""
        adapter_ids = tuple(adapter_ids)
        refs = (LayerRef.of(stack.asv_system), LayerRef.of(stack.control_layer), LayerRef.of(stack.simulation_layer))
        connections = tuple(zip(refs, refs[1:]))
        layers = [self.registry.layer(ref) for ref in refs]
        adapters = [self.registry.adapter_between(upper, lower, adapter_ids) for upper, lower in connections]
        reasons = [f"{ref} is not registered" for ref, layer in zip(refs, layers) if layer is None]
        for adapter_id in adapter_ids:
            if not self.registry.has_adapter(adapter_id):
                reasons.append(f"adapter {adapter_id} is not registered")
            elif all(adapter is None or adapter.id != adapter_id for adapter in adapters):
                selected = self.registry.adapter(adapter_id)
                reasons.append(f"adapter {adapter_id} connects {selected.source} to {selected.target}, which is not part of ({stack})")
        for (upper, lower), adapter in zip(connections, adapters):
            if adapter is None:
                unsupported = self.registry.unsupported_between(upper, lower)
                reasons.append(f"no adapter from {upper} to {lower}: {unsupported.reason}" if unsupported else f"no adapter from {upper} to {lower} is registered")
        chain = (layers[0], adapters[0], layers[1], adapters[1], layers[2])
        specs = tuple(spec for spec in chain if spec is not None)
        complete = len(specs) == len(chain)
        if complete:
            for spec in specs:
                if spec.status == SpecStatus.PLANNED:
                    phase = f" for phase {spec.planned_phase}" if spec.planned_phase is not None else ""
                    reasons.append(f"{spec.id} is planned{phase} and not implemented yet")
        return ChainResolution(stack=stack, specs=specs, complete=complete, reasons=tuple(reasons))

    def resolve_instance(self, instance: SimulationInstanceConfig, *, attended: bool = True, host: Optional[str] = None) -> InstanceResolution:
        """Validate a whole simulation instance.

        attended=False is an unattended campaign run. host names the machine that will run it,
        so a per-host max_speedup applies; without it a per-host value only warns.
        """
        errors: List[str] = []
        warnings: List[str] = []
        chains: Dict[str, ChainResolution] = {}
        if instance.simulation_layer == SimulationLayerId.REAL_VESSEL:
            errors.append("an instance runs on a simulation layer; real_vessel is the layer of a real vessel only")
        for agent_id, vessel in instance.vessels.items():
            if not vessel.is_simulated and (vessel.stack.control_layer, vessel.stack.simulation_layer) != _REAL_VESSEL_LAYERS:
                errors.append(f"vessel {agent_id} is a real vessel, so its control and simulation layers are real_vessel, not ({vessel.stack})")
            elif vessel.is_simulated and vessel.stack.simulation_layer != instance.simulation_layer:
                errors.append(f"vessel {agent_id} uses simulation layer {vessel.stack.simulation_layer.value}, but all vessels of one instance share {instance.simulation_layer.value}")
            chain = self.resolve(vessel.stack, vessel.adapter_ids)
            chains[agent_id] = chain
            if not chain.available:
                errors.append(f"vessel {agent_id} ({vessel.stack}): {chain.reason}")
        if errors or not chains:
            return InstanceResolution(instance=instance, chains=chains, capabilities=None, errors=tuple(errors), warnings=tuple(warnings))

        specs = _unique(spec for chain in chains.values() for spec in chain.specs)
        capabilities = weakest_link(spec.capabilities for spec in specs)
        # Requested wind and waves act on the shared simulation; a real vessel meets the real weather.
        simulated_specs = _unique(spec for agent_id, chain in chains.items() if instance.vessels[agent_id].is_simulated for spec in chain.specs)
        _check_environment(simulated_specs, instance.environment, errors, warnings)
        self._check_speedup(specs, instance.speedup, host, errors, warnings)
        if capabilities.interactive_only and not attended:
            for spec in specs:
                if spec.capabilities.interactive_only:
                    errors.append(_with_note(f"{spec.id} is interactive only and is rejected for unattended runs", spec, "interactive_only"))
        return InstanceResolution(instance=instance, chains=chains, capabilities=capabilities, errors=tuple(errors), warnings=tuple(warnings))

    def require_instance(self, instance: SimulationInstanceConfig, *, attended: bool = True, host: Optional[str] = None) -> InstanceResolution:
        return self.resolve_instance(instance, attended=attended, host=host).require()

    def _check_speedup(self, specs: Iterable[AnySpec], speedup: float, host: Optional[str], errors: List[str], warnings: List[str]) -> None:
        if speedup < 1:
            errors.append(f"speedup {speedup:g} is below 1; slower than real time is not supported")
            return
        if speedup == 1:
            return
        real_time_only = [spec.id for spec in specs if not spec.capabilities.faster_than_real_time]
        if real_time_only:
            errors.append(f"speedup {speedup:g} requested, but {', '.join(real_time_only)} cannot run faster than real time, so this stack is capped at 1x")
            return
        unverified = []
        exceeded = False
        for spec in specs:
            limit = spec.capabilities.max_speedup
            measurement = self.registry.measurement(spec.id)
            if limit is None and measurement is not None:
                limit = measurement.max_speedup_on(host)
            if limit is None:
                per_host = ", ".join(f"{value:g}x on {label}" for label, value in measurement.host_max_speedup) if measurement is not None else ""
                unverified.append(f"{spec.id} (measured per host: {per_host})" if per_host else spec.id)
            elif speedup > limit:
                exceeded = True
                where = f" on {host}" if spec.capabilities.max_speedup is None else ""
                errors.append(f"speedup {speedup:g} exceeds the measured max_speedup {limit:g} of {spec.id}{where}")
        if unverified and not exceeded:
            warnings.append(f"speedup {speedup:g} is unverified: max_speedup of {', '.join(unverified)} is not measured for this host")

    def availability_matrix(self) -> List[ChainResolution]:
        """Every combination of the three roles, in the order of the design's availability table."""
        return [
            self.resolve(VesselStackConfig(asv_system=asv_system, control_layer=control_layer, simulation_layer=simulation_layer))
            for asv_system in AsvSystemId
            for simulation_layer in SimulationLayerId
            for control_layer in ControlLayerId
        ]


def _unique(specs: Iterable[AnySpec]) -> Tuple[AnySpec, ...]:
    seen: Dict[str, AnySpec] = {}
    for spec in specs:
        seen.setdefault(spec.id, spec)
    return tuple(seen.values())


def _with_note(message: str, spec: AnySpec, capability: str) -> str:
    note = spec.note_for(capability)
    return f"{message}: {note}" if note else message


def _check_environment(specs: Iterable[AnySpec], environment: EnvironmentConfig, errors: List[str], warnings: List[str]) -> None:
    for capability, requested in (("wind", environment.wind_requested), ("waves", environment.waves_requested)):
        if not requested:
            continue
        for spec in specs:
            support = getattr(spec.capabilities, capability)
            if support == EnvironmentSupport.UNSUPPORTED:
                errors.append(_with_note(f"{capability} requested, but {spec.id} does not support {capability}", spec, capability))
            elif support == EnvironmentSupport.UNMEASURED:
                warnings.append(_with_note(f"{capability} requested, but support for {capability} in {spec.id} is unmeasured", spec, capability))
