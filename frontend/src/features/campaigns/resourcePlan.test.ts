import { describe, expect, it } from "vitest";
import { COMPONENTS } from "../../domain/cluster/components";
import { nodeViewSchema, type NodeView } from "../../domain/cluster/schemas";
import { sampleNode } from "../../test/fixtures/clusterViews";
import {
  capabilityLabel,
  fullUsageQueueDepth,
  needLabel,
  nodeProblems,
  planOfConfig,
  planResources,
  requiredCapabilities,
  simulationJobType,
  simulationJobTypesOf,
  slotsByJobType,
  startBlocker,
} from "./resourcePlan";
import { QUEUE_DEPTH_DEFAULTS } from "./wizard/wizardState";

const KINEMATIC_NODE = ["asv_software/replay", "asv_software/usv_navigation", "control_layer/none", "simulation_layer/kinematic", "scene_generation", "trajectory_generation", "monitoring"];
const SITL_NODE = ["asv_software/replay", "control_layer/ardupilot", "simulation_layer/ardupilot_sim"];

function components(usable: readonly string[], stale: readonly string[] = []) {
  return [...usable.map((component) => ({ component, images: [], state: "usable" })), ...stale.map((component) => ({ component, images: [], state: "out_of_date" }))];
}

/** A node with slots per job type and components, every one of the catalog unless named. */
function node(id: string, slots: Record<string, number>, overrides: Record<string, unknown> = {}, offered: readonly string[] = COMPONENTS): NodeView {
  const usage = Object.fromEntries(Object.entries(slots).map(([jobType, count]) => [jobType, { slots: count, slots_in_use: 0 }]));
  return nodeViewSchema.parse(sampleNode({ node_id: id, name: id, machine: `${id}-pc`, labels: { site: "lab" }, slots: usage, components: components(offered), ...overrides }));
}

const PIPELINE = { scene_generation: 4, trajectory_generation: 4, simulation: 8, "monitoring.post_hoc": 4 };
const KINEMATIC_COMPONENTS = ["asv_software/replay", "control_layer/none", "simulation_layer/kinematic"];

function config(runs: Record<string, unknown>[], resources: Record<string, unknown> = {}): Record<string, unknown> {
  return { trajectories: { generator: "monitor_driven_rrt" }, execution: { runs }, resources };
}

describe("requiredCapabilities", () => {
  it("needs scenes, trajectories, the simulation and the post hoc monitor by default, each with its components", () => {
    const required = requiredCapabilities(config([{}]));
    expect(required.map((capability) => [capability.jobType, capability.components])).toEqual([
      ["scene_generation", ["scene_generation"]],
      ["trajectory_generation", ["trajectory_generation"]],
      ["simulation", KINEMATIC_COMPONENTS],
      ["monitoring.post_hoc", ["monitoring"]],
    ]);
    expect(required[1].reason).toBe("Every case plans its trajectories (monitor-guided planner).");
    expect(required[2].reason).toBe("The run is simulated on the kinematic layer.");
  });

  it("needs the monitoring job only for post hoc runs and the calibration only for repeats", () => {
    const live = requiredCapabilities(config([{ monitor: "live" }, { monitor: "empty" }]));
    expect(live.map((capability) => capability.stage)).toEqual(["generate_scene", "generate_trajectories", "simulate"]);
    const repeated = requiredCapabilities(config([{ name: "nav", monitor: "post_hoc", repeats: 3 }, { monitor: "post_hoc", repeats: 2 }]));
    expect(repeated.map((capability) => capability.stage)).toEqual(["generate_scene", "generate_trajectories", "simulate", "monitor", "calibrate"]);
    expect(repeated[3].reason).toBe("The post hoc monitor judges nav and run 2.");
    expect(repeated[4]).toMatchObject({ components: ["calibration"], reason: "The repeats of nav and run 2 are compared." });
  });
});

describe("requiredCapabilities of a campaign with several stacks", () => {
  const sitl = { name: "sitl", stack: { simulation_layer: "ardupilot_sim" }, monitor: "post_hoc" };
  const world = { stack: { simulation_layer: "gazebo" }, monitor: "live" };

  it("simulates every run with the simulation job type", () => {
    expect(simulationJobType({ simulation_layer: "gazebo" })).toBe("simulation");
    expect(simulationJobType(undefined)).toBe("simulation");
  });

  it("needs the layers of the run's stack", () => {
    const required = requiredCapabilities(config([sitl]));
    expect(required[2]).toMatchObject({ jobType: "simulation", stage: "simulate", components: SITL_NODE, reason: "The run is simulated on ArduPilot SITL." });
    expect(requiredCapabilities(config([world, { ...world, name: "again" }]))[2].reason).toBe("Each of the 2 runs is simulated on Gazebo.");
    const navigation = requiredCapabilities(config([{ stack: { simulation_layer: "kinematic", mode: "usv_navigation" } }]))[2];
    expect(navigation.components).toEqual(["asv_software/replay", "asv_software/usv_navigation", "control_layer/none", "simulation_layer/kinematic"]);
    expect(navigation.reason).toBe("The run is simulated on the kinematic layer with USV Navigation.");
  });

  it("needs one simulation per distinct set of components, naming the runs of each", () => {
    const required = requiredCapabilities(config([{ name: "kinematic" }, sitl, world, { ...sitl, name: "sitl again" }]));
    const simulations = required.filter((capability) => capability.stage === "simulate");
    expect(simulations.map((capability) => [capability.jobType, capability.components.at(-1), capability.reason])).toEqual([
      ["simulation", "simulation_layer/kinematic", "kinematic is simulated on the kinematic layer."],
      ["simulation", "simulation_layer/ardupilot_sim", "sitl and sitl again are simulated on ArduPilot SITL."],
      ["simulation", "simulation_layer/gazebo", "run 3 is simulated on Gazebo."],
    ]);
    expect(capabilityLabel("simulation")).toBe("Simulation");
    expect(needLabel(simulations[2])).toBe("simulation with Replay, ArduPilot and Gazebo");
    expect(needLabel(required[0])).toBe("scene generation");
  });

  it("is missing when no usable node has the run's components", () => {
    const nodes = [node("a", PIPELINE, {}, KINEMATIC_NODE), node("b", { simulation: 2 }, {}, SITL_NODE)];
    const plan = planOfConfig(config([sitl], {}), [nodes[0]]);
    expect(plan.missing.map((capability) => capability.components)).toEqual([SITL_NODE]);
    expect(startBlocker(plan)).toBe("No usable machine of the campaign runs simulation with Replay, ArduPilot and ArduPilot SITL.");
    expect(planOfConfig(config([sitl], {}), nodes).missing).toEqual([]);
    // a SITL node does not run Gazebo runs
    expect(planOfConfig(config([world], {}), nodes).missing.map((capability) => capability.components.at(-1))).toEqual(["simulation_layer/gazebo"]);
  });

  it("does not count a component that is out of date on the node", () => {
    const stale = node("s", { simulation: 2 }, { out_of_date: true, components: components(["asv_software/replay", "control_layer/ardupilot"], ["simulation_layer/ardupilot_sim"]) });
    expect(nodeProblems(stale, {}), "the node's other components still work").toEqual([]);
    expect(planOfConfig(config([sitl], {}), [stale]).missing.map((capability) => capability.stage)).toContain("simulate");
  });
});

describe("requiredCapabilities of a partial campaign", () => {
  function partial(steps: string[], extra: Record<string, unknown> = {}): Record<string, unknown> {
    return { format: 2, steps, trajectories: { generator: "monitor_driven_rrt" }, execution: { runs: [{}] }, resources: {}, ...extra };
  }
  const stages = (c: Record<string, unknown>) => requiredCapabilities(c).map((capability) => capability.stage);

  it("needs only the jobs of the steps it runs", () => {
    expect(stages(partial(["scene_generation"]))).toEqual(["generate_scene"]);
    expect(stages(partial(["scene_generation", "trajectory_generation"]))).toEqual(["generate_scene", "generate_trajectories"]);
    expect(stages(partial(["trajectory_generation", "simulation"]))).toEqual(["generate_trajectories", "simulate", "monitor"]);
    expect(stages(partial(["simulation"]))).toEqual(["simulate", "monitor"]);
  });

  it("needs the monitoring job for a post hoc scene or trajectory monitor, and names what it judges", () => {
    const scenes = requiredCapabilities(partial(["scene_generation"], { scene_generation: { monitor: "post_hoc" } }));
    expect(scenes.map((capability) => capability.stage)).toEqual(["generate_scene", "monitor"]);
    expect(scenes[1].reason).toBe("The post hoc monitor judges the generated scenes.");
    const both = requiredCapabilities(partial(["scene_generation", "trajectory_generation", "simulation"], { scene_generation: { monitor: "post_hoc" }, trajectories: { generator: "straight", monitor: "post_hoc" } }));
    expect(both.find((capability) => capability.stage === "monitor")?.reason).toBe("The post hoc monitor judges the generated scenes, the planned trajectories and run 1.");
  });

  it("ignores the monitor of a step it does not run and the runs of a campaign without simulation", () => {
    expect(stages(partial(["trajectory_generation"], { scene_generation: { monitor: "post_hoc" } }))).toEqual(["generate_trajectories"]);
    expect(stages(partial(["scene_generation", "trajectory_generation"], { execution: { runs: [{ repeats: 3 }] } }))).toEqual(["generate_scene", "generate_trajectories"]);
  });

  it("reads a stored format 1 config, which has no steps, as the whole chain", () => {
    expect(stages({ trajectories: { generator: "straight" }, execution: { runs: [{}] }, resources: {} })).toEqual(["generate_scene", "generate_trajectories", "simulate", "monitor"]);
  });
});

describe("nodeProblems", () => {
  it("accepts an online, current node with the labels", () => {
    expect(nodeProblems(node("a", PIPELINE), { site: "lab" })).toEqual([]);
  });

  it("names every reason a node cannot take jobs", () => {
    const stale = node("a", PIPELINE, { status: "draining", out_of_date: true, components: components([], ["scene_generation", "monitoring"]) });
    expect(nodeProblems(stale, { site: "sea", gpu: "true" })).toEqual([
      "Draining: it takes no new jobs.",
      "Out of date: the images of all its components differ from the master's release.",
      "Lacks the labels site=sea, gpu=true.",
    ]);
    expect(nodeProblems(node("b", PIPELINE, { status: "offline" }), {})).toEqual(["Offline."]);
  });
});

describe("planResources", () => {
  const required = requiredCapabilities(config([{ repeats: 2 }]));
  const nodes = [
    node("a", { scene_generation: 2, trajectory_generation: 2 }),
    node("b", { simulation: 6, "monitoring.post_hoc": 2 }),
    node("c", { simulation: 4, "calibration.deviation": 1 }, { out_of_date: true, components: components([], ["simulation_layer/kinematic", "calibration"]) }),
    node("d", { simulation: 9 }, {}, SITL_NODE),
  ];

  it("covers with every usable node in full usage and reports what no node runs", () => {
    const plan = planResources(required, nodes, { nodes: null, labels: {} });
    expect(plan.usable.map((entry) => entry.node_id)).toEqual(["a", "b", "d"]);
    expect(plan.coverage.map((entry) => [entry.capability.jobType, entry.slots])).toEqual([
      ["scene_generation", 2],
      ["trajectory_generation", 2],
      ["simulation", 6],
      ["monitoring.post_hoc", 2],
      ["calibration.deviation", 0],
    ]);
    expect(plan.coverage[2].nodes.map((entry) => entry.node_id), "the SITL node lacks the kinematic layer").toEqual(["b"]);
    expect(plan.missing.map((capability) => capability.jobType)).toEqual(["calibration.deviation"]);
    expect(startBlocker(plan)).toBe("No usable machine of the campaign runs repeat calibration.");
  });

  it("counts only the selected nodes and lists selected ids the master does not know", () => {
    const plan = planResources(required.slice(0, 3), nodes, { nodes: ["b", "gone"], labels: {} });
    expect(plan.usable.map((entry) => entry.node_id)).toEqual(["b"]);
    expect(plan.missing.map((capability) => capability.jobType)).toEqual(["scene_generation", "trajectory_generation"]);
    expect(plan.unknownNodes).toEqual(["gone"]);
    expect(startBlocker(plan)).toBe("No usable machine of the campaign runs scene generation and trajectory generation.");
    expect(startBlocker(planResources(required.slice(0, 3), nodes, { nodes: ["a", "b"], labels: {} }))).toBeNull();
  });

  it("does not count nodes without the required labels", () => {
    expect(planResources(required.slice(0, 1), nodes, { nodes: null, labels: { site: "sea" } }).missing).toHaveLength(1);
  });

  it("blocks the start while the nodes are unknown", () => {
    expect(startBlocker(null)).toBe("The cluster's machines are not known yet.");
  });
});

describe("planOfConfig", () => {
  it("reads the nodes and labels of a stored config", () => {
    const nodes = [node("a", PIPELINE), node("b", PIPELINE, { labels: {} })];
    const stored = config([{ monitor: "post_hoc", repeats: 1 }], { nodes: ["b"], required_labels: { site: "lab" }, priority: 0 });
    expect(planOfConfig(stored, nodes).usable).toEqual([]);
    expect(planOfConfig(config([{}], { nodes: [], required_labels: {} }), nodes).usable.map((entry) => entry.node_id)).toEqual(["a", "b"]);
  });
});

describe("full usage", () => {
  it("adds the slots of usable nodes per job type", () => {
    const nodes = [node("a", PIPELINE), node("b", { simulation: 40 }), node("c", { simulation: 99 }, { status: "offline" })];
    expect(slotsByJobType(nodes)).toEqual({ scene_generation: 4, trajectory_generation: 4, simulation: 48, "monitoring.post_hoc": 4 });
  });

  it("sizes each queue cap to the slots of its stage, never below the default", () => {
    expect(fullUsageQueueDepth({})).toEqual(QUEUE_DEPTH_DEFAULTS);
    expect(fullUsageQueueDepth({ scene_generation: 40, simulation: 12, "calibration.deviation": 9 })).toEqual({
      ...QUEUE_DEPTH_DEFAULTS,
      generate_scene: 40,
      calibrate: 9,
    });
  });

  it("sizes the simulate cap to the simulation slots once, whatever the runs' stacks", () => {
    expect(fullUsageQueueDepth({ simulation: 50 }).simulate).toBe(50);
    expect(fullUsageQueueDepth({ simulation: 50 }, ["simulation", "simulation"]).simulate).toBe(50);
    expect(simulationJobTypesOf(requiredCapabilities(config([{ stack: { simulation_layer: "gazebo" } }, {}])))).toEqual(["simulation"]);
    expect(simulationJobTypesOf([])).toEqual(["simulation"]);
  });

  it("names capabilities without the comma of the cluster labels", () => {
    expect(capabilityLabel("custom.job")).toBe("custom.job");
  });
});
