"""JSON views of what a campaign may run: the class catalog and the stacks, monitors and trajectory generators.

stacks_view describes every option so a form can be generated from it; a stack says whether a live monitor
can stop its run early (supports_early_stop), and stack_section holds the fields of a run's stack section
that pick the option (simulation_layer and mode, and control_layer for the custom controller), so a
form writes them as they are and finds an option again from a section. A parameter is
{"key", "type", "default", "required", "description"} plus "unit", "minimum", "exclusive_minimum",
"maximum" or "choices" where they apply; type is number, integer, boolean, number_pair, number_triple,
number_map or string. A default of null means the parameter is left out and the system derives it
(the description says how). The imports are inside the functions: the config model pulls in numpy and
the job type modules, which the control node keeps out of its startup.
"""

from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

CAMPAIGN_STACKS_NOTE = (
    "Campaign configs offer every campaign stack of the resolver, each with replay, or with USV Navigation or MOOS-IvP on the own ship: the kinematic layer "
    "(the simulation job's kinematic runner), ArduPilot on SITL or Gazebo (its ardupilot runner) and the custom controller on Gazebo "
    "(its gazebo_custom runner). Workbench only stacks (Mission Planner, real vessels) never run in a campaign."
)


def class_view(scenario_class: Any) -> Dict[str, Any]:
    return {
        "fec_id": scenario_class.class_id,
        "folder": scenario_class.folder,
        "vessel_count": scenario_class.vessel_count,
        "obstacle_count": scenario_class.obstacle_count,
        "content_hash": scenario_class.content_hash,
    }


def domain_presets_view() -> Dict[str, List[Dict[str, Any]]]:
    """The domain presets per key (colregs_constants, vessel_types, obstacle_types), each {"name", "default", "content"}."""
    from scenegems_tool.assurance.campaign.domain_presets import domain_presets

    return {key: [{"name": preset.name, "default": preset.default, "content": preset.content} for preset in presets] for key, presets in domain_presets().items()}


def parameter(
    key: str,
    kind: str,
    description: str,
    default: Any = None,
    *,
    required: bool = False,
    unit: Optional[str] = None,
    minimum: Optional[float] = None,
    exclusive_minimum: Optional[float] = None,
    maximum: Optional[float] = None,
    choices: Optional[List[str]] = None,
) -> Dict[str, Any]:
    view: Dict[str, Any] = {"key": key, "type": kind, "default": default, "required": required, "description": description}
    for name, value in (("unit", unit), ("minimum", minimum), ("exclusive_minimum", exclusive_minimum), ("maximum", maximum), ("choices", choices)):
        if value is not None:
            view[name] = value
    return view


def _triple(stack: Any) -> Dict[str, str]:
    return {"asv_system": stack.asv_system.value, "control_layer": stack.control_layer.value, "simulation_layer": stack.simulation_layer.value}


def _key(stack: Any) -> Tuple[str, str, str]:
    return stack.asv_system.value, stack.control_layer.value, stack.simulation_layer.value


def _usv_navigation_parameters() -> List[Dict[str, Any]]:
    from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_parameters import DEFAULT_PRESCRIBED_TIME_S

    return [
        parameter("goal", "number_pair", "waypoint [x, y] in the scene's local frame", required=True, unit="m"),
        parameter("speed", "number", "the speed the runtime holds and commands", required=True, exclusive_minimum=0.0, unit="m/s"),
        parameter("safety_radius", "number", "the radius the runtime steers around every obstacle; a target's motion can still bring it closer", required=True, exclusive_minimum=0.0, unit="m"),
        parameter("control_horizon", "number", "horizon of the prescribed-time heading law, not a look-ahead", required=True, exclusive_minimum=0.0, unit="s"),
        parameter(
            "prescribed_time", "number", "prescribed time tp; it sizes the arrival radius, and the safety distance without a horizon", DEFAULT_PRESCRIBED_TIME_S, exclusive_minimum=0.0, unit="s"
        ),
        parameter("horizon", "number", "how far the navigator looks; every target at any range and the upstream safety distance when absent", exclusive_minimum=0.0, unit="m"),
        parameter("runtime_options", "number_map", "further runtime arguments by name (a, eta, K, K_off, v1_buffer, ...); the upstream defaults when absent", {}),
    ]


def _derived_usv_navigation() -> str:
    from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_parameters import (
        DCPA_BETA1_RADII,
        DCPA_BETA2_RADII,
        DEFAULT_CONTROL_HORIZON_STEPS,
        DEFAULT_PRESCRIBED_TIME_S,
    )

    return (
        "Left out, every scene gets its own values: goal is the end of the generated trajectory, speed the own ship's reference speed at the start "
        f"(capped at its maximum speed), safety_radius the largest safety radius in the scene, control_horizon the longest of {DEFAULT_CONTROL_HORIZON_STEPS} steps, "
        f"{DEFAULT_PRESCRIBED_TIME_S:g} s and one full turn at the maximum yaw rate, horizon the largest visibility distance between the own ship and another actor, "
        f"and the risk index's DCPA bounds at least {DCPA_BETA1_RADII:g} and {DCPA_BETA2_RADII:g} safety radii. "
        "Given, goal, speed, safety_radius and control_horizon are required and apply to every case."
    )


def _moos_ivp_parameters() -> List[Dict[str, Any]]:
    """The fields of MoosIvpPayload a form can take: every one optional. behaviour_options (further lines of the avoidance behaviour, by name) is a config field only."""
    from scenegems_tool.vessel_stack.asv_system.moos_ivp.moos_ivp_parameters import AVOIDANCE_BEHAVIOURS

    return [
        parameter(
            "avoidance",
            "string",
            "the collision avoidance behaviour of a contact: colregs (BHV_AvdColregsV22, the give-way and stand-on modes of rules 13 to 17) or cpa (BHV_AvoidCollision, no rule)",
            choices=list(AVOIDANCE_BEHAVIOURS),
        ),
        parameter("goal", "number_pair", "waypoint [x, y] in the scene's local frame", unit="m"),
        parameter("speed", "number", "transit speed of the waypoint behaviour", exclusive_minimum=0.0, unit="m/s"),
        parameter("max_speed", "number", "upper end of the speed the helm may decide", exclusive_minimum=0.0, unit="m/s"),
        parameter("min_util_cpa_dist", "number", "a closest point of approach at this distance or less has no utility: the helm avoids it", minimum=0.0, unit="m"),
        parameter("max_util_cpa_dist", "number", "a closest point of approach at this distance or more has full utility", minimum=0.0, unit="m"),
        parameter("pwt_outer_dist", "number", "the avoidance behaviour has no say beyond this range to its contact", exclusive_minimum=0.0, unit="m"),
        parameter("pwt_inner_dist", "number", "the avoidance behaviour has its full priority weight within this range", exclusive_minimum=0.0, unit="m"),
        parameter("completed_dist", "number", "a contact gets its avoidance behaviour within this range, and the behaviour ends beyond 1.1 times it", exclusive_minimum=0.0, unit="m"),
        parameter("capture_radius", "number", "the goal is reached within this distance", exclusive_minimum=0.0, unit="m"),
    ]


def _derived_moos_ivp() -> str:
    from scenegems_tool.vessel_stack.asv_system.moos_ivp.moos_ivp_parameters import CAPTURE_RADIUS_LENGTHS, COMPLETED_DISTANCE_FACTOR, MAX_UTILITY_CPA_RADII

    return (
        "Every value left out is each scene's own: avoidance is colregs, goal the end of the generated trajectory, speed the own ship's reference speed at the start "
        "(capped at its maximum speed, which is max_speed), min_util_cpa_dist the largest safety radius in the scene, "
        f"max_util_cpa_dist {MAX_UTILITY_CPA_RADII:g} times that, pwt_outer_dist the largest visibility distance between the own ship and another actor "
        f"(at least twice max_util_cpa_dist), pwt_inner_dist half of pwt_outer_dist, completed_dist {COMPLETED_DISTANCE_FACTOR:g} times pwt_outer_dist "
        f"and capture_radius {CAPTURE_RADIUS_LENGTHS:g} vessel lengths. A value that is given replaces the scene's and applies to every case."
    )


def _run_stack_parameters() -> List[Dict[str, Any]]:
    return [
        parameter("dt", "number", "time step of the run; the trajectories' time step when absent", unit="s", exclusive_minimum=0.0),
        parameter("steps", "integer", "number of steps; the trajectories' timespan when absent", minimum=1),
    ]


def _environment_support(resolver: Any, stacks: Dict[str, Any]) -> Dict[str, Any]:
    from scenegems_tool.vessel_stack.contracts.capabilities import weakest_link

    capabilities = weakest_link(spec.capabilities for stack in stacks.values() for spec in resolver.resolve(stack).specs)
    return {"wind": capabilities.wind.value, "waves": capabilities.waves.value, "interactive_only": capabilities.interactive_only}


def _geofence_parameters() -> List[Dict[str, Any]]:
    from scenegems_tool.assurance.campaign.campaign_config import GeofenceSettings

    fields = GeofenceSettings.model_fields
    return [
        parameter("latitude", "number", "latitude of the reference area's center", fields["latitude"].default, unit="deg", minimum=-90.0, maximum=90.0),
        parameter("longitude", "number", "longitude of the reference area's center", fields["longitude"].default, unit="deg", minimum=-180.0, maximum=180.0),
        parameter("radius_meters", "number", "radius of the reference area", fields["radius_meters"].default, unit="m", exclusive_minimum=0.0),
    ]


def _ardupilot_parameters() -> List[Dict[str, Any]]:
    from scenegems_tool.assurance.campaign.campaign_config import ArdupilotStackConfig

    return [
        parameter(
            "speedup", "integer", "SITL's requested pace as a multiple of real time; the resolver refuses a pace the stack cannot hold", ArdupilotStackConfig.model_fields["speedup"].default, minimum=1
        ),
        *_lockstep_parameters("the trajectories' time step when absent, 1 s when that is 3 s or longer (Rover's GUIDED target timeout)"),
    ]


def _lockstep_parameters(absent: str = "the trajectories' time step when absent") -> List[Dict[str, Any]]:
    return [
        parameter("dt", "number", f"time step of the run in whole seconds; {absent}", unit="s", exclusive_minimum=0.0),
        parameter("steps", "integer", "number of steps; the trajectories' timespan when absent", minimum=1),
    ]


def _ardupilot_environment(resolver: Any, vessels: Dict[str, Any]) -> Dict[str, Any]:
    """What a run on the stack can apply: the resolver's support, cut to what the ardupilot runner does (it runs calm water, so a configured wind or wave is refused)."""
    support = _environment_support(resolver, vessels)
    return {"wind": "unsupported", "waves": "unsupported", "interactive_only": support["interactive_only"]}


def offered_stacks(resolver: Any) -> List[Dict[str, Any]]:
    """The stack options a campaign config accepts (campaign_config.StackConfig), each as the resolver judges it for an unattended run."""
    return _kinematic_stacks(resolver) + _ardupilot_stacks(resolver) + _custom_stacks(resolver)


def _usv_navigation_group() -> Dict[str, Any]:
    return {"key": "usv_navigation", "label": "USV Navigation parameters", "optional": True, "derived_when_absent": _derived_usv_navigation(), "parameters": _usv_navigation_parameters()}


def _moos_ivp_group() -> Dict[str, Any]:
    return {"key": "moos_ivp", "label": "MOOS-IvP parameters", "optional": True, "derived_when_absent": _derived_moos_ivp(), "parameters": _moos_ivp_parameters()}


def _mode_groups(mode: Any) -> List[Dict[str, Any]]:
    """The parameter group of the ASV system a mode puts on the own ship; none for replay."""
    from scenegems_tool.cluster.worker_node.jobs.simulation_runners.kinematic_runner import KinematicMode

    return {KinematicMode.USV_NAVIGATION: [_usv_navigation_group()], KinematicMode.MOOS_IVP: [_moos_ivp_group()]}.get(mode, [])


def _offered(resolver: Any, option_id: str, config: Any, label: str, description: str, **fields: Any) -> Dict[str, Any]:
    """An option of the config's stack section: its id, its vessels' triples and whether the resolver accepts it; fields add the parameters, groups, environment and early stop."""
    from scenegems_tool.assurance.campaign.campaign_config import RunConfig
    from scenegems_tool.assurance.campaign.config_validation import resolve_run, vessel_stacks

    resolved, reasons = resolve_run(RunConfig(stack=config), 0, resolver)
    vessels = vessel_stacks(config)
    section = {"simulation_layer": config.simulation_layer, **({"control_layer": config.control_layer} if "control_layer" in type(config).model_fields else {}), "mode": config.mode.value}
    return {
        "id": option_id,
        "label": label,
        "description": description,
        "simulation_layer": config.simulation_layer,
        "control_layer": vessels["own_ship"].control_layer.value,
        "mode": config.mode.value,
        "stack_section": section,
        "available": resolved is not None,
        "reasons": reasons,
        "repeatability_tier": None if resolved is None else resolved.repeatability_tier,
        "vessels": {agent_id: _triple(stack) for agent_id, stack in vessels.items()},
        **fields,
    }


def _ardupilot_stacks(resolver: Any) -> List[Dict[str, Any]]:
    from scenegems_tool.assurance.campaign.campaign_config import ARDUPILOT_LAYERS, ArdupilotStackConfig
    from scenegems_tool.assurance.campaign.config_validation import vessel_stacks
    from scenegems_tool.cluster.worker_node.jobs.simulation_runners.kinematic_runner import KinematicMode

    layers = {
        "ardupilot_sim": ("ArduPilot SITL", "its own ArduPilot SITL (SITL's physics)"),
        "gazebo": ("SITL with Gazebo", "its own ArduPilot SITL against a Gazebo world"),
    }
    modes = {
        KinematicMode.REPLAY: ("Replay on {layer}", "Every vessel replays its generated trajectory through {through}, stepped in lockstep over MAVLink."),
        KinematicMode.USV_NAVIGATION: (
            "USV Navigation on {layer}",
            "The own ship runs USV Navigation closed loop, its heading and speed sent to {through} as GUIDED targets over MAVLink in lockstep; the other vessels replay.",
        ),
        KinematicMode.MOOS_IVP: (
            "MOOS-IvP on {layer}",
            "The own ship runs MOOS-IvP's helm closed loop, its heading and speed sent to {through} as GUIDED targets over MAVLink in lockstep; the other vessels replay.",
        ),
    }
    stacks = []
    for mode in KinematicMode:
        for layer in ARDUPILOT_LAYERS:
            config = ArdupilotStackConfig(simulation_layer=layer, mode=mode)
            layer_label, through = layers[layer]
            label, description = modes[mode]
            groups = [*_mode_groups(mode), {"key": "geofence", "label": "Reference area", "optional": True, "derived_when_absent": _derived_geofence(), "parameters": _geofence_parameters()}]
            stacks.append(
                _offered(
                    resolver,
                    f"{layer}.{mode.value}",
                    config,
                    label.format(layer=layer_label),
                    description.format(through=through) + " Repeats differ within a measured bound. The run has no wind or waves, and no early stop.",
                    supports_early_stop=False,
                    environment=_ardupilot_environment(resolver, vessel_stacks(config)),
                    parameters=_ardupilot_parameters(),
                    groups=groups,
                )
            )
    return stacks


def _custom_stacks(resolver: Any) -> List[Dict[str, Any]]:
    """The custom controller on Gazebo: the gazebo_custom runner steps the world, which applies the run's wind and waves as far as the resolver supports them."""
    from scenegems_tool.assurance.campaign.campaign_config import CUSTOM_CONTROL_LAYER, CustomStackConfig
    from scenegems_tool.assurance.campaign.config_validation import vessel_stacks
    from scenegems_tool.cluster.worker_node.jobs.simulation_runners.kinematic_runner import KinematicMode

    described = {
        KinematicMode.REPLAY: ("Replay on the custom controller with Gazebo", "Every vessel follows its generated trajectory with the line-of-sight follower of the custom controller"),
        KinematicMode.USV_NAVIGATION: ("USV Navigation on the custom controller with Gazebo", "The own ship runs USV Navigation closed loop through the custom controller; the other vessels replay"),
        KinematicMode.MOOS_IVP: ("MOOS-IvP on the custom controller with Gazebo", "The own ship runs MOOS-IvP's helm closed loop through the custom controller; the other vessels replay"),
    }
    stacks = []
    for mode in KinematicMode:
        config = CustomStackConfig(simulation_layer="gazebo", control_layer=CUSTOM_CONTROL_LAYER, mode=mode)
        label, description = described[mode]
        stacks.append(
            _offered(
                resolver,
                f"gazebo_custom.{mode.value}",
                config,
                label,
                description + ", in a Gazebo world the runner steps itself (no SITL). Repeats differ within a measured bound; the run applies its wind and waves, and has no early stop.",
                supports_early_stop=False,
                environment=_environment_support(resolver, vessel_stacks(config)),
                parameters=_lockstep_parameters(),
                groups=_mode_groups(mode),
            )
        )
    return stacks


def _derived_geofence() -> str:
    from scenegems_tool.assurance.campaign.campaign_config import GeofenceSettings

    fields = GeofenceSettings.model_fields
    return (
        "Left out, the workbench's reference area is used: "
        f"latitude {fields['latitude'].default}, longitude {fields['longitude'].default}, radius {fields['radius_meters'].default:g} m. "
        "It maps the scenes' local frame to SITL's home positions."
    )


def _kinematic_stacks(resolver: Any) -> List[Dict[str, Any]]:
    from scenegems_tool.assurance.campaign.campaign_config import KinematicStackConfig
    from scenegems_tool.assurance.campaign.config_validation import vessel_stacks
    from scenegems_tool.cluster.worker_node.jobs.simulation_runners.kinematic_runner import KinematicMode

    labels = {
        KinematicMode.REPLAY: ("Replay on the kinematic layer", "Every vessel replays its generated trajectory; the scene is judged as it was generated."),
        KinematicMode.USV_NAVIGATION: ("USV Navigation on the kinematic layer", "The own ship runs USV Navigation closed loop; the other vessels replay."),
        KinematicMode.MOOS_IVP: ("MOOS-IvP on the kinematic layer", "The own ship runs MOOS-IvP's helm closed loop, one helm pass per step; the other vessels replay."),
    }
    stacks = []
    for mode in KinematicMode:
        config = KinematicStackConfig(mode=mode)
        label, description = labels[mode]
        stacks.append(
            _offered(
                resolver,
                f"kinematic.{mode.value}",
                config,
                label,
                description,
                supports_early_stop=True,
                environment=_environment_support(resolver, vessel_stacks(config)),
                parameters=_run_stack_parameters(),
                groups=_mode_groups(mode),
            )
        )
    return stacks


def unavailable_stacks(resolver: Any, offered: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every other triple of the resolver's matrix with the reasons a campaign cannot use it."""
    taken = {(vessel["asv_system"], vessel["control_layer"], vessel["simulation_layer"]) for option in offered for vessel in option["vessels"].values()}
    others = []
    for chain in resolver.availability_matrix():
        if _key(chain.stack) in taken:
            continue
        capabilities = chain.capabilities
        interactive = bool(capabilities and capabilities.interactive_only)
        if chain.available and interactive:
            reasons = ["workbench only: an operator or a physical vessel is in the loop, so a campaign never runs it"]
        elif chain.available:
            reasons = ["the campaign config does not offer this stack yet: no runner of the simulation job runs it"]
        else:
            reasons = list(chain.reasons)
        others.append(
            {
                **_triple(chain.stack),
                "status": chain.status,
                "design_status": chain.design_status,
                "available_in_resolver": chain.available,
                "tier": None if capabilities is None or not chain.available else capabilities.repeatability_tier.value,
                "reasons": reasons,
            }
        )
    return others


def monitors_view() -> List[Dict[str, Any]]:
    from scenegems_tool.persistence.schema import MonitorImplementation

    described = {
        MonitorImplementation.POST_HOC: ("Post hoc", "A monitoring job judges the recorded run after the simulation; the monitor result summary is passed or failed.", ["monitoring.post_hoc"], False),
        MonitorImplementation.LIVE: (
            "Live",
            "The COLREGS monitor runs inside the simulation step by step; on the kinematic layer it can stop the run early once every rule is decided.",
            ["simulation"],
            True,
        ),
        MonitorImplementation.EMPTY: ("None", "Nothing is judged; every monitor result summary is unmonitored.", [], False),
    }
    return [
        {"id": monitor.value, "label": label, "description": description, "job_types": job_types, "supports_early_stop": early_stop}
        for monitor, (label, description, job_types, early_stop) in described.items()
    ]


def _search_parameters() -> List[Dict[str, Any]]:
    from concrete_level.trajectory_generation.monitor_guided_planner import MonitorGuidedPlanner
    from concrete_level.trajectory_generation.trajectory_generator import TIME_STEP
    from scenegems_tool.assurance.campaign.campaign_config import SEARCH_PARAM_KEYS

    search = MonitorGuidedPlanner
    described = [
        parameter("timeStep", "integer", "time step of the generated trajectories", TIME_STEP, unit="s", minimum=1),
        parameter("timeout", "number", "wall-clock limit of the search; the best path so far is returned when it ends. No limit when absent", unit="s", exclusive_minimum=0.0),
        parameter("maxIterations", "integer", "seed steps the planner may take; the plan ends there. No limit when absent", minimum=1),
        parameter("directionThreshold", "number", "distance at which a repaired stretch counts as back on the seed path", search.DIRECTION_THRESHOLD, unit="m", exclusive_minimum=0.0),
        parameter("bestRandomNodesK", "integer", "cheapest leaves expanded per repair round", search.BEST_RANDOM_NODES_K, minimum=1),
        parameter("previewInterval", "integer", "seed steps between two previews of the plan", search.ANIM_UPDATE_INTERVAL, minimum=1),
        parameter("includeMonitorResults", "boolean", "whether previews and results carry the monitor output of the search", True),
    ]
    if {entry["key"] for entry in described} != set(SEARCH_PARAM_KEYS):
        raise RuntimeError("the catalog of search parameters is out of step with the campaign config")
    return described


def trajectory_generators_view() -> List[Dict[str, Any]]:
    from scenegems_tool.assurance.campaign.campaign_config import TrajectoriesConfig

    timeout_s = TrajectoriesConfig.model_fields["timeout_s"].default
    common = [parameter("timeout_s", "number", "how long a trajectory generation job may take", timeout_s, unit="s", exclusive_minimum=0.0)]
    return [
        {
            "id": "monitor_driven_rrt",
            "label": "Monitor-guided planner",
            "description": "Follows a maneuvering corridor for every give-way vessel and repairs each step the COLREGS monitor fails with a short tree search over sampled heading changes. Parameters go under trajectories.params by these keys.",
            "params_field": "params",
            "parameters": _search_parameters(),
            "common_parameters": common,
        },
        {
            "id": "straight",
            "label": "Straight",
            "description": "Every vessel keeps its course and speed for the timespan.",
            "params_field": None,
            "parameters": [parameter("timespan_s", "number", "how far every vessel goes straight on", required=True, unit="s", exclusive_minimum=0.0)],
            "common_parameters": common,
        },
    ]


def run_parameters_view() -> List[Dict[str, Any]]:
    """The fields of a run besides its stack and monitor (campaign_config.RunConfig)."""
    from scenegems_tool.assurance.campaign.campaign_config import MAX_SEED, RunConfig

    return [
        parameter("name", "string", "label of the run in the campaign and its results"),
        parameter("seed", "integer", "one seed for the run in every case; the case seed when absent", minimum=0, maximum=MAX_SEED),
        parameter("repeats", "integer", "runs with the same seed, for the calibration of a bounded stack", RunConfig.model_fields["repeats"].default, minimum=1),
        parameter("early_stop", "boolean", "stop the run once every rule is decided; the live monitor on a kinematic stack only", RunConfig.model_fields["early_stop"].default),
        parameter("environment.wind_vector", "number_triple", "wind [east, north, up]", [0.0, 0.0, 0.0], unit="m/s"),
        parameter("environment.waves", "object", "waves: amplitude, period, steepness and direction [east, north] (its norm is the wave speed); none when absent"),
    ]


@lru_cache(maxsize=1)
def _stacks_view() -> Dict[str, Any]:
    from scenegems_tool.vessel_stack.registry.catalog import default_resolver

    resolver = default_resolver()
    offered = offered_stacks(resolver)
    matrix = resolver.availability_matrix()
    return {
        "stacks": offered,
        "unavailable_stacks": unavailable_stacks(resolver, offered),
        "monitors": monitors_view(),
        "trajectory_generators": trajectory_generators_view(),
        "run_parameters": run_parameters_view(),
        "note": CAMPAIGN_STACKS_NOTE,
        "resolver": {"combinations": len(matrix), "available": sum(1 for chain in matrix if chain.available)},
    }


def stacks_view() -> Dict[str, Any]:
    return _stacks_view()
