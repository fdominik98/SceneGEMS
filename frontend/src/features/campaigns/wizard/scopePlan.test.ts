import { describe, expect, it } from "vitest";
import { catalogClassSchema } from "../../../domain/cluster/campaignApi";
import { sampleCatalogClasses } from "../../../test/fixtures/campaignCatalog";
import { expandPattern, globToRegExp, planScope, summarizeFolders } from "./scopePlan";
import type { ScopeEntryDraft } from "./wizardState";

const catalog = sampleCatalogClasses.map((entry) => catalogClassSchema.parse(entry));

function entry(overrides: Partial<ScopeEntryDraft>): ScopeEntryDraft {
  return { id: "e", classes: [], patterns: [], quota: 1, failureBudget: 0, ...overrides };
}

describe("globToRegExp", () => {
  it("matches shell wildcards over the whole text", () => {
    expect(globToRegExp("2vessel_*_scenarios").test("2vessel_0obstacle_scenarios")).toBe(true);
    expect(globToRegExp("2vessel_*_scenarios").test("12vessel_0obstacle_scenarios")).toBe(false);
    expect(globToRegExp("fec?").test("fec5")).toBe(true);
    expect(globToRegExp("fec?").test("fec10")).toBe(false);
    expect(globToRegExp("[23]vessel*").test("3vessel_x")).toBe(true);
    expect(globToRegExp("[!2]vessel*").test("2vessel_x")).toBe(false);
  });

  it("treats the characters of a regular expression literally", () => {
    expect(globToRegExp("a.b").test("axb")).toBe(false);
    expect(globToRegExp("a.b").test("a.b")).toBe(true);
    expect(globToRegExp("a+b(c)").test("a+b(c)")).toBe(true);
    expect(globToRegExp("a[b").test("a[b")).toBe(true);
  });
});

describe("expandPattern", () => {
  it("matches folders without a slash and class ids with one, in catalog order", () => {
    expect(expandPattern("2vessel_*_scenarios", catalog).map((entry) => entry.fec_id)).toEqual([
      "2vessel_0obstacle_scenarios/fec1",
      "2vessel_0obstacle_scenarios/fec2",
      "2vessel_0obstacle_scenarios/fec10",
      "2vessel_1obstacle_scenarios/fec1",
    ]);
    expect(expandPattern("*/fec1", catalog)).toHaveLength(4);
    expect(expandPattern("no_such_folder", catalog)).toEqual([]);
  });
});

describe("planScope", () => {
  it("counts the cases of patterns and classes by their quotas", () => {
    const plan = planScope(
      [
        entry({ patterns: ["2vessel_0obstacle_scenarios"], quota: 15 }),
        entry({ classes: ["3vessel_0obstacle_scenarios/fec5"], quota: 4 }),
      ],
      catalog
    );
    expect(plan.classes).toBe(4);
    expect(plan.casesPlanned).toBe(3 * 15 + 4);
    expect(plan.entries.map((item) => item.casesPlanned)).toEqual([45, 4]);
  });

  it("counts a class once, for the first entry that names it, and reports the repeats", () => {
    const plan = planScope(
      [entry({ patterns: ["3vessel_*_scenarios"], quota: 2 }), entry({ classes: ["3vessel_0obstacle_scenarios/fec1", "4vessel_0obstacle_scenarios/fec1"], quota: 5 })],
      catalog
    );
    expect(plan.entries[0].classes).toHaveLength(2);
    expect(plan.entries[1].classes.map((item) => item.fec_id)).toEqual(["4vessel_0obstacle_scenarios/fec1"]);
    expect(plan.entries[1].duplicates).toEqual(["3vessel_0obstacle_scenarios/fec1"]);
    expect(plan.casesPlanned).toBe(4 + 5);
  });

  it("does not count a class twice inside one entry", () => {
    const plan = planScope([entry({ classes: ["3vessel_0obstacle_scenarios/fec1"], patterns: ["3vessel_*_scenarios"], quota: 1 })], catalog);
    expect(plan.classes).toBe(2);
    expect(plan.entries[0].duplicates).toEqual([]);
  });

  it("reports unknown classes and patterns that match nothing, and a missing quota as zero cases", () => {
    const plan = planScope([entry({ classes: ["x/y"], patterns: ["9vessel_*"], quota: null })], catalog);
    expect(plan.entries[0].unknownClasses).toEqual(["x/y"]);
    expect(plan.entries[0].emptyPatterns).toEqual(["9vessel_*"]);
    expect(plan.casesPlanned).toBe(0);
  });
});

describe("summarizeFolders", () => {
  it("counts the classes of each folder with the vessel and obstacle counts they hold", () => {
    const folders = summarizeFolders(catalog);
    expect(folders.map((folder) => [folder.folder, folder.classes])).toEqual([
      ["2vessel_0obstacle_scenarios", 3],
      ["2vessel_1obstacle_scenarios", 1],
      ["3vessel_0obstacle_scenarios", 2],
      ["4vessel_0obstacle_scenarios", 1],
    ]);
    expect(folders[1]).toMatchObject({ vessels: [2], obstacles: [1] });
  });
});
