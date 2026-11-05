/**
 * The wizard's catalogs (the stacks and the campaign presets) as data: what an item can be filtered
 * and grouped by, and which items a search and the picked filters leave. `CatalogDialog.tsx` shows it;
 * `stackCatalog.ts` and `presetCatalog.ts` say what each catalog's items have.
 */

/** A value an item has under a facet or a grouping; `rank` orders the values, ties go by label. */
export interface CatalogValue {
  value: string;
  label: string;
  rank?: number;
}

export interface CatalogFacet<T> {
  key: string;
  label: string;
  /** The item's values: several when it has several (a preset with two stacks), none when it has none. */
  values: (item: T) => readonly CatalogValue[];
  /** With several values picked: "any" keeps an item with one of them, "all" only an item with every one. */
  match: "any" | "all";
}

export interface CatalogGrouping<T> {
  key: string;
  label: string;
  /** The groups the item is listed under; it shows in each of them. */
  groups: (item: T) => readonly CatalogValue[];
}

export interface CatalogModel<T> {
  idOf: (item: T) => string;
  /** What the search looks through. */
  textOf: (item: T) => string;
  facets: readonly CatalogFacet<T>[];
  /** The first one is the default. */
  groupings: readonly CatalogGrouping<T>[];
}

/** The picked values per facet key. */
export type CatalogPicks = Readonly<Record<string, readonly string[]>>;

export interface FacetOptionView extends CatalogValue {
  /** The items left if this value were picked, the other filters and the search kept. */
  count: number;
  picked: boolean;
}

export interface FacetView {
  key: string;
  label: string;
  match: "any" | "all";
  options: FacetOptionView[];
}

export interface CatalogGroup<T> {
  value: string;
  label: string;
  items: T[];
}

function byRank(a: CatalogValue, b: CatalogValue): number {
  return (a.rank ?? 0) - (b.rank ?? 0) || a.label.localeCompare(b.label, undefined, { numeric: true });
}

function distinctValues<T>(items: readonly T[], valuesOf: (item: T) => readonly CatalogValue[]): CatalogValue[] {
  const found = new Map<string, CatalogValue>();
  for (const item of items) {
    for (const entry of valuesOf(item)) {
      if (!found.has(entry.value)) {
        found.set(entry.value, entry);
      }
    }
  }
  return [...found.values()].sort(byRank);
}

function hasPicked<T>(item: T, facet: CatalogFacet<T>, picked: readonly string[]): boolean {
  if (picked.length === 0) {
    return true;
  }
  const has = new Set(facet.values(item).map((entry) => entry.value));
  return facet.match === "all" ? picked.every((value) => has.has(value)) : picked.some((value) => has.has(value));
}

/** Whether a facet can narrow the catalog: it is left out when every item has every one of its values. */
function narrows<T>(items: readonly T[], facet: CatalogFacet<T>): boolean {
  return distinctValues(items, facet.values).some((option) => items.some((item) => !facet.values(item).some((entry) => entry.value === option.value)));
}

/** The facets offered for these items. */
export function offeredFacets<T>(items: readonly T[], model: CatalogModel<T>): CatalogFacet<T>[] {
  return model.facets.filter((facet) => narrows(items, facet));
}

/**
 * The picks that still apply: stored ones outlive the catalog, so a value no item has any more, or
 * a facet no longer offered, must not hide items without a way to clear it.
 */
export function activePicks<T>(items: readonly T[], model: CatalogModel<T>, picks: CatalogPicks): CatalogPicks {
  const active: Record<string, readonly string[]> = {};
  for (const facet of offeredFacets(items, model)) {
    const known = new Set(distinctValues(items, facet.values).map((option) => option.value));
    const kept = (picks[facet.key] ?? []).filter((value) => known.has(value));
    if (kept.length > 0) {
      active[facet.key] = kept;
    }
  }
  return active;
}

function matchesSearch<T>(item: T, model: CatalogModel<T>, query: string): boolean {
  const text = model.textOf(item).toLowerCase();
  return query
    .toLowerCase()
    .split(/\s+/)
    .every((word) => text.includes(word));
}

/** The items the search and the picks leave; `picks` come from `activePicks`. */
export function filterCatalog<T>(items: readonly T[], model: CatalogModel<T>, picks: CatalogPicks, query: string): T[] {
  return items.filter((item) => matchesSearch(item, model, query) && model.facets.every((facet) => hasPicked(item, facet, picks[facet.key] ?? [])));
}

/** The offered facets with their values, each counted against the search and the other filters. */
export function facetViews<T>(items: readonly T[], model: CatalogModel<T>, picks: CatalogPicks, query: string): FacetView[] {
  return offeredFacets(items, model).map((facet) => {
    const others = filterCatalog(items, model, { ...picks, [facet.key]: [] }, query);
    const picked = picks[facet.key] ?? [];
    return {
      key: facet.key,
      label: facet.label,
      match: facet.match,
      options: distinctValues(items, facet.values).map((option) => ({
        ...option,
        count: others.filter((item) => hasPicked(item, facet, facet.match === "all" ? [...new Set([...picked, option.value])] : [option.value])).length,
        picked: picked.includes(option.value),
      })),
    };
  });
}

/** The items under each of the grouping's groups, in the groups' order; an item without a group goes under "Other". */
export function groupCatalog<T>(items: readonly T[], grouping: CatalogGrouping<T>): CatalogGroup<T>[] {
  const other: CatalogValue = { value: "", label: "Other", rank: Number.MAX_SAFE_INTEGER };
  const groupsOf = (item: T) => (grouping.groups(item).length > 0 ? grouping.groups(item) : [other]);
  return distinctValues(items, groupsOf).map(({ value, label }) => ({
    value,
    label,
    items: items.filter((item) => groupsOf(item).some((entry) => entry.value === value)),
  }));
}

/** The picks with a facet's value switched. */
export function togglePick(picks: CatalogPicks, key: string, value: string): CatalogPicks {
  const picked = picks[key] ?? [];
  return { ...picks, [key]: picked.includes(value) ? picked.filter((entry) => entry !== value) : [...picked, value] };
}

/** Stored picks as they must be: anything else in the browser's storage counts as nothing picked. */
export function picksFromStorage(stored: unknown): CatalogPicks {
  if (typeof stored !== "object" || stored === null || Array.isArray(stored)) {
    return {};
  }
  const entries = Object.entries(stored).map(([key, values]) => [key, Array.isArray(values) ? values.filter((value) => typeof value === "string") : []]);
  return Object.fromEntries(entries) as CatalogPicks;
}
