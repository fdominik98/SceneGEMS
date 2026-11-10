import { describe, expect, it } from "vitest";
import { catalogClassSchema, catalogStacksSchema } from "../../../domain/cluster/campaignApi";
import { campaignPresetSchema, type CampaignPreset } from "../../../domain/cluster/presetsApi";
import { sampleCatalogClasses, sampleCatalogStacks } from "../../../test/fixtures/campaignCatalog";
import { activePicks, facetViews, filterCatalog, groupCatalog } from "./catalogModel";
import type { BuilderCatalog } from "./configBuilder";
import { describeSteps, PRESET_CATALOG, presetFacts, scopeTags, type PresetFacts } from "./presetCatalog";

const parsed = catalogStacksSchema.parse(sampleCatalogStacks);
const catalog: BuilderCatalog = { stacks: parsed.stacks, generators: parsed.trajectory_generators };
const classes = sampleCatalogClasses.map((entry) => catalogClassSchema.parse(entry));

const WHOLE_CHAIN = ["scene_generation", "trajectory_generation", "simulation"];
const KINEMATIC = { simulation_layer: "kinematic", mode: "replay" };
const USV = { simulation_layer: "kinematic", mode: "usv_navigation" };
const SITL = { simulation_layer: "ardupilot_sim", mode: "replay", speedup: 10 };

function preset(id: string, steps: string[], scope: unknown[], stacks: unknown[], extra: Partial<CampaignPreset> = {}): CampaignPreset {
  return campaignPresetSchema.parse({
    preset_id: id,
    name: id,
    description: `about ${id}`,
    builtin: true,
    steps,
    config: { format: 3, name: id, steps, scope, execution: { runs: stacks.map((stack) => ({ stack, monitor: "post_hoc" })) } },
    created_at: null,
    updated_at: null,
    ...extra,
  });
}

const PRESETS = [
  preset("two", WHOLE_CHAIN, [{ patterns: ["2vessel_*_scenarios"], quota: 5, failure_budget: 5 }], [KINEMATIC]),
  preset("compare", WHOLE_CHAIN, [{ patterns: ["2vessel_*_scenarios", "3vessel_*_scenarios"], quota: 3, failure_budget: 3 }], [KINEMATIC, USV]),
  preset("sitl", WHOLE_CHAIN, [{ patterns: ["2vessel_0obstacle_scenarios"], quota: 2, failure_budget: 2 }], [SITL]),
  preset("scenes", ["scene_generation"], [{ patterns: ["*"], quota: 1, failure_budget: 1 }], []),
  preset("saved_trajectories", ["simulation"], [], [KINEMATIC, SITL]),
  preset("mine", WHOLE_CHAIN, [{ fecs: ["4vessel_0obstacle_scenarios/fec1"], quota: 1, failure_budget: 1 }], [SITL], { builtin: false }),
];

const FACTS = PRESETS.map((entry) => presetFacts(entry, catalog, classes));

function factsOf(id: string): PresetFacts {
  const found = FACTS.find((facts) => facts.preset.preset_id === id);
  if (!found) {
    throw new Error(`no preset ${id}`);
  }
  return found;
}

function idsWith(picks: Record<string, string[]>, query = ""): string[] {
  return filterCatalog(FACTS, PRESET_CATALOG, activePicks(FACTS, PRESET_CATALOG, picks), query).map((facts) => facts.preset.preset_id);
}

describe("presetFacts", () => {
  it("reads the vessel and obstacle counts of the FECs its patterns select", () => {
    expect(factsOf("two")).toMatchObject({ vessels: [2], obstacles: [0, 1], fromInput: false, fecs: 4, cases: 20 });
    expect(factsOf("compare")).toMatchObject({ vessels: [2, 3], obstacles: [0, 1], fecs: 6, cases: 18 });
    expect(factsOf("scenes")).toMatchObject({ vessels: [2, 3, 4], obstacles: [0, 1], fecs: 7, cases: 7 });
  });

  it("reads FECs a scope names, under the format 3 key and the older one", () => {
    expect(factsOf("mine")).toMatchObject({ vessels: [4], obstacles: [0], fecs: 1 });
    const older = preset("older", WHOLE_CHAIN, [{ classes: ["3vessel_0obstacle_scenarios/fec1"], quota: 1, failure_budget: 1 }], [KINEMATIC]);
    expect(presetFacts(older, catalog, classes).vessels).toEqual([3]);
  });

  it("says that the input decides for a preset without a scope", () => {
    expect(factsOf("saved_trajectories")).toMatchObject({ fromInput: true, vessels: [], obstacles: [], fecs: null, cases: null });
  });

  it("lists the stacks of its runs, none when it does not simulate", () => {
    expect(factsOf("compare").stacks.map((stack) => stack.id)).toEqual(["kinematic.replay", "kinematic.usv_navigation"]);
    expect(factsOf("saved_trajectories").stacks.map((stack) => stack.id)).toEqual(["kinematic.replay", "ardupilot_sim.replay"]);
    expect(factsOf("scenes").stacks).toEqual([]);
  });

  it("ignores runs left in the config of a preset that does not simulate", () => {
    const facts = presetFacts(preset("no_simulation", ["scene_generation"], [{ patterns: ["*"], quota: 1, failure_budget: 1 }], [SITL]), catalog, classes);
    expect(facts.stacks).toEqual([]);
    expect(facts.blocked).toBe(false);
  });

  it("flags a run on a stack the control node does not offer or cannot run", () => {
    expect(factsOf("two").blocked).toBe(false);
    const unknown = preset("unknown", WHOLE_CHAIN, [{ patterns: ["*"], quota: 1, failure_budget: 1 }], [{ simulation_layer: "somewhere", mode: "replay" }]);
    expect(presetFacts(unknown, catalog, classes)).toMatchObject({ blocked: true, stacks: [] });
    const cannotRun = { ...catalog, stacks: catalog.stacks.map((stack) => (stack.id === "kinematic.replay" ? { ...stack, available: false } : stack)) };
    expect(presetFacts(PRESETS[0], cannotRun, classes).blocked).toBe(true);
  });

  it("states nothing it cannot read yet while the catalogs load", () => {
    expect(presetFacts(PRESETS[0], null, undefined)).toMatchObject({ vessels: [], obstacles: [], fecs: null, cases: null, stacks: [], blocked: false, fromInput: false });
  });

  it("does not read the input in for a pattern the catalog does not have", () => {
    const facts = presetFacts(preset("nothing", WHOLE_CHAIN, [{ patterns: ["9vessel_*"], quota: 1, failure_budget: 1 }], [KINEMATIC]), catalog, classes);
    expect(facts).toMatchObject({ vessels: [], fromInput: false, fecs: 0 });
  });
});

describe("the preset catalog", () => {
  it("offers the facets that tell the presets apart", () => {
    const facets = facetViews(FACTS, PRESET_CATALOG, {}, "");
    expect(facets.map((facet) => facet.label)).toEqual(["Source", "Vessels", "Obstacles", "Simulation stack", "Steps"]);
    expect(facets[1].options.map((option) => [option.label, option.count])).toEqual([
      ["2 vessels", 4],
      ["3 vessels", 2],
      ["4 vessels", 2],
      ["Set by the input", 1],
    ]);
    expect(facets[2].options.map((option) => option.label)).toEqual(["No obstacles", "1 obstacle", "Set by the input"]);
    expect(facets[3].options.map((option) => option.label)).toEqual(["Replay on the kinematic layer", "USV Navigation on the kinematic layer", "Replay on ArduPilot SITL"]);
  });

  it("filters by vessel count", () => {
    expect(idsWith({ vessels: ["3"] })).toEqual(["compare", "scenes"]);
    expect(idsWith({ vessels: ["4", "input"] })).toEqual(["scenes", "saved_trajectories", "mine"]);
  });

  it("filters by simulation stack and vessel count together", () => {
    expect(idsWith({ stack: ["ardupilot_sim.replay"] })).toEqual(["sitl", "saved_trajectories", "mine"]);
    expect(idsWith({ stack: ["ardupilot_sim.replay"], vessels: ["2"] })).toEqual(["sitl"]);
    expect(idsWith({ stack: ["kinematic.usv_navigation"], obstacles: ["1"] })).toEqual(["compare"]);
  });

  it("filters by source and by the steps a preset needs to have", () => {
    expect(idsWith({ source: ["saved"] })).toEqual(["mine"]);
    expect(idsWith({ steps: ["simulation"], source: ["shipped"] })).toEqual(["two", "compare", "sitl", "saved_trajectories"]);
    expect(idsWith({ steps: ["scene_generation", "simulation"], source: ["shipped"] })).toEqual(["two", "compare", "sitl"]);
  });

  it("finds a preset by its name, its description or what it is sorted by", () => {
    expect(idsWith({}, "about compare")).toEqual(["compare"]);
    expect(idsWith({}, "usv navigation")).toEqual(["compare"]);
    expect(idsWith({}, "sitl")).toEqual(["sitl", "saved_trajectories", "mine"]);
  });

  it("groups by source first, and by vessels, stack and steps", () => {
    const groupingOf = (key: string) => {
      const grouping = PRESET_CATALOG.groupings.find((entry) => entry.key === key);
      if (!grouping) {
        throw new Error(`no grouping ${key}`);
      }
      return groupCatalog(FACTS, grouping).map((group) => [group.label, group.items.map((facts) => facts.preset.preset_id)]);
    };
    expect(PRESET_CATALOG.groupings[0].key).toBe("source");
    expect(groupingOf("source")).toEqual([
      ["Shipped with the control node", ["two", "compare", "sitl", "scenes", "saved_trajectories"]],
      ["Saved on this cluster", ["mine"]],
    ]);
    expect(groupingOf("vessels").at(-1)).toEqual(["Set by the input", ["saved_trajectories"]]);
    expect(groupingOf("stack").at(-1)).toEqual(["No simulation", ["scenes"]]);
    expect(groupingOf("steps")).toEqual([
      ["Whole chain", ["two", "compare", "sitl", "mine"]],
      ["Scene generation", ["scenes"]],
      ["Simulation", ["saved_trajectories"]],
    ]);
  });
});

describe("what a preset's card says", () => {
  it("states the scope in words", () => {
    expect(scopeTags(factsOf("two"))).toEqual(["2 vessels, with and without obstacles", "4 FECs, 20 cases"]);
    expect(scopeTags(factsOf("compare"))[0]).toBe("2 to 3 vessels, with and without obstacles");
    expect(scopeTags(factsOf("sitl"))[0]).toBe("2 vessels, no obstacles");
    expect(scopeTags(factsOf("saved_trajectories"))).toEqual(["Input picked in the wizard"]);
  });

  it("states nothing about the scope before the FEC catalog is read", () => {
    expect(scopeTags(presetFacts(PRESETS[0], catalog, undefined))).toEqual([]);
  });

  it("names the steps", () => {
    expect(describeSteps(["scene_generation", "trajectory_generation", "simulation"])).toBe("Whole chain");
    expect(describeSteps(["scene_generation", "trajectory_generation"])).toBe("Scene generation, Trajectory generation");
  });
});
