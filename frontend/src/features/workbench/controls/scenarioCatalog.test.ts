import { describe, expect, it } from "vitest";
import type { CatalogClass } from "../../../domain/cluster/campaignApi";
import { ANY_COUNT, countOptions, filterCatalogClasses } from "./scenarioCatalog";

function catalogClass(classId: string, vessels: number, obstacles: number): CatalogClass {
  return { class_id: classId, folder: classId.split("/")[0], vessel_count: vessels, obstacle_count: obstacles, content_hash: "a".repeat(64) };
}

const classes = [
  catalogClass("2vessel_0obstacle_scenarios/functional_model0", 2, 0),
  catalogClass("3vessel_1obstacle_scenarios/functional_model1", 3, 1),
  catalogClass("3vessel_0obstacle_scenarios/functional_model10", 3, 0),
];

describe("filterCatalogClasses", () => {
  it("filters by vessel and obstacle count", () => {
    expect(filterCatalogClasses(classes, "", "3", "0").map((entry) => entry.class_id)).toEqual(["3vessel_0obstacle_scenarios/functional_model10"]);
    expect(filterCatalogClasses(classes, "", "3", ANY_COUNT)).toHaveLength(2);
  });

  it("finds a text in the class id, ignoring case", () => {
    expect(filterCatalogClasses(classes, " Model1", ANY_COUNT, ANY_COUNT).map((entry) => entry.class_id)).toEqual([
      "3vessel_1obstacle_scenarios/functional_model1",
      "3vessel_0obstacle_scenarios/functional_model10",
    ]);
    expect(filterCatalogClasses(classes, "", ANY_COUNT, ANY_COUNT)).toEqual(classes);
  });
});

describe("countOptions", () => {
  it("lists every count once, ascending", () => {
    expect(countOptions(classes, "vessel_count")).toEqual([2, 3]);
    expect(countOptions(classes, "obstacle_count")).toEqual([0, 1]);
    expect(countOptions([], "vessel_count")).toEqual([]);
  });
});
