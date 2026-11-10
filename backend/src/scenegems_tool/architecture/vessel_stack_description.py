"""The vessel stack as an architecture document, read from the registry.

Nothing here declares a layer or an adapter: the nodes are the registry's LayerSpecs, the edges its AdapterSpecs, the
ruled-out connections come from the catalog, the combinations from the resolver's availability matrix, the cluster job
of each available combination from cluster/fingerprints/components.py (RUNNER_STACKS) and the measured values from
vessel_stack/registry/measured_capabilities.yaml, as the registry merged them into the specs. A new
simulator, controller or adapter registered in vessel_stack/registry/catalog.py shows up without a change here.

The metamodel is read from the contracts: the roles, the ports, the spec dataclasses an implementation fills in and
the protocols a Docker-backed layer implements.
"""

import dataclasses
import inspect
import re
from typing import Dict, Iterable, List, Optional, Tuple

from scenegems_tool.architecture.architecture_model import (
    GROUP_CAPABILITY,
    GROUP_PROPERTY,
    KIND_COMPONENT,
    KIND_INTERFACE,
    KIND_ROLE,
    ROLE_STEP,
    STATUS_AVAILABLE,
    STATUS_PLANNED,
    ArchitectureDocument,
    ArchitectureEdge,
    ArchitectureNode,
    Combination,
    Fact,
    Lane,
    MetamodelEdge,
    MetamodelNode,
    UnsupportedLink,
)
from scenegems_tool.cluster.fingerprints.components import runner_of_stack
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, AnySpec, ContainerSpec, LayerSpec, SpecStatus, UnsupportedConnection
from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities
from scenegems_tool.vessel_stack.contracts.clock import LockstepClock, LockstepParticipant
from scenegems_tool.vessel_stack.contracts.docker_stack import DockerControlLayer, DockerSimulationLayer
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import STACK_ROLE_ORDER, Role
from scenegems_tool.vessel_stack.registry.adapter_registry import AdapterRegistry
from scenegems_tool.vessel_stack.registry.resolver import ChainResolution, StackResolver

DOCUMENT_ID = "vessel_stack"
META_PREFIX = f"{DOCUMENT_ID}/"
META_ASV_TO_CONTROL = f"{META_PREFIX}adapter/asv_system_to_control_layer"
META_CONTROL_TO_SIMULATION = f"{META_PREFIX}adapter/control_layer_to_simulation_layer"
META_PARTICIPANT = f"{META_PREFIX}runtime/lockstep_participant"
META_DOCKER_CONTROL = f"{META_PREFIX}runtime/docker_control_layer"
META_DOCKER_SIMULATION = f"{META_PREFIX}runtime/docker_simulation_layer"
META_CLOCK = f"{META_PREFIX}runtime/lockstep_clock"

_LANE_TEXT = {
    Role.ASV_SYSTEM: ("ASV system", "Decides where the vessel goes."),
    Role.CONTROL_LAYER: ("Control layer", "Turns that decision into actuation."),
    Role.SIMULATION_LAYER: ("Simulation layer", "Moves the vessel and the world around it."),
}
_META_ADAPTER_BY_UPPER_ROLE = {Role.ASV_SYSTEM: META_ASV_TO_CONTROL, Role.CONTROL_LAYER: META_CONTROL_TO_SIMULATION}

_CAPABILITY_LABELS = {
    "faster_than_real_time": "Faster than real time",
    "lockstep": "Lockstep",
    "repeatability_tier": "Repeatability",
    "exact_up_to_speedup": "Exact up to speedup",
    "wind": "Wind",
    "waves": "Waves",
    "max_speedup": "Max speedup",
    "interactive_only": "Workbench only",
}
_UNIT_BY_FIELD = {"exact_up_to_speedup": "x", "max_speedup": "x"}

CLUSTER_JOB_FACT = "cluster_job"  # the job and runner that run an available combination on a worker node ("simulation, runner kinematic"), None when none does
_CLUSTER_JOB_NOTES = {
    "job": "campaigns and workbench simulations run it as this job, with this runner, on a worker node",
    "none": "no simulation runner runs it yet, so campaigns cannot use it; the workbench runs it as a live session",
    "workbench_only": "workbench only: an operator or a physical vessel is in the loop, so it runs as a live session",
}


def _meta_layer_id(role: Role) -> str:
    return f"{META_PREFIX}layer/{role.value}"


def _status(spec: AnySpec) -> str:
    return STATUS_PLANNED if spec.status == SpecStatus.PLANNED else STATUS_AVAILABLE


def _ports(ports: Iterable[Port]) -> Tuple[str, ...]:
    return tuple(sorted(port.value for port in ports))


def _container_facts(containers: Iterable[ContainerSpec]) -> Tuple[Fact, ...]:
    return tuple(
        Fact(f"container_{index}", "Container", container.image, GROUP_PROPERTY, note=f"entrypoint {container.entrypoint}" + (f", {container.cpus:g} CPU" if container.cpus else ""))
        for index, container in enumerate(containers)
    )


def capability_facts(capabilities: Capabilities, measured_fields: Iterable[str] = (), notes: Optional[Dict[str, str]] = None, measured_flag: Optional[bool] = None) -> Tuple[Fact, ...]:
    """One fact per capability field. A field is measured when the measurement file set it; None for max_speedup means not measured."""
    measured_fields = set(measured_fields)
    notes = notes or {}
    facts = []
    for field_name, value in capabilities.as_dict().items():
        note = notes.get(field_name)
        if field_name == "max_speedup" and value is None and note is None:
            note = "not measured"
        facts.append(
            Fact(
                field_name,
                _CAPABILITY_LABELS[field_name],
                value,
                GROUP_CAPABILITY,
                measured=(field_name in measured_fields) if measured_flag is None else measured_flag,
                unit=_UNIT_BY_FIELD.get(field_name),
                note=note,
            )
        )
    return tuple(facts)


def _measurement_facts(registry: AdapterRegistry, spec: AnySpec) -> Tuple[Tuple[Fact, ...], str]:
    """Capability facts of a spec, with the measured ones marked, and the evidence text."""
    measurement = registry.measurement(spec.id)
    measured_fields = {name for name, _ in measurement.overrides} if measurement else set()
    facts = list(capability_facts(spec.capabilities, measured_fields, dict(spec.restriction_notes)))
    evidence = ""
    if measurement is not None:
        evidence = measurement.evidence
        facts.extend(
            Fact(f"max_speedup_on_{host}", f"Max speedup on {host}", limit, GROUP_CAPABILITY, measured=True, unit="x", note="depends on the machine") for host, limit in measurement.host_max_speedup
        )
        if measurement.deviation_bounds_m:
            bounds = ", ".join(f"{speedup:g}x: {deviation:g} m" for speedup, deviation in measurement.deviation_bounds_m)
            facts.append(Fact("deviation_bounds_m", "Deviation between repeats", bounds, GROUP_CAPABILITY, measured=True, note="largest distance at equal scenario time"))
        for layer_id, layer_bounds in measurement.deviation_bounds_m_by_layer:
            bounds = ", ".join(f"{speedup:g}x: {deviation:g} m" for speedup, deviation in layer_bounds)
            facts.append(Fact(f"deviation_bounds_m_{layer_id}", f"Deviation on {layer_id}", bounds, GROUP_CAPABILITY, measured=True, note="largest distance at equal scenario time"))
    return tuple(facts), evidence


def _layer_node(registry: AdapterRegistry, spec: LayerSpec) -> ArchitectureNode:
    facts, evidence = _measurement_facts(registry, spec)
    tags = ("docker",) if spec.containers else ("in-process",)
    if spec.capabilities.interactive_only:
        tags += ("interactive",)
    if spec.on_board_asv_system:
        facts += (Fact("on_board_asv_system", "On board ASV system", True, GROUP_PROPERTY, note="the vessel can run with ASV system on_board"),)
    return ArchitectureNode(
        id=spec.id,
        lane=spec.layer.role.value,
        label=spec.layer.impl,
        description=spec.description,
        implements=_meta_layer_id(spec.layer.role),
        status=_status(spec),
        facts=(*facts, *_container_facts(spec.containers)),
        ports_provided=_ports(spec.provides_ports),
        ports_required=_ports(spec.requires_ports),
        tags=tags,
        evidence=evidence,
    )


def _adapter_edge(registry: AdapterRegistry, spec: AdapterSpec) -> ArchitectureEdge:
    facts, evidence = _measurement_facts(registry, spec)
    default = registry.adapters_between(spec.source, spec.target)[0].id == spec.id
    tags = ("docker",) if spec.containers else ("in-process",)
    if not default:
        tags += ("alternative",)
    if spec.built_in:
        tags += ("built-in",)
    return ArchitectureEdge(
        id=spec.id,
        source=str(spec.source),
        target=str(spec.target),
        label=spec.id,
        description=spec.description,
        implements=_META_ADAPTER_BY_UPPER_ROLE[spec.source.role],
        kind="adapter",
        status=_status(spec),
        default=default,
        facts=(*facts, *_container_facts(spec.containers)),
        ports_provided=_ports(spec.provides_ports),
        ports_required=_ports(spec.requires_ports),
        tags=tags,
        evidence=evidence,
    )


def cluster_job_fact(chain: ChainResolution) -> Fact:
    """Which job and runner run the available combination on a worker node; None, with the reason, when it runs on the workbench only."""
    runner = runner_of_stack(chain.stack)
    if runner is not None:
        return Fact(CLUSTER_JOB_FACT, "Cluster job", f"{JobType.SIMULATION.value}, runner {runner.value}", GROUP_PROPERTY, note=_CLUSTER_JOB_NOTES["job"])
    reason = "workbench_only" if chain.capabilities is not None and chain.capabilities.interactive_only else "none"
    return Fact(CLUSTER_JOB_FACT, "Cluster job", None, GROUP_PROPERTY, note=_CLUSTER_JOB_NOTES[reason])


def _combination(chain: ChainResolution) -> Combination:
    stack = chain.stack
    if chain.available:
        status = STATUS_AVAILABLE
    elif chain.complete:
        status = STATUS_PLANNED
    else:
        status = "unavailable"
    capabilities = chain.capabilities
    facts = () if capabilities is None else capability_facts(capabilities, measured_flag=False)
    if chain.available:
        facts = (*facts, cluster_job_fact(chain))
    return Combination(
        path=(f"asv_system/{stack.asv_system.value}", f"control_layer/{stack.control_layer.value}", f"simulation_layer/{stack.simulation_layer.value}"),
        status=status,
        reasons=chain.reasons,
        facts=facts,
    )


def _port_members() -> Tuple[str, ...]:
    """Each Port as 'id: what flows', the text taken from the comment after its definition in ports.py."""
    comments = dict(re.findall(r'^\s+[A-Z_]+ = "([a-z_]+)"\s+#\s*(.+)$', inspect.getsource(Port), flags=re.MULTILINE))
    return tuple(f"{port.value}: {comments.get(port.value, '')}".rstrip(": ") for port in Port)


def _protocol_members(protocol: type) -> Tuple[str, ...]:
    members = []
    for name, member in inspect.getmembers(protocol, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        parameters = [parameter for parameter in inspect.signature(member).parameters if parameter != "self"]
        members.append(f"{name}({', '.join(parameters)})")
    return tuple(members)


def _spec_fields(spec_type: type) -> Tuple[str, ...]:
    return tuple(item.name for item in dataclasses.fields(spec_type))


def _metamodel() -> Tuple[Tuple[MetamodelNode, ...], Tuple[MetamodelEdge, ...]]:
    spec_fields = ", ".join(_spec_fields(LayerSpec))
    adapter_fields = ", ".join(_spec_fields(AdapterSpec))
    layer_members = (f"LayerSpec({spec_fields})", "measured values: an entry under the spec id in measured_capabilities.yaml")
    nodes = (
        MetamodelNode(
            _meta_layer_id(Role.ASV_SYSTEM),
            Role.ASV_SYSTEM.value,
            "ASV system layer",
            "The software that decides where a vessel goes: it reads the vessel's state and issues heading and speed commands, waypoints or MAVLink missions.",
            KIND_ROLE,
            (*layer_members, "AsvSystemId member", "a runtime bound by a loader in registry/catalog.py"),
            (
                "Add an AsvSystemId member and a LayerSpec in <impl>_specs.py, serve the software over the lockstep wire protocol (contracts/lockstep_wire.py) "
                "in a container of its own, register it in registry/catalog.py with the class that adds that container to a stack, connect it to a control "
                "layer with an adapter, and add its entry to asv_system/asv_system_runtime.py."
            ),
            "scenegems_tool/vessel_stack/asv_system",
        ),
        MetamodelNode(
            _meta_layer_id(Role.CONTROL_LAYER),
            Role.CONTROL_LAYER.value,
            "Control layer",
            "Turns the ASV system's decision into actuator commands. The none layer stands for a simulation that integrates control itself.",
            KIND_ROLE,
            (*layer_members, "ControlLayerId member", "a runtime bound by a loader in registry/catalog.py"),
            "Add a ControlLayerId member, a LayerSpec and a DockerControlLayer that adds the controller's container per vessel, and register both in registry/catalog.py (docker=).",
            "scenegems_tool/vessel_stack/control_layers",
        ),
        MetamodelNode(
            _meta_layer_id(Role.SIMULATION_LAYER),
            Role.SIMULATION_LAYER.value,
            "Simulation layer",
            "Moves the vessels and applies the environment. One simulation layer is shared by every vessel of an instance, and it owns the clock.",
            KIND_ROLE,
            (
                *layer_members,
                "SimulationLayerId member",
                "a runtime bound by a loader in registry/catalog.py",
            ),
            (
                "Add a SimulationLayerId member, a LayerSpec with its capabilities and a DockerSimulationLayer that adds the simulator's container for the scenario, "
                "register both in registry/catalog.py (docker=), and add its measurements to measured_capabilities.yaml."
            ),
            "scenegems_tool/vessel_stack/simulation_layers",
        ),
        MetamodelNode(
            META_PARTICIPANT,
            Role.ASV_SYSTEM.value,
            "Lockstep participant",
            (
                "How ASV system takes part in a run: the clock asks every participant for its command at each step. "
                "The runner holds a link to the software's container, which answers over the lockstep wire protocol."
            ),
            KIND_INTERFACE,
            tuple(f"LockstepParticipant.{member}" for member in _protocol_members(LockstepParticipant)),
            "Implement the protocol, serve it in the software's container and bind the class as the runtime of the spec.",
            "scenegems_tool/vessel_stack/contracts/clock.py",
        ),
        MetamodelNode(
            META_DOCKER_CONTROL,
            Role.CONTROL_LAYER.value,
            "Docker control layer",
            "How a control layer that runs in containers contributes its files and services to the compose stack of a job.",
            KIND_INTERFACE,
            tuple(f"DockerControlLayer.{member}" for member in _protocol_members(DockerControlLayer)),
            "Implement the protocol and bind the class to the spec in registry/catalog.py (docker=).",
            "scenegems_tool/vessel_stack/contracts/docker_stack.py",
        ),
        MetamodelNode(
            META_DOCKER_SIMULATION,
            Role.SIMULATION_LAYER.value,
            "Docker simulation layer",
            "How a simulator that runs in containers adds its world, vessels and service to the compose stack, one vessel at a time and then the instance as a whole.",
            KIND_INTERFACE,
            tuple(f"DockerSimulationLayer.{member}" for member in _protocol_members(DockerSimulationLayer)),
            "Implement the protocol and bind the class to the spec in registry/catalog.py (docker=).",
            "scenegems_tool/vessel_stack/contracts/docker_stack.py",
        ),
        MetamodelNode(
            META_CLOCK,
            Role.SIMULATION_LAYER.value,
            "Lockstep clock",
            "The simulation layer owns the clock: time advances only after every participant has acknowledged the step, so runs repeat and can go faster than real time.",
            KIND_COMPONENT,
            tuple(f"LockstepClock.{member}" for member in _protocol_members(LockstepClock)),
            None,
            "scenegems_tool/vessel_stack/contracts/clock.py",
        ),
    )
    edges = (
        MetamodelEdge(
            META_ASV_TO_CONTROL,
            _meta_layer_id(Role.ASV_SYSTEM),
            _meta_layer_id(Role.CONTROL_LAYER),
            "ASV system to control layer",
            "Carries the ASV system's commands to the control layer. The resolver finds one adapter per connection, or the ruled-out connection with its reason.",
            "adapter",
            (f"AdapterSpec({adapter_fields})", "source and target LayerRefs one role apart", "capabilities of the connection", "register_adapter(spec, runtime, default=...)"),
            "Define an AdapterSpec for the pair in the implementation's specs module and register it; a second adapter on the same pair needs default=True or False. Rule a pair out with an UnsupportedConnection and its reason.",
            "scenegems_tool/vessel_stack/contracts/adapter_spec.py",
        ),
        MetamodelEdge(
            META_CONTROL_TO_SIMULATION,
            _meta_layer_id(Role.CONTROL_LAYER),
            _meta_layer_id(Role.SIMULATION_LAYER),
            "Control layer to simulation layer",
            "Carries actuator commands to the simulation and the vessel's state back. Measurements of a pair sit on this adapter.",
            "adapter",
            (f"AdapterSpec({adapter_fields})", "measured pair capabilities in measured_capabilities.yaml", "register_adapter(spec, runtime, default=...)"),
            "As for the ASV adapter. Measure the pair and file the values under the adapter id.",
            "scenegems_tool/vessel_stack/contracts/adapter_spec.py",
        ),
    )
    return nodes, edges


def vessel_stack_document(registry: Optional[AdapterRegistry] = None, resolver: Optional[StackResolver] = None, unsupported: Optional[Iterable[UnsupportedConnection]] = None) -> ArchitectureDocument:
    from scenegems_tool.vessel_stack.registry.catalog import UNSUPPORTED_CONNECTIONS, default_registry

    registry = registry or default_registry()
    resolver = resolver or StackResolver(registry)
    unsupported = UNSUPPORTED_CONNECTIONS if unsupported is None else unsupported
    layer_order = {role: index for index, role in enumerate(STACK_ROLE_ORDER)}
    layers: List[LayerSpec] = sorted(registry.layers, key=lambda spec: (layer_order[spec.layer.role], spec.layer.impl))
    metamodel_nodes, metamodel_edges = _metamodel()
    registered = {spec.id for spec in layers}
    combinations = [_combination(chain) for chain in resolver.availability_matrix()]  # over the role enums, so a registry without a layer leaves its rows out
    return ArchitectureDocument(
        id=DOCUMENT_ID,
        title="Vessel stack",
        summary="Every vessel runs on a stack of three layers: ASV system, control layer and simulation layer. Adapters connect an implementation of one layer to an implementation of the next, and a stack exists when the adapters on its path do. One integration may cover several layers through built-in adapters, as ArduPilot does with SITL and a real vessel with its own autopilot.",
        lanes=tuple(Lane(role.value, *_LANE_TEXT[role]) for role in STACK_ROLE_ORDER),
        metamodel_nodes=metamodel_nodes,
        metamodel_edges=metamodel_edges,
        nodes=tuple(_layer_node(registry, spec) for spec in layers),
        edges=tuple(_adapter_edge(registry, spec) for spec in sorted(registry.adapters, key=lambda adapter: (layer_order[adapter.source.role], adapter.source.impl, adapter.target.impl, adapter.id))),
        unsupported=tuple(UnsupportedLink(str(item.source), str(item.target), item.reason) for item in unsupported),
        combinations=tuple(combination for combination in combinations if registered.issuperset(combination.path)),
        notes=(
            "The capabilities of a path are the weakest link over its three layers and two adapters. Values marked measured come from vessel_stack/registry/measured_capabilities.yaml.",
            "A stack runs in campaigns only when a runner of the simulation job runs it on a worker node (Cluster job); the other available stacks run on the workbench as live sessions. Workbench only stacks (Mission Planner, real vessels) never run in a campaign: an operator or a physical vessel is in the loop.",
            "Ports that adapters connect: " + "; ".join(_port_members()) + ".",
        ),
        role=ROLE_STEP,
        step="Simulation",
        takes="trajectories",
        gives="a simulated run: its state log",
        job_types=("simulation",),
    ).validate()
