/**
 * Sample answers of the catalog and validate routes, shaped as `catalog_views.py` and
 * `campaign_views.validated_campaign_view` build them (the stack catalog as P5.1 reports it).
 */

function parameter(key: string, type: string, description: string, extra: Record<string, unknown> = {}): Record<string, unknown> {
  return { key, type, default: null, required: false, description, ...extra };
}

export const sampleCatalogClasses = [
  { fec_id: "2vessel_0obstacle_scenarios/fec1", folder: "2vessel_0obstacle_scenarios", vessel_count: 2, obstacle_count: 0, content_hash: "aa01" },
  { fec_id: "2vessel_0obstacle_scenarios/fec2", folder: "2vessel_0obstacle_scenarios", vessel_count: 2, obstacle_count: 0, content_hash: "aa02" },
  { fec_id: "2vessel_0obstacle_scenarios/fec10", folder: "2vessel_0obstacle_scenarios", vessel_count: 2, obstacle_count: 0, content_hash: "aa0a" },
  { fec_id: "2vessel_1obstacle_scenarios/fec1", folder: "2vessel_1obstacle_scenarios", vessel_count: 2, obstacle_count: 1, content_hash: "bb01" },
  { fec_id: "3vessel_0obstacle_scenarios/fec1", folder: "3vessel_0obstacle_scenarios", vessel_count: 3, obstacle_count: 0, content_hash: "cc01" },
  { fec_id: "3vessel_0obstacle_scenarios/fec5", folder: "3vessel_0obstacle_scenarios", vessel_count: 3, obstacle_count: 0, content_hash: "cc05" },
  { fec_id: "4vessel_0obstacle_scenarios/fec1", folder: "4vessel_0obstacle_scenarios", vessel_count: 4, obstacle_count: 0, content_hash: "dd01" },
];

const usvNavigationGroup = {
  key: "usv_navigation",
  label: "USV Navigation parameters",
  optional: true,
  derived_when_absent: "Left out, every scene gets its own values.",
  parameters: [
    parameter("goal", "number_pair", "waypoint [x, y] in the scene's local frame", { required: true, unit: "m" }),
    parameter("speed", "number", "the speed the runtime holds and commands", { required: true, exclusive_minimum: 0, unit: "m/s" }),
    parameter("safety_radius", "number", "the radius the runtime steers around every obstacle", { required: true, exclusive_minimum: 0, unit: "m" }),
    parameter("control_horizon", "number", "horizon of the prescribed-time heading law, not a look-ahead", { required: true, exclusive_minimum: 0, unit: "s" }),
    parameter("prescribed_time", "number", "prescribed time tp", { default: 20, exclusive_minimum: 0, unit: "s" }),
    parameter("horizon", "number", "how far the navigator looks", { exclusive_minimum: 0, unit: "m" }),
    parameter("runtime_options", "number_map", "further runtime arguments by name", { default: {} }),
  ],
};

const runStackParameters = [
  parameter("dt", "number", "time step of the run; the trajectories' time step when absent", { unit: "s", exclusive_minimum: 0 }),
  parameter("steps", "integer", "number of steps; the trajectories' timespan when absent", { minimum: 1 }),
];

const triple = (software: string) => ({ asv_software: software, control_layer: "none", simulation_layer: "kinematic" });
const ardupilotTriple = { asv_software: "replay", control_layer: "ardupilot", simulation_layer: "ardupilot_sim" };
const customTriple = { asv_software: "replay", control_layer: "custom", simulation_layer: "gazebo" };
const lockstepParameters = [
  parameter("dt", "number", "time step of the run in whole seconds", { unit: "s", exclusive_minimum: 0 }),
  parameter("steps", "integer", "number of steps; the trajectories' timespan when absent", { minimum: 1 }),
];

export const sampleCatalogStacks = {
  stacks: [
    {
      id: "kinematic.replay",
      label: "Replay on the kinematic layer",
      description: "Every vessel replays its generated trajectory; the scene is judged as it was generated.",
      simulation_layer: "kinematic",
      control_layer: "none",
      mode: "replay",
      stack_section: { simulation_layer: "kinematic", mode: "replay" },
      available: true,
      reasons: [],
      repeatability_tier: "exact",
      vessels: { own_ship: triple("replay"), target_ship: triple("replay") },
      environment: { wind: "unsupported", waves: "unsupported", interactive_only: false },
      parameters: runStackParameters,
      groups: [],
    },
    {
      id: "kinematic.usv_navigation",
      label: "USV Navigation on the kinematic layer",
      description: "The own ship runs USV Navigation closed loop; the other vessels replay.",
      simulation_layer: "kinematic",
      control_layer: "none",
      mode: "usv_navigation",
      stack_section: { simulation_layer: "kinematic", mode: "usv_navigation" },
      available: true,
      reasons: [],
      repeatability_tier: "exact",
      vessels: { own_ship: triple("usv_navigation"), target_ship: triple("replay") },
      environment: { wind: "unsupported", waves: "unsupported", interactive_only: false },
      parameters: runStackParameters,
      groups: [usvNavigationGroup],
    },
    {
      id: "ardupilot_sim.replay",
      label: "Replay on ArduPilot SITL",
      description: "Every vessel replays its generated trajectory through its own ArduPilot SITL, stepped in lockstep over MAVLink.",
      simulation_layer: "ardupilot_sim",
      control_layer: "ardupilot",
      mode: "replay",
      stack_section: { simulation_layer: "ardupilot_sim", mode: "replay" },
      available: true,
      reasons: [],
      repeatability_tier: "bounded",
      supports_early_stop: false,
      vessels: { own_ship: ardupilotTriple, target_ship: ardupilotTriple },
      environment: { wind: "unsupported", waves: "unsupported", interactive_only: false },
      parameters: [
        parameter("speedup", "integer", "SITL's requested pace as a multiple of real time", { default: 1, minimum: 1 }),
        parameter("dt", "number", "time step of the run in whole seconds", { unit: "s", exclusive_minimum: 0 }),
        parameter("steps", "integer", "number of steps; the trajectories' timespan when absent", { minimum: 1 }),
      ],
      groups: [
        {
          key: "geofence",
          label: "Reference area",
          optional: true,
          derived_when_absent: "Left out, the workbench's reference area is used.",
          parameters: [
            parameter("latitude", "number", "latitude of the reference area's center", { default: 57.76080082972655, unit: "deg", minimum: -90, maximum: 90 }),
            parameter("longitude", "number", "longitude of the reference area's center", { default: 16.680965995056, unit: "deg", minimum: -180, maximum: 180 }),
            parameter("radius_meters", "number", "radius of the reference area", { default: 20, unit: "m", exclusive_minimum: 0 }),
          ],
        },
      ],
    },
    {
      id: "ardupilot_sim.usv_navigation",
      label: "USV Navigation on ArduPilot SITL",
      description: "The own ship runs USV Navigation closed loop through its own ArduPilot SITL; the other vessels replay.",
      simulation_layer: "ardupilot_sim",
      control_layer: "ardupilot",
      mode: "usv_navigation",
      stack_section: { simulation_layer: "ardupilot_sim", mode: "usv_navigation" },
      available: true,
      reasons: [],
      repeatability_tier: "bounded",
      supports_early_stop: false,
      vessels: { own_ship: { ...ardupilotTriple, asv_software: "usv_navigation" }, target_ship: ardupilotTriple },
      environment: { wind: "unsupported", waves: "unsupported", interactive_only: false },
      parameters: [parameter("speedup", "integer", "SITL's requested pace as a multiple of real time", { default: 1, minimum: 1 }), ...lockstepParameters],
      groups: [usvNavigationGroup],
    },
    {
      id: "gazebo_custom.replay",
      label: "Replay on the custom controller with Gazebo",
      description: "Every vessel follows its generated trajectory with the custom controller, in a Gazebo world the runner steps itself.",
      simulation_layer: "gazebo",
      control_layer: "custom",
      mode: "replay",
      stack_section: { simulation_layer: "gazebo", control_layer: "custom", mode: "replay" },
      available: true,
      reasons: [],
      repeatability_tier: "bounded",
      supports_early_stop: false,
      vessels: { own_ship: customTriple, target_ship: customTriple },
      environment: { wind: "supported", waves: "supported", interactive_only: false },
      parameters: lockstepParameters,
      groups: [],
    },
    {
      id: "gazebo_custom.usv_navigation",
      label: "USV Navigation on the custom controller with Gazebo",
      description: "The own ship runs USV Navigation closed loop through the custom controller; the other vessels replay.",
      simulation_layer: "gazebo",
      control_layer: "custom",
      mode: "usv_navigation",
      stack_section: { simulation_layer: "gazebo", control_layer: "custom", mode: "usv_navigation" },
      available: true,
      reasons: [],
      repeatability_tier: "bounded",
      supports_early_stop: false,
      vessels: { own_ship: { ...customTriple, asv_software: "usv_navigation" }, target_ship: customTriple },
      environment: { wind: "supported", waves: "supported", interactive_only: false },
      parameters: lockstepParameters,
      groups: [usvNavigationGroup],
    },
  ],
  unavailable_stacks: [
    {
      asv_software: "ardupilot",
      control_layer: "none",
      simulation_layer: "gazebo",
      status: "planned",
      design_status: "design",
      available_in_resolver: false,
      tier: null,
      reasons: ["the Gazebo adapter is not built yet"],
    },
    {
      asv_software: "replay",
      control_layer: "none",
      simulation_layer: "ardupilot",
      status: "available",
      design_status: "design",
      available_in_resolver: true,
      tier: "bounded",
      reasons: ["the campaign config does not offer this stack yet: its runs use the kinematic layer or replay on ArduPilot SITL or Gazebo"],
    },
  ],
  monitors: [
    { id: "post_hoc", label: "Post hoc", description: "A monitoring job judges the recorded run after the simulation.", job_types: ["monitoring.post_hoc"], supports_early_stop: false },
    { id: "live", label: "Live", description: "The COLREGS monitor runs inside the simulation step by step.", job_types: ["simulation"], supports_early_stop: true },
    { id: "empty", label: "None", description: "Nothing is judged; every monitor result summary is unmonitored.", job_types: [], supports_early_stop: false },
  ],
  trajectory_generators: [
    {
      id: "monitor_driven_rrt",
      label: "Monitor-guided planner",
      description: "Follows a maneuvering corridor for every give-way vessel and repairs each step the COLREGS monitor fails.",
      params_field: "params",
      parameters: [
        parameter("timeStep", "integer", "time step of the generated trajectories", { default: 1, unit: "s", minimum: 1 }),
        parameter("timeout", "number", "wall-clock limit of the search", { unit: "s", exclusive_minimum: 0 }),
        parameter("maxIterations", "integer", "seed steps the planner may take", { minimum: 1 }),
        parameter("bestRandomNodesK", "integer", "cheapest leaves expanded per repair round", { default: 20, minimum: 1 }),
        parameter("includeMonitorResults", "boolean", "whether previews and results carry the monitor output", { default: true }),
      ],
      common_parameters: [parameter("timeout_s", "number", "how long a trajectory generation job may take", { default: 1800, unit: "s", exclusive_minimum: 0 })],
    },
    {
      id: "straight",
      label: "Straight",
      description: "Every vessel keeps its course and speed for the timespan.",
      params_field: null,
      parameters: [parameter("timespan_s", "number", "how far every vessel goes straight on", { required: true, unit: "s", exclusive_minimum: 0 })],
      common_parameters: [parameter("timeout_s", "number", "how long a trajectory generation job may take", { default: 1800, unit: "s", exclusive_minimum: 0 })],
    },
  ],
  run_parameters: [
    parameter("name", "string", "label of the run"),
    parameter("seed", "integer", "one seed for the run in every case", { minimum: 0, maximum: 2147483647 }),
    parameter("repeats", "integer", "runs with the same seed", { default: 1, minimum: 1 }),
    parameter("early_stop", "boolean", "stop the run once every rule is decided", { default: false }),
  ],
  note: "Campaign configs offer the kinematic layer today.",
  resolver: { combinations: 12, available: 5 },
};

export const sampleValidationResult = {
  valid: true,
  name: "head-on sweep",
  config_hash: "9f2c1d",
  fecs: [
    { fec_id: "2vessel_0obstacle_scenarios/fec1", content_hash: "aa01", vessel_count: 2, obstacle_count: 0, quota: 15, failure_budget: 15 },
    { fec_id: "2vessel_0obstacle_scenarios/fec2", content_hash: "aa02", vessel_count: 2, obstacle_count: 0, quota: 15, failure_budget: 15 },
  ],
  cases_planned: 30,
  runs: [{ run_index: 0, name: "usv_navigation", repeatability_tier: "exact", warnings: [] }],
};
