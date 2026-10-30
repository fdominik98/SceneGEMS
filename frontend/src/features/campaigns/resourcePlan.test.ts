import { describe, expect, it } from "vitest";
import { nodeViewSchema, type NodeView } from "../../domain/cluster/schemas";
import { sampleNode } from "../../test/fixtures/clusterViews";
import {
  capabilityLabel,
  fullUsageQueueDepth,
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

function node(id: string, capabilities: Record<string, number>, overrides: Record<string, unknown> = {}): NodeView {
  const usage = Object.fromEntries(Object.entries(capabilities).map(([jobType, slots]) => [jobType, { slots, slots_in_use: 0 }]));
  return nodeViewSchema.parse(sampleNode({ node_id: id, name: id, machine: `${id}-pc`, labels: { site: "lab" }, capabilities: usage, ...overrides }));
}

const PIPELINE = { scene_generation: 4, trajectory_generation: 4, "simulation.kinematic": 8, "monitoring.post_hoc": 4 };

function config(runs: Record<string, unknown>[], resources: Record<string, unknown> = {}): Record<string, unknown> {
  return { trajectories: { generator: "monitor_driven_rrt" }, execution: { runs }, resources };
}

describe("requiredCapabilities", () => {
  it("needs scenes, trajectories, the simulation and the post hoc monitor by default", () => {
    const required = requiredCapabilities(config([{}]));
    expect(required.map((capability) => capability.jobType)).toEqual(["scene_generation", "trajectory_generation", "simulation.kinematic", "monitoring.post_hoc"]);
    expect(required[1].reason).toBe("Every case plans its trajectories (monitor driven rrt).");
  });

  it("needs the monitoring job only for post hoc runs and the calibration only for repeats", () => {
    const live = requiredCapabilities(config([{ monitor: "live" }, { monitor: "empty" }]));
    expect(live.map((capability) => capability.stage)).toEqual(["generate_scene", "generate_trajectories", "simulate"]);
    const repeated = requiredCapabilities(config([{ name: "nav", monitor: "post_hoc", repeats: 3 }, { monitor: "post_hoc", repeats: 2 }]));
    expect(repeated.map((capability) => capability.stage)).toEqual(["generate_scene", "generate_trajectories", "simulate", "monitor", "calibrate"]);
    expect(repeated[3].reason).toBe("The post hoc monitor judges nav and run 2.");
    expect(repeated[4].reason).toBe("The repeats of nav and run 2 are compared.");
  });
});

describe("requiredCapabilities of a campaign with ArduPilot runs", () => {
  const sitl = { name: "sitl", stack: { simulation_layer: "ardupilot_sim" }, monitor: "post_hoc" };
  const world = { stack: { simulation_layer: "gazebo" }, monitor: "live" };

  it("reads the simulation job type of a run from its stack, as stage_graph does", () => {
    expect(simulationJobType({ simulation_layer: "ardupilot_sim" })).toBe("simulation.ardupilot_sim");
    expect(simulationJobType({ simulation_layer: "gazebo" })).toBe("simulation.gazebo");
    expect(simulationJobType({ simulation_layer: "kinematic", mode: "replay" })).toBe("simulation.kinematic");
    expect(simulationJobType({ mode: "usv_navigation" })).toBe("simulation.kinematic");
    expect(simulationJobType(undefined)).toBe("simulation.kinematic");
  });

  it("needs the ArduPilot simulation of the run's layer instead of the kinematic one", () => {
    const required = requiredCapabilities(config([sitl]));
    expect(required.map((capability) => capability.jobType)).toEqual(["scene_generation", "trajectory_generation", "simulation.ardupilot_sim", "monitoring.post_hoc"]);
    expect(required[2]).toMatchObject({ stage: "simulate", reason: "The run is simulated on ArduPilot SITL." });
    expect(requiredCapabilities(config([world, { ...world, name: "again" }]))[2].reason).toBe("Each of the 2 runs is simulated on Gazebo.");
  });

  it("needs both simulation jobs for a mix, naming the runs of each", () => {
    const required = requiredCapabilities(config([{ name: "kinematic" }, sitl, world]));
    const simulations = required.filter((capability) => capability.stage === "simulate");
    expect(simulations.map((capability) => [capability.jobType, capability.reason])).toEqual([
      ["simulation.kinematic", "kinematic is simulated on the kinematic layer."],
      ["simulation.ardupilot_sim", "sitl is simulated on ArduPilot SITL."],
      ["simulation.gazebo", "run 3 is simulated on Gazebo."],
    ]);
    expect(capabilityLabel("simulation.ardupilot_sim")).toBe("ArduPilot SITL simulation");
    expect(capabilityLabel("simulation.gazebo")).toBe("Gazebo simulation");
  });

  it("is missing when no usable node offers the ArduPilot simulation of the run's layer", () => {
    const nodes = [node("a", PIPELINE), node("b", { "simulation.ardupilot_sim": 2 })];
    const plan = planOfConfig(config([sitl], {}), [nodes[0]]);
    expect(plan.missing.map((capability) => capability.jobType)).toEqual(["simulation.ardupilot_sim"]);
    expect(startBlocker(plan)).toBe("No usable machine of the campaign runs ardupilot sitl simulation.");
    expect(planOfConfig(config([sitl], {}), nodes).missing).toEqual([]);
    // a SITL node does not run Gazebo runs
    expect(planOfConfig(config([world], {}), nodes).missing.map((capability) => capability.jobType)).toEqual(["simulation.gazebo"]);
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
    const stale = node("a", PIPELINE, { status: "draining", out_of_date: true });
    expect(nodeProblems(stale, { site: "sea", gpu: "true" })).toEqual([
      "Draining: it takes no new jobs.",
      "Out of date: its images differ from the master's release.",
      "Lacks the labels site=sea, gpu=true.",
    ]);
    expect(nodeProblems(node("b", PIPELINE, { status: "offline" }), {})).toEqual(["Offline."]);
  });
});

describe("planResources", () => {
  const required = requiredCapabilities(config([{ repeats: 2 }]));
  const nodes = [
    node("a", { scene_generation: 2, trajectory_generation: 2 }),
    node("b", { "simulation.kinematic": 6, "monitoring.post_hoc": 2 }),
    node("c", { "simulation.kinematic": 4, "calibration.deviation": 1 }, { out_of_date: true }),
  ];

  it("covers with every usable node in full usage and reports what no node runs", () => {
    const plan = planResources(required, nodes, { nodes: null, labels: {} });
    expect(plan.usable.map((entry) => entry.node_id)).toEqual(["a", "b"]);
    expect(plan.coverage.map((entry) => [entry.capability.jobType, entry.slots])).toEqual([
      ["scene_generation", 2],
      ["trajectory_generation", 2],
      ["simulation.kinematic", 6],
      ["monitoring.post_hoc", 2],
      ["calibration.deviation", 0],
    ]);
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
    const nodes = [node("a", PIPELINE), node("b", { "simulation.kinematic": 40 }), node("c", { "simulation.kinematic": 99 }, { status: "offline" })];
    expect(slotsByJobType(nodes)).toEqual({ scene_generation: 4, trajectory_generation: 4, "simulation.kinematic": 48, "monitoring.post_hoc": 4 });
  });

  it("sizes each queue cap to the slots of its stage, never below the default", () => {
    expect(fullUsageQueueDepth({})).toEqual(QUEUE_DEPTH_DEFAULTS);
    expect(fullUsageQueueDepth({ scene_generation: 40, "simulation.kinematic": 12, "calibration.deviation": 9 })).toEqual({
      ...QUEUE_DEPTH_DEFAULTS,
      generate_scene: 40,
      calibrate: 9,
    });
  });

  it("sizes the simulate cap to the slots of the simulation jobs the runs use", () => {
    const slots = { "simulation.kinematic": 12, "simulation.ardupilot_sim": 20, "simulation.gazebo": 4 };
    expect(fullUsageQueueDepth(slots, ["simulation.ardupilot_sim"]).simulate).toBe(32);
    expect(fullUsageQueueDepth(slots, ["simulation.kinematic", "simulation.ardupilot_sim"]).simulate).toBe(32);
    expect(fullUsageQueueDepth(slots, ["simulation.ardupilot_sim", "simulation.gazebo"]).simulate).toBe(32);
    expect(fullUsageQueueDepth({ "simulation.gazebo": 50 }, ["simulation.gazebo"]).simulate).toBe(50);
    expect(fullUsageQueueDepth({ "simulation.gazebo": 50 }).simulate).toBe(QUEUE_DEPTH_DEFAULTS.simulate);
    expect(simulationJobTypesOf(requiredCapabilities(config([{ stack: { simulation_layer: "gazebo" } }, {}])))).toEqual(["simulation.gazebo", "simulation.kinematic"]);
    expect(simulationJobTypesOf([])).toEqual(["simulation.kinematic"]);
  });

  it("names capabilities without the comma of the cluster labels", () => {
    expect(capabilityLabel("simulation.kinematic")).toBe("Kinematic simulation");
    expect(capabilityLabel("custom.job")).toBe("custom.job");
  });
});
