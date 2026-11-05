import { describe, expect, it } from "vitest";
import { activePicks, facetViews, filterCatalog, groupCatalog, offeredFacets, picksFromStorage, togglePick, type CatalogModel, type CatalogValue } from "./catalogModel";

interface Boat {
  id: string;
  name: string;
  sizes: string[];
  gear: string[];
  fleet: string;
}

const value = (entry: string, rank?: number): CatalogValue => ({ value: entry, label: entry, rank });

const BOATS: Boat[] = [
  { id: "a", name: "Alpha tug", sizes: ["small"], gear: ["radar", "sonar"], fleet: "north" },
  { id: "b", name: "Bravo ferry", sizes: ["small", "large"], gear: ["radar"], fleet: "north" },
  { id: "c", name: "Charlie tanker", sizes: ["large"], gear: [], fleet: "north" },
];

const MODEL: CatalogModel<Boat> = {
  idOf: (boat) => boat.id,
  textOf: (boat) => boat.name,
  facets: [
    { key: "size", label: "Size", match: "any", values: (boat) => boat.sizes.map((size) => value(size, size === "small" ? 0 : 1)) },
    { key: "gear", label: "Gear", match: "all", values: (boat) => boat.gear.map((gear) => value(gear)) },
    { key: "fleet", label: "Fleet", match: "any", values: (boat) => [value(boat.fleet)] },
  ],
  groupings: [{ key: "size", label: "Size", groups: (boat) => boat.sizes.map((size) => value(size, size === "small" ? 0 : 1)) }],
};

const idsOf = (boats: readonly Boat[]) => boats.map((boat) => boat.id);

describe("filterCatalog", () => {
  it("keeps every item without filters or a search", () => {
    expect(idsOf(filterCatalog(BOATS, MODEL, {}, ""))).toEqual(["a", "b", "c"]);
  });

  it("keeps an item with one of the picked values of an any facet", () => {
    expect(idsOf(filterCatalog(BOATS, MODEL, { size: ["small"] }, ""))).toEqual(["a", "b"]);
    expect(idsOf(filterCatalog(BOATS, MODEL, { size: ["small", "large"] }, ""))).toEqual(["a", "b", "c"]);
  });

  it("keeps only an item with every picked value of an all facet", () => {
    expect(idsOf(filterCatalog(BOATS, MODEL, { gear: ["radar"] }, ""))).toEqual(["a", "b"]);
    expect(idsOf(filterCatalog(BOATS, MODEL, { gear: ["radar", "sonar"] }, ""))).toEqual(["a"]);
  });

  it("needs every facet to match", () => {
    expect(idsOf(filterCatalog(BOATS, MODEL, { size: ["large"], gear: ["radar"] }, ""))).toEqual(["b"]);
  });

  it("searches for every word, in any case and order", () => {
    expect(idsOf(filterCatalog(BOATS, MODEL, {}, "  TUG alpha "))).toEqual(["a"]);
    expect(filterCatalog(BOATS, MODEL, {}, "alpha ferry")).toEqual([]);
  });
});

describe("facetViews", () => {
  it("leaves out a facet that cannot narrow the catalog", () => {
    expect(offeredFacets(BOATS, MODEL).map((facet) => facet.key)).toEqual(["size", "gear"]);
    expect(facetViews(BOATS, MODEL, {}, "").map((facet) => facet.key)).toEqual(["size", "gear"]);
  });

  it("orders the values by rank, then by label", () => {
    expect(facetViews(BOATS, MODEL, {}, "")[0].options.map((option) => option.value)).toEqual(["small", "large"]);
    expect(facetViews(BOATS, MODEL, {}, "")[1].options.map((option) => option.value)).toEqual(["radar", "sonar"]);
  });

  it("counts an any facet's values against the other filters, not against its own", () => {
    const [size] = facetViews(BOATS, MODEL, { size: ["small"], gear: ["sonar"] }, "");
    expect(size.options.map((option) => [option.value, option.count, option.picked])).toEqual([
      ["small", 1, true],
      ["large", 0, false],
    ]);
    const [unfiltered] = facetViews(BOATS, MODEL, { size: ["small"] }, "");
    expect(unfiltered.options.map((option) => option.count)).toEqual([2, 2]);
  });

  it("counts an all facet's values together with what is already picked", () => {
    const gear = facetViews(BOATS, MODEL, { gear: ["sonar"] }, "")[1];
    expect(gear.options.map((option) => [option.value, option.count])).toEqual([
      ["radar", 1],
      ["sonar", 1],
    ]);
  });

  it("counts against the search", () => {
    const [size] = facetViews(BOATS, MODEL, {}, "tug");
    expect(size.options.map((option) => option.count)).toEqual([1, 0]);
  });
});

describe("activePicks", () => {
  it("drops a stored value no item has any more, and a facet no longer offered", () => {
    expect(activePicks(BOATS, MODEL, { size: ["small", "gone"], fleet: ["north"], unknown: ["x"] })).toEqual({ size: ["small"] });
  });

  it("drops a facet left without values", () => {
    expect(activePicks(BOATS, MODEL, { size: ["gone"] })).toEqual({});
  });
});

describe("groupCatalog", () => {
  it("lists an item under each of its groups, in the groups' order", () => {
    const groups = groupCatalog(BOATS, MODEL.groupings[0]);
    expect(groups.map((group) => [group.label, idsOf(group.items)])).toEqual([
      ["small", ["a", "b"]],
      ["large", ["b", "c"]],
    ]);
  });

  it("puts an item without a group under Other, last", () => {
    const groups = groupCatalog(BOATS, { key: "gear", label: "Gear", groups: (boat) => boat.gear.map((gear) => value(gear)) });
    expect(groups.map((group) => [group.label, idsOf(group.items)])).toEqual([
      ["radar", ["a", "b"]],
      ["sonar", ["a"]],
      ["Other", ["c"]],
    ]);
  });
});

describe("togglePick", () => {
  it("adds a value and removes it again, and leaves the other facets", () => {
    const picked = togglePick({ gear: ["radar"] }, "size", "small");
    expect(picked).toEqual({ gear: ["radar"], size: ["small"] });
    expect(togglePick(picked, "size", "small")).toEqual({ gear: ["radar"], size: [] });
  });
});

describe("picksFromStorage", () => {
  it("keeps string lists and treats anything else as nothing picked", () => {
    expect(picksFromStorage({ size: ["small", 1], gear: "radar" })).toEqual({ size: ["small"], gear: [] });
    expect(picksFromStorage(null)).toEqual({});
    expect(picksFromStorage(["small"])).toEqual({});
    expect(picksFromStorage("small")).toEqual({});
  });
});
