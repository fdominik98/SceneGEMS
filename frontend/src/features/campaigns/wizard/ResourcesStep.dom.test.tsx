import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { nodeViewSchema, type NodeView } from "../../../domain/cluster/schemas";
import { sampleNode } from "../../../test/fixtures/clusterViews";
import { needKey, planResources, requiredCapabilities, slotsByJobType, startBlocker } from "../resourcePlan";
import { parseReasons } from "./reasons";
import { ResourcesStep } from "./ResourcesStep";
import type { ClusterResources } from "./stepTypes";
import { StepHarness } from "./wizardTestHarness";
import { draftOf } from "./wizardTestData";

const SITL = ["asv_software/replay", "control_layer/ardupilot", "simulation_layer/ardupilot_sim"];
const GAZEBO_ONLY = ["asv_software/replay", "control_layer/custom", "simulation_layer/gazebo"];

function node(id: string, slots: Record<string, number>, offered: readonly string[]): NodeView {
  const usage = Object.fromEntries(Object.entries(slots).map(([jobType, count]) => [jobType, { slots: count, slots_in_use: 0 }]));
  const components = offered.map((component) => ({ component, images: [], state: "usable" }));
  return nodeViewSchema.parse(sampleNode({ node_id: id, name: id, machine: `${id}-pc`, slots: usage, components }));
}

/** Two runs on different stacks: ArduPilot SITL and the custom controller on Gazebo, so two simulation needs. */
const CONFIG = {
  steps: ["simulation"],
  execution: {
    runs: [
      { name: "sitl", stack: { simulation_layer: "ardupilot_sim" }, monitor: "empty" },
      { name: "world", stack: { simulation_layer: "gazebo", control_layer: "custom" }, monitor: "empty" },
    ],
  },
};

function cluster(nodes: NodeView[]): ClusterResources {
  const plan = planResources(requiredCapabilities(CONFIG), nodes, { nodes: null, labels: {} });
  return { selected: true, loaded: true, error: null, nodes, plan, slots: slotsByJobType(nodes), startBlocker: startBlocker(plan) };
}

function setup(nodes: NodeView[]) {
  render(<StepHarness Page={ResourcesStep} extra={{ cluster: cluster(nodes) }} initial={draftOf()} reasons={parseReasons([])} />);
}

describe("the Resources page", () => {
  it("lists one need per stage and component set, each named with its components", () => {
    setup([node("sitl", { simulation: 2 }, SITL)]);
    const needs = within(screen.getByRole("region", { name: "What the campaign needs" })).getAllByRole("listitem");
    const texts = needs.map((item) => item.textContent ?? "");
    expect(texts).toHaveLength(2);
    expect(texts[0]).toContain("Simulation with Replay, ArduPilot and ArduPilot SITL");
    expect(texts[0]).toContain("1 machine, 2 slots");
    expect(texts[1]).toContain("Simulation with Replay, Custom controller and Gazebo");
    expect(texts[1]).toContain("world is simulated on the custom controller with Gazebo.");
    expect(texts[1]).toContain("No machine");
  });

  it("shows a machine's slots by job type, from the node's slots", () => {
    setup([node("gazebo", { simulation: 3, "monitoring.post_hoc": 1 }, GAZEBO_ONLY)]);
    const slots = screen.getByRole("list", { name: "Capabilities of gazebo-pc" });
    expect(within(slots).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["Simulation 3 slots", "Post hoc monitoring 1 slot"]);
  });

  it("keys the need rows apart, so a node without SITL covers only the custom controller's need", () => {
    const nodes = [node("gazebo", { simulation: 1 }, GAZEBO_ONLY)];
    const plan = cluster(nodes).plan!;
    expect(new Set(plan.coverage.map((entry) => needKey(entry.capability))).size).toBe(2);
    expect(plan.coverage.map((entry) => entry.nodes.map((covering) => covering.node_id))).toEqual([[], ["gazebo"]]);
    setup(nodes);
    expect(screen.getByRole("alert")).toHaveTextContent("No usable machine of the campaign runs simulation with Replay, ArduPilot and ArduPilot SITL.");
  });
});
