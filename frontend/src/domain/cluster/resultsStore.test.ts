import { beforeEach, describe, expect, it } from "vitest";
import { useClusterStore } from "./clusterStore";
import { DEFAULT_PAGE_SIZE, DEFAULT_VERDICT_FILTERS } from "./resultsApi";
import { selectShownEntry, useResultsStore } from "./resultsStore";

describe("results store", () => {
  beforeEach(() => {
    useResultsStore.getState().reset();
    useClusterStore.setState({ clusters: [{ id: "a", name: "A", operatorUrl: "http://a:5174" }, { id: "b", name: "B", operatorUrl: "http://b:5174" }], selectedClusterId: "a" });
  });

  it("starts with no campaign, the default filters and the first page", () => {
    expect(useResultsStore.getState()).toMatchObject({
      campaignId: null,
      caseId: null,
      filters: DEFAULT_VERDICT_FILTERS,
      page: 0,
      pageSize: DEFAULT_PAGE_SIZE,
      direction: "asc",
      sort: "fec_id",
    });
  });

  it("sorts by a column ascending, flips it when selected again and starts over on another column", () => {
    const store = useResultsStore.getState();
    store.setPage(3);
    store.sortBy("first_failure_time_s");
    expect(useResultsStore.getState()).toMatchObject({ sort: "first_failure_time_s", direction: "asc", page: 0 });
    store.setPage(2);
    store.sortBy("first_failure_time_s");
    expect(useResultsStore.getState()).toMatchObject({ sort: "first_failure_time_s", direction: "desc", page: 0 });
    store.sortBy("state");
    expect(useResultsStore.getState()).toMatchObject({ sort: "state", direction: "asc" });
    store.reset();
    expect(useResultsStore.getState()).toMatchObject({ sort: "fec_id", direction: "asc" });
  });

  it("opens a campaign with clean filters and the table shown", () => {
    const store = useResultsStore.getState();
    store.openCampaign("c1");
    store.setFilters({ state: "failed" });
    store.openCase("c1", 5);
    store.openCampaign("c2");
    expect(useResultsStore.getState()).toMatchObject({ campaignId: "c2", caseId: null, filters: DEFAULT_VERDICT_FILTERS, page: 0 });
  });

  it("shows the last executed step of an entry until a step is picked", () => {
    const store = useResultsStore.getState();
    store.openCampaign("c1");
    expect(useResultsStore.getState().step).toBeNull();
    store.setFilters({ state: "failed" });
    store.setStep("scene_generation");
    expect(useResultsStore.getState()).toMatchObject({ step: "scene_generation", caseId: null, filters: DEFAULT_VERDICT_FILTERS, page: 0 });
  });

  it("keeps the picked step for the same entry and drops it for another", () => {
    const store = useResultsStore.getState();
    store.openCampaign("c1", "trajectory_generation");
    store.openCase("c1", 5);
    expect(useResultsStore.getState()).toMatchObject({ step: "trajectory_generation", caseId: 5 });
    store.openCampaign("c1");
    expect(useResultsStore.getState()).toMatchObject({ step: "trajectory_generation", caseId: null });
    store.openCampaign("c2");
    expect(useResultsStore.getState().step).toBeNull();
    store.openCase("c3", 1, "simulation");
    expect(useResultsStore.getState()).toMatchObject({ campaignId: "c3", step: "simulation", caseId: 1 });
  });

  it("opens the same entry on another step", () => {
    const store = useResultsStore.getState();
    store.openCampaign("c1", "scene_generation");
    store.setFilters({ runIndex: 1 });
    store.openCampaign("c1", "simulation");
    expect(useResultsStore.getState()).toMatchObject({ step: "simulation", filters: DEFAULT_VERDICT_FILTERS });
  });

  it("keeps the filters when the same campaign is opened again from its table", () => {
    const store = useResultsStore.getState();
    store.openCampaign("c1");
    store.setFilters({ runIndex: 1 });
    store.openCampaign("c1");
    expect(useResultsStore.getState().filters.runIndex).toBe(1);
  });

  it("returns to the first page when a filter, the page size or the order changes", () => {
    const store = useResultsStore.getState();
    store.openCampaign("c1");
    store.setPage(3);
    store.setFilters({ classId: "a" });
    expect(useResultsStore.getState().page).toBe(0);
    store.setPage(2);
    store.setPageSize(100);
    expect(useResultsStore.getState()).toMatchObject({ page: 0, pageSize: 100 });
    store.setPage(2);
    store.setDirection("desc");
    expect(useResultsStore.getState()).toMatchObject({ page: 0, direction: "desc" });
    store.setPage(2);
    store.resetFilters();
    expect(useResultsStore.getState()).toMatchObject({ page: 0, filters: DEFAULT_VERDICT_FILTERS });
  });

  it("merges filter changes", () => {
    const store = useResultsStore.getState();
    store.setFilters({ state: "failed" });
    store.setFilters({ sensitive: "yes" });
    expect(useResultsStore.getState().filters).toEqual({ ...DEFAULT_VERDICT_FILTERS, state: "failed", sensitive: "yes" });
  });

  it("keeps the page inside the known total", () => {
    const store = useResultsStore.getState();
    store.setPage(9, 120);
    expect(useResultsStore.getState().page).toBe(2);
    store.setPage(-4, 120);
    expect(useResultsStore.getState().page).toBe(0);
    store.setPage(4);
    expect(useResultsStore.getState().page).toBe(4);
  });

  it("opens a case of the open campaign and goes back to the table", () => {
    const store = useResultsStore.getState();
    store.openCampaign("c1");
    store.setFilters({ state: "failed" });
    store.openCase("c1", 5);
    expect(useResultsStore.getState()).toMatchObject({ campaignId: "c1", caseId: 5 });
    expect(useResultsStore.getState().filters.state).toBe("failed");
    store.closeCase();
    expect(useResultsStore.getState().caseId).toBeNull();
    expect(useResultsStore.getState().filters.state).toBe("failed");
  });

  it("opens a case of another campaign with clean filters", () => {
    const store = useResultsStore.getState();
    store.openCampaign("c1");
    store.setFilters({ state: "failed" });
    store.openCase("c2", 7);
    expect(useResultsStore.getState()).toMatchObject({ campaignId: "c2", caseId: 7, filters: DEFAULT_VERDICT_FILTERS });
  });

  it("keeps the cluster an entry was opened on and shows it on that cluster only", () => {
    const store = useResultsStore.getState();
    store.openCampaign("c1");
    expect(useResultsStore.getState().clusterId).toBe("a");
    expect(selectShownEntry(useResultsStore.getState(), "a")).toBe("c1");
    expect(selectShownEntry(useResultsStore.getState(), "b")).toBeNull();
    // the same id on another cluster is another entry: it opens with clean filters
    store.setFilters({ state: "failed" });
    useClusterStore.setState({ selectedClusterId: "b" });
    store.openCase("c1", 2);
    expect(useResultsStore.getState()).toMatchObject({ clusterId: "b", campaignId: "c1", caseId: 2, filters: DEFAULT_VERDICT_FILTERS });
  });
});
