import { describe, expect, it } from "vitest";
import { catalogStacksSchema, type CatalogStack } from "../../../domain/cluster/campaignApi";
import { sampleCatalogStacks } from "../../../test/fixtures/campaignCatalog";
import { activePicks, facetViews, filterCatalog, groupCatalog } from "./catalogModel";
import { controlValue, repeatabilityValue, STACK_CATALOG, supportValues } from "./stackCatalog";

const stacks = catalogStacksSchema.parse(sampleCatalogStacks).stacks;

function stackOf(id: string): CatalogStack {
  const found = stacks.find((stack) => stack.id === id);
  if (!found) {
    throw new Error(`no stack ${id}`);
  }
  return found;
}

function idsWith(picks: Record<string, string[]>, query = ""): string[] {
  return filterCatalog(stacks, STACK_CATALOG, activePicks(stacks, STACK_CATALOG, picks), query).map((stack) => stack.id);
}

describe("the stack catalog", () => {
  it("offers the facets that tell the stacks apart", () => {
    const facets = facetViews(stacks, STACK_CATALOG, {}, "");
    expect(facets.map((facet) => facet.label)).toEqual(["Simulation layer", "Control layer", "Own ship software", "Repeatability", "Supports"]);
    expect(facets[0].options.map((option) => [option.label, option.count])).toEqual([
      ["Kinematic layer", 2],
      ["ArduPilot SITL", 2],
      ["Gazebo", 2],
    ]);
    expect(facets[1].options.map((option) => option.label)).toEqual(["No control layer", "ArduPilot", "Custom controller"]);
    expect(facets[2].options.map((option) => option.label)).toEqual(["Replay", "USV Navigation"]);
    expect(facets[3].options.map((option) => option.label)).toEqual(["Exact", "Bounded"]);
    expect(facets[4].options.map((option) => option.label)).toEqual(["Wind", "Waves", "Early stop"]);
  });

  it("filters by layer and software together", () => {
    expect(idsWith({ simulation: ["gazebo"], software: ["usv_navigation"] })).toEqual(["gazebo_custom.usv_navigation"]);
    expect(idsWith({ simulation: ["kinematic", "ardupilot_sim"], software: ["replay"] })).toEqual(["kinematic.replay", "ardupilot_sim.replay"]);
  });

  it("needs every picked capability", () => {
    expect(idsWith({ supports: ["wind", "waves"] })).toEqual(["gazebo_custom.replay", "gazebo_custom.usv_navigation"]);
    expect(idsWith({ supports: ["wind", "early_stop"] })).toEqual([]);
  });

  it("finds a stack by a word of its description or of its facets", () => {
    expect(idsWith({}, "mavlink")).toEqual(["ardupilot_sim.replay"]);
    expect(idsWith({}, "custom controller usv")).toEqual(["gazebo_custom.usv_navigation"]);
  });

  it("groups by the simulation layer first and can group by any any-facet", () => {
    expect(STACK_CATALOG.groupings.map((grouping) => grouping.key)).toEqual(["simulation", "control", "software", "repeatability"]);
    expect(groupCatalog(stacks, STACK_CATALOG.groupings[0]).map((group) => [group.label, group.items.length])).toEqual([
      ["Kinematic layer", 2],
      ["ArduPilot SITL", 2],
      ["Gazebo", 2],
    ]);
  });

  it("offers availability only when the control node cannot run a stack, and says so", () => {
    const withUnavailable = stacks.map((stack) => (stack.id === "gazebo_custom.replay" ? { ...stack, available: false, repeatability_tier: null } : stack));
    const facets = facetViews(withUnavailable, STACK_CATALOG, {}, "");
    expect(facets.map((facet) => facet.key)).toContain("availability");
    expect(facets.find((facet) => facet.key === "availability")?.options.map((option) => [option.label, option.count])).toEqual([
      ["Runs on this control node", 5],
      ["Cannot run on this control node", 1],
    ]);
  });
});

describe("what a stack is sorted by", () => {
  it("reads the control layer from the own ship on a control node that does not report it", () => {
    expect(controlValue({ ...stackOf("ardupilot_sim.replay"), control_layer: undefined }).value).toBe("ardupilot");
  });

  it("calls a stack without a tier unknown, and keeps a tier it does not know", () => {
    const stack = stackOf("kinematic.replay");
    expect(repeatabilityValue({ ...stack, repeatability_tier: null }).label).toBe("Unknown");
    expect(repeatabilityValue({ ...stack, repeatability_tier: "none" }).label).toBe("No claim");
    expect(repeatabilityValue({ ...stack, repeatability_tier: "measured" }).label).toBe("measured");
  });

  it("counts an unmeasured environment as supported, as the Simulation page offers it", () => {
    const stack = stackOf("kinematic.replay");
    const unmeasured = { ...stack, environment: { ...stack.environment, wind: "unmeasured" } };
    expect(supportValues(unmeasured).map((entry) => entry.value)).toEqual(["wind", "early_stop"]);
  });
});
