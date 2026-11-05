import { describe, expect, it } from "vitest";
import type { CatalogClass } from "../../../domain/cluster/campaignApi";
import { ANY_COUNT, countOptions, filterCatalogClasses, hiddenSelections, listedValue, selectListed } from "./scenarioCatalog";

function catalogClass(classId: string, vessels: number, obstacles: number): CatalogClass {
  return { fec_id: classId, folder: classId.split("/")[0], vessel_count: vessels, obstacle_count: obstacles, content_hash: "a".repeat(64) };
}

const classes = [
  catalogClass("2vessel_0obstacle_scenarios/fec0", 2, 0),
  catalogClass("3vessel_1obstacle_scenarios/fec1", 3, 1),
  catalogClass("3vessel_0obstacle_scenarios/fec10", 3, 0),
];

describe("filterCatalogClasses", () => {
  it("filters by vessel and obstacle count", () => {
    expect(filterCatalogClasses(classes, "", "3", "0").map((entry) => entry.fec_id)).toEqual(["3vessel_0obstacle_scenarios/fec10"]);
    expect(filterCatalogClasses(classes, "", "3", ANY_COUNT)).toHaveLength(2);
  });

  it("finds a text in the class id, ignoring case", () => {
    expect(filterCatalogClasses(classes, " FEC1", ANY_COUNT, ANY_COUNT).map((entry) => entry.fec_id)).toEqual([
      "3vessel_1obstacle_scenarios/fec1",
      "3vessel_0obstacle_scenarios/fec10",
    ]);
    expect(filterCatalogClasses(classes, "", ANY_COUNT, ANY_COUNT)).toEqual(classes);
  });
});

describe("listedValue", () => {
  const oneVessel = [catalogClass("1vessel_0obstacle_scenarios/fec0", 1, 0)];

  it("shows the loaded scenario only while it is listed", () => {
    expect(listedValue(classes, "3vessel_1obstacle_scenarios/fec1")).toBe("3vessel_1obstacle_scenarios/fec1");
    expect(listedValue(classes, null)).toBe("");
  });

  it("shows the placeholder over a list of one scenario that is not loaded, so picking it loads it", () => {
    expect(listedValue(oneVessel, "2vessel_0obstacle_scenarios/fec0")).toBe("");
    expect(listedValue(oneVessel, "1vessel_0obstacle_scenarios/fec0 (edited)")).toBe("");
    expect(listedValue(oneVessel, "head_on.problem")).toBe("");
  });
});

describe("batch selection", () => {
  it("adds the listed classes to the selection and keeps the hidden ones", () => {
    const listed = classes.slice(1);
    expect(selectListed(["other/fec9", classes[1].fec_id], listed)).toEqual([
      "other/fec9",
      "3vessel_1obstacle_scenarios/fec1",
      "3vessel_0obstacle_scenarios/fec10",
    ]);
  });

  it("counts the selected classes the filters hide", () => {
    expect(hiddenSelections(["other/fec9", classes[0].fec_id], classes)).toBe(1);
    expect(hiddenSelections([], classes)).toBe(0);
  });
});

describe("countOptions", () => {
  it("lists every count once, ascending", () => {
    expect(countOptions(classes, "vessel_count")).toEqual([2, 3]);
    expect(countOptions(classes, "obstacle_count")).toEqual([0, 1]);
    expect(countOptions([], "vessel_count")).toEqual([]);
  });
});
