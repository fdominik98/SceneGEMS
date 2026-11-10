import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { workerNodeViewSchema, type WorkerNodeView } from "../../../domain/cluster/schemas";
import { sampleWorkerNode } from "../../../test/fixtures/clusterViews";
import { needKey, planResources, requiredCapabilities, slotsByJobType, startBlocker } from "../resourcePlan";
import { parseReasons } from "./reasons";
import { ResourcesStep } from "./ResourcesStep";
import type { ClusterResources } from "./stepTypes";
import { StepHarness } from "./wizardTestHarness";
import { draftOf } from "./wizardTestData";

const SITL = ["asv_system/replay", "control_layer/ardupilot", "simulation_layer/ardupilot_sim"];
const GAZEBO_ONLY = ["asv_system/replay", "control_layer/custom", "simulation_layer/gazebo"];

function workerNode(id: string, slots: Record<string, number>, offered: readonly string[]): WorkerNodeView {
  const usage = Object.fromEntries(Object.entries(slots).map(([jobType, count]) => [jobType, { slots: count, slots_in_use: 0 }]));
  const components = offered.map((component) => ({ component, images: [], state: "usable" }));
  return workerNodeViewSchema.parse(sampleWorkerNode({ worker_node_id: id, name: id, machine: `${id}-pc`, slots: usage, components }));
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

function cluster(workerNodes: WorkerNodeView[]): ClusterResources {
  const plan = planResources(requiredCapabilities(CONFIG), workerNodes, { workerNodes: null, labels: {} });
  return { selected: true, loaded: true, error: null, workerNodes, plan, slots: slotsByJobType(workerNodes), startBlocker: startBlocker(plan) };
}

function setup(workerNodes: WorkerNodeView[]) {
  render(<StepHarness Page={ResourcesStep} extra={{ cluster: cluster(workerNodes) }} initial={draftOf()} reasons={parseReasons([])} />);
}

describe("the Resources page", () => {
  it("lists one need per stage and component set, each named with its components", () => {
    setup([workerNode("sitl", { simulation: 2 }, SITL)]);
    const needs = within(screen.getByRole("region", { name: "What the campaign needs" })).getAllByRole("listitem");
    const texts = needs.map((item) => item.textContent ?? "");
    expect(texts).toHaveLength(2);
    expect(texts[0]).toContain("Simulation with Replay, ArduPilot and ArduPilot SITL");
    expect(texts[0]).toContain("1 machine, 2 slots");
    expect(texts[1]).toContain("Simulation with Replay, Custom controller and Gazebo");
    expect(texts[1]).toContain("world is simulated on the custom controller with Gazebo.");
    expect(texts[1]).toContain("No machine");
  });

  it("shows a machine's slots by job type, from the worker node's slots", () => {
    setup([workerNode("gazebo", { simulation: 3, "monitoring.post_hoc": 1 }, GAZEBO_ONLY)]);
    const slots = screen.getByRole("list", { name: "Capabilities of gazebo-pc" });
    expect(within(slots).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["Simulation 3 slots", "Post hoc monitoring 1 slot"]);
  });

  it("keys the need rows apart, so a worker node without SITL covers only the custom controller's need", () => {
    const workerNodes = [workerNode("gazebo", { simulation: 1 }, GAZEBO_ONLY)];
    const plan = cluster(workerNodes).plan!;
    expect(new Set(plan.coverage.map((entry) => needKey(entry.capability))).size).toBe(2);
    expect(plan.coverage.map((entry) => entry.workerNodes.map((covering) => covering.worker_node_id))).toEqual([[], ["gazebo"]]);
    setup(workerNodes);
    expect(screen.getByRole("alert")).toHaveTextContent("No usable machine of the campaign runs simulation with Replay, ArduPilot and ArduPilot SITL.");
  });
});
