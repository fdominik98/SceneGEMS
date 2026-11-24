import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useUiStore } from "../../app/uiStore";
import { resetLiveChannels } from "../../domain/cluster/liveChannels";
import { useResultsStore } from "../../domain/cluster/resultsStore";
import { sampleCampaignDetail, sampleCase, sampleClass } from "../../test/fixtures/clusterViews";
import {
  sampleCampaignRow,
  sampleHistoryRows,
  sampleMonitorVerdict,
  sampleRunningWorkbenchRow,
  sampleSimulationOutput,
  sampleTrajectoryOutput,
  sampleWorkbenchRow,
} from "../../test/fixtures/historyViews";
import { sampleCatalogStacks } from "../../test/fixtures/campaignCatalog";
import { MockWebSocket } from "../../test/mockWebSocket";
import { useWizardStore } from "../campaigns/wizard/wizardState";
import { useWorkbenchTargetStore } from "../workbench/pages/workbenchTarget";
import { HistorySection } from "./HistorySection";
import { INITIAL_LIST_VIEW } from "./campaignModel";
import { useHistoryStore } from "./historyStore";

// Campaign History against a fake operator API (fetch) and a fake live channel socket.

interface Call {
  method: string;
  path: string;
  query: URLSearchParams;
}

let calls: Call[] = [];
let deleteStatus = 204;
let outputs: Record<string, unknown>[] = [];
/** The cases the cases route lists by state. */
let failedCases: Record<string, unknown>[] = [];
let droppedCases: Record<string, unknown>[] = [];
/** What the detail route answers differently from the sample detail. */
let detailOverride: Record<string, unknown> = {};
/** What the config route answers; null answers 404. */
let entryConfig: Record<string, unknown> | null = null;
/** Whether the control node answers its stack catalog (it answers 404 otherwise). */
let stacksServed = true;

const CLUSTER_DOMAIN = { colregs_constants: "A: 1\n", vessel_types: "Ferry: {}\n", obstacle_types: "Buoy: {}\n" };

/** The config of the campaign c1 as the control node stores it: every default filled in, the cluster's domain contents written in. */
const STORED_CAMPAIGN_CONFIG = {
  format: 3,
  name: "head-on sweep",
  description: "",
  steps: ["scene_generation", "trajectory_generation"],
  scope: [{ fecs: ["2vessel_0obstacle_scenarios/fec1"], patterns: [], quota: 5, failure_budget: 1 }],
  input: { functional_scenarios: [], items: [] },
  domain: { ...CLUSTER_DOMAIN, scene_generation_timeout_s: 90, enforce_low_tcpa: false },
  scene_generation: { monitor: "post_hoc" },
  trajectories: { generator: "straight", params: {}, timespan_s: 600.0, timeout_s: 1800.0, monitor: "post_hoc" },
  resources: { worker_nodes: [], required_labels: {}, queue_depth: { generate_scene: 16, generate_trajectories: 16, simulate: 32, monitor: 32, calibrate: 8 }, priority: 0 },
  policy: { retention: "all", keep_frames: false, seed: 7, stop: { max_cases: null, max_failed_verdicts: null, max_duration_s: null } },
};

function json(body: unknown, total?: number, status = 200): Response {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (total !== undefined) {
    headers["X-Total-Count"] = String(total);
  }
  return new Response(JSON.stringify(body), { status, headers });
}

function detailOf(row: Record<string, unknown>): Record<string, unknown> {
  const detail = sampleCampaignDetail();
  return { ...row, totals: detail.totals, fecs: row.kind === "campaign" ? detail.fecs : [], ...detailOverride };
}

async function fakeFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const url = new URL(String(input));
  const method = init?.method ?? "GET";
  calls.push({ method, path: url.pathname, query: url.searchParams });
  const parts = url.pathname.split("/").filter(Boolean);
  if (url.pathname === "/cluster/campaigns" && method === "GET") {
    return json(sampleHistoryRows, sampleHistoryRows.length);
  }
  if (parts[0] === "cluster" && parts[1] === "campaigns" && parts.length === 3) {
    if (method === "DELETE") {
      return deleteStatus === 204 ? new Response(null, { status: 204 }) : json({ detail: "campaign wb1 is running" }, undefined, deleteStatus);
    }
    const row = sampleHistoryRows.find((entry) => entry.campaign_id === parts[2]);
    return row ? json(detailOf(row)) : json({ detail: "no such campaign" }, undefined, 404);
  }
  if (parts[3] === "outputs") {
    return json(outputs, outputs.length);
  }
  if (parts[3] === "cases" && parts.length === 4) {
    const listed = url.searchParams.get("state") === "failed" ? failedCases : url.searchParams.get("state") === "dropped" ? droppedCases : [];
    return json(listed, listed.length);
  }
  if (parts[3] === "config" && entryConfig !== null) {
    return json({ current_version: 1, versions: [{ version: 1, config_hash: "a", created_at: "2026-10-28T10:00:00+00:00", config: entryConfig }] });
  }
  if (url.pathname === "/cluster/catalog/stacks" && stacksServed) {
    return json(sampleCatalogStacks);
  }
  if (url.pathname === "/cluster/domain") {
    return json({ ...CLUSTER_DOMAIN, saved: true, updated_at: null, editable: true });
  }
  if (parts[3] === "events" || url.pathname === "/cluster/worker-nodes") {
    return json([], 0);
  }
  return json({ detail: "not found" }, undefined, 404);
}

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <HistorySection />
    </QueryClientProvider>
  );
}

/** Opens the fake socket and answers the `campaigns` subscription with its empty snapshot. */
async function goLive(): Promise<MockWebSocket> {
  await waitFor(() => expect(MockWebSocket.instances.length).toBeGreaterThan(0));
  const socket = MockWebSocket.latest();
  act(() => socket.open());
  await waitFor(() => expect(socket.sentOfType("subscribe").some((message) => message.topic === "campaigns")).toBe(true));
  act(() => socket.receive({ type: "subscribed", topic: "campaigns", snapshot: {} }));
  return socket;
}

beforeEach(() => {
  calls = [];
  deleteStatus = 204;
  outputs = [sampleTrajectoryOutput()];
  failedCases = [];
  droppedCases = [];
  detailOverride = {};
  entryConfig = null;
  stacksServed = true;
  useWizardStore.getState().reset();
  MockWebSocket.reset();
  resetLiveChannels({ createSocket: MockWebSocket.factory });
  vi.stubGlobal("fetch", vi.fn(fakeFetch));
  useHistoryStore.setState({ clusterId: null, entryId: null, step: null, listView: INITIAL_LIST_VIEW });
  useWorkbenchTargetStore.setState({ pending: {} });
  useUiStore.getState().setSection("history");
});

afterEach(() => {
  resetLiveChannels();
  vi.unstubAllGlobals();
});

describe("Campaign History in the DOM", () => {
  it("lists entries with kind, origin, steps, made-from links and totals, and follows the campaigns topic", async () => {
    renderSection();
    const campaignRow = (await screen.findByRole("button", { name: "head-on sweep" })).closest("tr") as HTMLElement;
    expect(within(campaignRow).getByText("Campaign")).toBeInTheDocument();
    expect(within(campaignRow).getByText("from the wizard")).toBeInTheDocument();
    // The steps as the stretch of the chain they cover; the full list is the cell's tooltip
    expect(within(campaignRow).getByText("Scene generation to trajectory generation")).toHaveAttribute("title", "Scene generation, trajectory generation");
    // An entry that starts from its own input does not say so
    expect(within(campaignRow).queryByText(/its own input|made from/)).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Made from" })).not.toBeInTheDocument();
    expect(within(campaignRow).getByText("5 complete, 4 active, 1 dropped")).toBeInTheDocument();
    const workbenchRow = screen.getByRole("button", { name: "Trajectory generation" }).closest("tr") as HTMLElement;
    expect(within(workbenchRow).getByText("Workbench run")).toBeInTheDocument();
    // wb1 is made from c1, whose name is on the page
    expect(within(workbenchRow).getByRole("button", { name: "Made from head-on sweep" })).toBeInTheDocument();

    const socket = await goLive();
    expect(screen.getByText("live")).toBeInTheDocument();
    const listReads = calls.filter((call) => call.path === "/cluster/campaigns").length;
    act(() =>
      socket.receive({ type: "update", topic: "campaigns", seq: 1, data: { campaign: sampleRunningWorkbenchRow({ actual_state: "stalled", updated_at: "2030-01-01T00:00:00+00:00" }) } })
    );
    const simulationRow = screen.getByRole("button", { name: "Simulation" }).closest("tr") as HTMLElement;
    expect(within(simulationRow).getByText("Stalled")).toBeInTheDocument();
    // A row on the page changes in place; a new entry has the page read again
    expect(calls.filter((call) => call.path === "/cluster/campaigns")).toHaveLength(listReads);
    act(() => socket.receive({ type: "update", topic: "campaigns", seq: 2, data: { campaign: sampleWorkbenchRow({ campaign_id: "wb9", name: "Scene generation" }) } }));
    await waitFor(() => expect(calls.filter((call) => call.path === "/cluster/campaigns").length).toBeGreaterThan(listReads));
  });

  it("reads the page again when the campaigns topic starts over from a new snapshot", async () => {
    renderSection();
    await screen.findByRole("button", { name: "head-on sweep" });
    const socket = await goLive();
    const listReads = () => calls.filter((call) => call.path === "/cluster/campaigns").length;
    act(() => socket.receive({ type: "update", topic: "campaigns", seq: 1, data: { campaign: sampleRunningWorkbenchRow({ actual_state: "stalled" }) } }));
    await waitFor(() => expect(screen.getAllByText("Stalled").length).toBeGreaterThan(0));
    const before = listReads();
    // A gap in seq: the channel subscribes again and the snapshot drops the pushed rows
    act(() => socket.receive({ type: "update", topic: "campaigns", seq: 5, data: { campaign: sampleRunningWorkbenchRow({ actual_state: "paused" }) } }));
    act(() => socket.receive({ type: "subscribed", topic: "campaigns", snapshot: {} }));
    await waitFor(() => expect(listReads()).toBeGreaterThan(before));
  });

  it("filters by kind through the route and by step on the page", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByRole("button", { name: "head-on sweep" });
    await user.click(screen.getByRole("button", { name: "Workbench runs" }));
    await waitFor(() => expect(calls.some((call) => call.path === "/cluster/campaigns" && call.query.get("kind") === "workbench")).toBe(true));
    await user.click(screen.getByRole("group", { name: "Filter by kind" }).querySelector("button") as HTMLElement);
    await user.selectOptions(screen.getByLabelText("Step"), "scene_generation");
    await waitFor(() => expect(screen.queryByRole("button", { name: "Simulation" })).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "head-on sweep" })).toBeInTheDocument();
  });

  it("comes back from an entry to the list with its filters", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByRole("button", { name: "head-on sweep" });
    await user.click(screen.getByRole("button", { name: "Workbench runs" }));
    await user.type(screen.getByRole("searchbox", { name: /name/i }), "traj");
    await waitFor(() => expect(useHistoryStore.getState().listView).toMatchObject({ kind: "workbench", q: "traj" }));
    await user.click(await screen.findByRole("button", { name: "Trajectory generation" }));
    await user.click(await screen.findByRole("button", { name: "Back to the history" }));
    expect(await screen.findByRole("searchbox", { name: /name/i })).toHaveValue("traj");
    expect(screen.getByRole("button", { name: "Workbench runs" })).toHaveAttribute("aria-pressed", "true");
  });

  it("opens an entry with a tab per executed step and opens an output on its workbench page", async () => {
    const user = userEvent.setup();
    renderSection();
    await user.click(await screen.findByRole("button", { name: "Trajectory generation" }));
    expect(await screen.findByRole("heading", { name: "Trajectory generation", level: 3 })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Trajectory generation" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getAllByRole("tab")).toHaveLength(1);
    // The name of the entry it was made from is known from the list
    expect(screen.getByRole("button", { name: "Made from head-on sweep" })).toBeInTheDocument();
    // Who made the entry is a detail: it is there on request
    expect(screen.queryByText("the trajectory generation page")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Entry details/ }));
    expect(screen.getByText("the trajectory generation page")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Hide entry details/ }));
    // A workbench entry has no campaign controls
    expect(screen.queryByRole("region", { name: "Campaign controls" })).not.toBeInTheDocument();

    const output = (await screen.findByText("incomplete")).closest("tr") as HTMLElement;
    expect(within(output).getByText("failed")).toBeInTheDocument();
    expect(within(output).getByText("rule_15")).toBeInTheDocument();
    await user.click(within(output).getByRole("button", { name: "Open in workbench" }));
    expect(useWorkbenchTargetStore.getState().pending.trajectoryGeneration).toEqual({ page: "trajectoryGeneration", campaignId: "wb1", caseId: 6, step: "trajectory_generation" });
    expect(useUiStore.getState().section).toBe("workbench");
  });

  it("shows the monitor result summary: passed or failed, scenario types, roles of the vessels and failed rules", async () => {
    const user = userEvent.setup();
    outputs = [sampleTrajectoryOutput({ verdict: sampleMonitorVerdict() })];
    entryConfig = { trajectories: { monitor: "post_hoc" } };
    renderSection();
    await user.click(await screen.findByRole("button", { name: "Trajectory generation" }));
    expect(await screen.findByRole("columnheader", { name: "Monitor result summary" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: /verdict/i })).not.toBeInTheDocument();
    const output = (await screen.findByText("incomplete")).closest("tr") as HTMLElement;
    expect(within(output).getByText("failed")).toBeInTheDocument();
    expect(within(output).getByText("2 rules failed, first at 1 min 1 s")).toBeInTheDocument();

    const crossing = within(output).getByText("os - ts1").parentElement as HTMLElement;
    expect(within(crossing).getByText("Crossing from Port")).toBeInTheDocument();
    expect(within(crossing).getByText("ts1 give-way")).toHaveAttribute("title", "ts1 is the give-way vessel");
    expect(within(crossing).getByText("os stand-on")).toBeInTheDocument();
    expect(within(crossing).getByText("Rule 16: Give-Way Vessel Takes Early and Substantial Action (ts1)")).toBeInTheDocument();

    const headOn = within(output).getByText("os - ts2").parentElement as HTMLElement;
    expect(within(headOn).getByText("Head-On")).toBeInTheDocument();
    expect(within(headOn).getByText("os give-way")).toBeInTheDocument();
    expect(within(headOn).getByText("ts2 give-way")).toBeInTheDocument();

    expect(within(output).getByText("Rule 8: Readily Apparent Course Change (os)")).toBeInTheDocument();
    expect(within(output).getByText("1 pair without an encounter")).toBeInTheDocument();
    expect(within(output).queryByText("os - ts10")).not.toBeInTheDocument();
  });

  it("cuts a long list of failed rules short, and says when the roles were not recorded", async () => {
    const user = userEvent.setup();
    const rules = ["a", "b", "c", "d", "e"].map((name) => `os - ts1: Rule ${name}`);
    outputs = [sampleTrajectoryOutput({ verdict: sampleMonitorVerdict({ failed_rules: rules, encounter_roles: null }) })];
    renderSection();
    await user.click(await screen.findByRole("button", { name: "Trajectory generation" }));
    const output = (await screen.findByText("incomplete")).closest("tr") as HTMLElement;
    expect(within(output).getByText("Rule c")).toBeInTheDocument();
    expect(within(output).queryByText("Rule d")).not.toBeInTheDocument();
    expect(within(output).getByText("and 2 more")).toHaveAttribute("title", "Rule d\nRule e");
    expect(within(output).getAllByText("roles not recorded")).toHaveLength(2);
  });

  it("leaves the monitor result summary out of a step without a monitor", async () => {
    const user = userEvent.setup();
    outputs = [sampleTrajectoryOutput({ verdict: null })];
    entryConfig = { trajectories: { monitor: "empty" } };
    renderSection();
    await user.click(await screen.findByRole("button", { name: "Trajectory generation" }));
    await waitFor(() => expect(calls.some((call) => call.path === "/cluster/campaigns/wb1/config")).toBe(true));
    expect(await screen.findByText("incomplete")).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Monitor result summary" })).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Input from" })).toBeInTheDocument();
  });

  it("says a case of a monitored step has no monitor result summary yet", async () => {
    const user = userEvent.setup();
    outputs = [sampleTrajectoryOutput({ state: "active", verdict: null })];
    entryConfig = { trajectories: { monitor: "post_hoc" } };
    renderSection();
    await user.click(await screen.findByRole("button", { name: "Trajectory generation" }));
    expect(await screen.findByText("no monitor result summary yet")).toBeInTheDocument();
  });

  it("deletes a final entry after a confirmation, and says to stop one the control node refuses", async () => {
    const user = userEvent.setup();
    renderSection();
    const running = (await screen.findByRole("button", { name: "Simulation" })).closest("tr") as HTMLElement;
    expect(within(running).getByRole("button", { name: "Delete" })).toBeDisabled();

    const finished = screen.getByRole("button", { name: "Trajectory generation" }).closest("tr") as HTMLElement;
    deleteStatus = 409;
    await user.click(within(finished).getByRole("button", { name: "Delete" }));
    expect(within(finished).getByRole("alertdialog", { name: "Delete Trajectory generation" })).toBeInTheDocument();
    await user.click(within(finished).getByRole("button", { name: "Delete the entry" }));
    expect(await within(finished).findByRole("alert")).toHaveTextContent("Stop it first");

    deleteStatus = 204;
    await user.click(within(finished).getByRole("button", { name: "Delete" }));
    await user.click(within(finished).getByRole("button", { name: "Delete the entry" }));
    await waitFor(() => expect(calls.filter((call) => call.method === "DELETE" && call.path === "/cluster/campaigns/wb1")).toHaveLength(2));
  });

  it("leaves out the column of the input's source when no output names one", async () => {
    const user = userEvent.setup();
    outputs = [sampleTrajectoryOutput({ input_source: null })];
    renderSection();
    await user.click(await screen.findByRole("button", { name: "Trajectory generation" }));
    expect(await screen.findByText("incomplete")).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Input from" })).not.toBeInTheDocument();
    // What every output has says nothing: only the flag of what is off is shown
    expect(screen.queryByText("valid")).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Output" })).not.toBeInTheDocument();
  });

  it("folds the identical repeats of a run into one line, each still opening on the workbench", async () => {
    const user = userEvent.setup();
    const repeat = (index: number) => sampleSimulationOutput({ repeat_index: index, run_record_id: 30 + index, verdict: sampleMonitorVerdict() });
    outputs = [repeat(0), repeat(1), repeat(2)];
    renderSection();
    await user.click(await screen.findByRole("button", { name: "Simulation" }));
    const line = (await screen.findByText("run 1, 3 identical repeats")).closest("tr") as HTMLElement;
    expect(screen.getAllByRole("row")).toHaveLength(2);
    expect(screen.getByText(/1 to 3 of 3 runs, identical repeats on one line/)).toBeInTheDocument();
    await user.click(within(line).getByRole("button", { name: "Open repeat 3 in the workbench" }));
    expect(useWorkbenchTargetStore.getState().pending.simulation).toMatchObject({ campaignId: "wb2", caseId: 7, runRecordId: 32 });
    act(() => useUiStore.getState().setSection("history"));
    await user.click(within((await screen.findByText("run 1, 3 identical repeats")).closest("tr") as HTMLElement).getByRole("button", { name: "Open in workbench" }));
    expect(useWorkbenchTargetStore.getState().pending.simulation).toMatchObject({ runRecordId: 30 });
  });

  it("shows the summary of the judged repeat on a folded line, and says where a later repeat on its own was judged", async () => {
    const user = userEvent.setup();
    const other = "9".repeat(64);
    outputs = [
      // The control node gives the run's summary to the repeat it judged, the first
      sampleSimulationOutput({ repeat_index: 0, run_record_id: 30, verdict: sampleMonitorVerdict() }),
      sampleSimulationOutput({ repeat_index: 1, run_record_id: 31, verdict: null }),
      // A repeat with another state log keeps its own line
      sampleSimulationOutput({ repeat_index: 2, run_record_id: 32, verdict: null, artifact: { sha256: other, size_bytes: 10, kind: "trajectories", media_type: "application/json", pointer: null } }),
    ];
    renderSection();
    await user.click(await screen.findByRole("button", { name: "Simulation" }));
    const folded = (await screen.findByText("run 1, 2 identical repeats")).closest("tr") as HTMLElement;
    expect(within(folded).getByText("2 rules failed, first at 1 min 1 s")).toBeInTheDocument();
    const alone = screen.getByText("run 1, repeat 3").closest("tr") as HTMLElement;
    expect(within(alone).getByText("judged on repeat 1 of the run")).toBeInTheDocument();
    expect(within(alone).queryByText(/no monitor result summary/)).not.toBeInTheDocument();
  });

  it("says why cases did not complete, the most frequent reason first", async () => {
    const user = userEvent.setup();
    const JOB = "69c13761-fcca-4d38-b1ff-9696bbc441f4";
    failedCases = [
      { ...sampleCase, case_id: 21, state: "failed", stage: "simulate", reason: `simulate:0:0 job ${JOB} failed: pHelmIvP did not acknowledge the tick` },
      { ...sampleCase, case_id: 22, state: "failed", stage: "simulate", reason: "simulate:0:1 job e67af559-5178-4024-ad10-eb559e9f57d5 failed: pHelmIvP did not acknowledge the tick" },
    ];
    droppedCases = [{ ...sampleCase, case_id: 23, state: "dropped", stage: "generate_scene", reason: "the scene generation found no valid scene" }];
    renderSection();
    await user.click(await screen.findByRole("button", { name: "head-on sweep" }));
    const panel = await screen.findByRole("region", { name: "Why cases did not complete" });
    const reasons = await within(panel).findAllByRole("listitem");
    expect(reasons).toHaveLength(2);
    expect(reasons[0]).toHaveTextContent("2 failed");
    expect(reasons[0]).toHaveTextContent("in simulation");
    expect(reasons[0]).toHaveTextContent("pHelmIvP did not acknowledge the tick");
    expect(reasons[0]).not.toHaveTextContent(JOB);
    expect(reasons[1]).toHaveTextContent("1 dropped");
    expect(reasons[1]).toHaveTextContent("in scene generation");
    expect(calls.filter((call) => call.path === "/cluster/campaigns/c1/cases").map((call) => call.query.get("state")).sort()).toEqual(["dropped", "failed"]);
    // A case of the reason opens in Results, where its jobs and their errors are
    await user.click(within(reasons[0]).getByRole("button", { name: "Open a case" }));
    expect(useUiStore.getState().section).toBe("results");
    expect(useResultsStore.getState()).toMatchObject({ campaignId: "c1", caseId: 21 });
  });

  it("says that an entry which is still exploring has no cases to count yet", async () => {
    const user = userEvent.setup();
    outputs = [];
    // The control node counts the scenarios' FECs and cases: while the exploration runs there are none
    detailOverride = {
      steps: ["design_space_exploration", "scene_generation"],
      totals: { fecs: 0, fecs_open: 0, fecs_complete: 0, fecs_abandoned: 0, quota: 0, complete: 0, dropped: 0, in_flight: 0, verdicts: {} },
      fecs: [sampleClass({ fec_id: "exploration", quota: 1, complete: 0, dropped: 0, in_flight: 1, vessel_count: 0, verdicts: {} })],
    };
    renderSection();
    await user.click(await screen.findByRole("button", { name: "head-on sweep" }));
    expect(await screen.findByText("The design space exploration is finding the FECs; their cases follow.")).toBeInTheDocument();
    expect(screen.queryByText(/0 in flight/)).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Why cases did not complete" })).not.toBeInTheDocument();
  });

  it("offers a running campaign the controls that apply to it, and a finished one none", async () => {
    const user = userEvent.setup();
    renderSection();
    await user.click(await screen.findByRole("button", { name: "head-on sweep" }));
    const controls = await screen.findByRole("region", { name: "Campaign controls" });
    expect(within(controls).getAllByRole("button").map((button) => button.textContent?.replace(/Holds.*|Lets.*|Ends.*/, "")).slice(0, 3)).toEqual(["Pause", "Drain", "Stop"]);
    expect(within(controls).queryByRole("button", { name: /^Start/ })).not.toBeInTheDocument();
    expect(within(controls).queryByRole("button", { name: /^Resume/ })).not.toBeInTheDocument();
  });

  it("opens the campaign controls and the coverage for a campaign", async () => {
    const user = userEvent.setup();
    renderSection();
    await user.click(await screen.findByRole("button", { name: "head-on sweep" }));
    expect(await screen.findByRole("region", { name: "Campaign controls" })).toBeInTheDocument();
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["Scene generation", "Trajectory generation"]);
    await user.click(screen.getByRole("tab", { name: "Scene generation" }));
    expect(useHistoryStore.getState().step).toBe("scene_generation");
    expect(sampleCampaignRow().campaign_id).toBe("c1");
  });
});

describe("loading a campaign's config into the wizard", () => {
  const loadButton = () => screen.findByRole("button", { name: "Load the config into the wizard" });

  it("puts the config into the wizard as a draft and opens the Campaigns section", async () => {
    const user = userEvent.setup();
    entryConfig = STORED_CAMPAIGN_CONFIG;
    renderSection();
    await user.click(await screen.findByRole("button", { name: "head-on sweep" }));
    await waitFor(async () => expect(await loadButton()).toBeEnabled());
    await user.click(await loadButton());

    expect(useUiStore.getState().section).toBe("campaigns");
    const { draft, step, notice } = useWizardStore.getState();
    expect(step).toBe("steps");
    expect(notice).toBe('Started from the config of "head-on sweep" (version 1). Adjust it, then create the campaign.');
    expect(draft).toMatchObject({
      name: "head-on sweep",
      steps: ["scene_generation", "trajectory_generation"],
      sceneMonitor: "post_hoc",
      trajectoryMonitor: "post_hoc",
      scope: [{ classes: ["2vessel_0obstacle_scenarios/fec1"], quota: 5, failureBudget: 1 }],
      // The stored contents are the cluster's domain configuration: the draft uses the cluster's
      domain: { custom: false, sceneGenerationTimeoutS: 90 },
      trajectories: { generator: "straight", parameters: { timespan_s: 600 } },
      policy: { seed: 7 },
    });
    // The wizard has no allocation settings: a campaign made in it uses every machine
    expect(Object.keys(draft)).not.toContain("resources");
  });

  it("says what a loaded config named about its machines, which the wizard does not take over", async () => {
    const user = userEvent.setup();
    entryConfig = { ...STORED_CAMPAIGN_CONFIG, resources: { ...STORED_CAMPAIGN_CONFIG.resources, worker_nodes: ["worker-node-2"], priority: 5 } };
    renderSection();
    await user.click(await screen.findByRole("button", { name: "head-on sweep" }));
    await waitFor(async () => expect(await loadButton()).toBeEnabled());
    await user.click(await loadButton());
    expect(useWizardStore.getState().notice).toBe(
      'Started from the config of "head-on sweep" (version 1). It named one chosen machine, priority 5; a campaign made here uses every machine automatically. Adjust it, then create the campaign.'
    );
  });

  it("loads the version shown in the config panel", async () => {
    const user = userEvent.setup();
    entryConfig = STORED_CAMPAIGN_CONFIG;
    renderSection();
    await user.click(await screen.findByRole("button", { name: "head-on sweep" }));
    const inPanel = await screen.findByRole("button", { name: "Load version 1 into the wizard" });
    await waitFor(() => expect(inPanel).toBeEnabled());
    await user.click(inPanel);
    expect(useWizardStore.getState().draft.name).toBe("head-on sweep");
    expect(useUiStore.getState().section).toBe("campaigns");
  });

  it("asks before it replaces a draft that holds entries, and leaves it when the operator declines", async () => {
    const user = userEvent.setup();
    entryConfig = STORED_CAMPAIGN_CONFIG;
    useWizardStore.getState().update((draft) => {
      draft.name = "half done";
    });
    const confirm = vi.fn(() => false);
    vi.stubGlobal("confirm", confirm);
    renderSection();
    await user.click(await screen.findByRole("button", { name: "head-on sweep" }));
    await waitFor(async () => expect(await loadButton()).toBeEnabled());
    await user.click(await loadButton());
    expect(confirm).toHaveBeenCalledWith('Replace the draft in the wizard with the config of "head-on sweep"?');
    expect(useWizardStore.getState().draft.name).toBe("half done");
    expect(useUiStore.getState().section).toBe("history");

    confirm.mockReturnValue(true);
    await user.click(await loadButton());
    expect(useWizardStore.getState().draft.name).toBe("head-on sweep");
    expect(useUiStore.getState().section).toBe("campaigns");
  });

  it("waits for the control node's stacks, and says so when they cannot be read", async () => {
    const user = userEvent.setup();
    entryConfig = STORED_CAMPAIGN_CONFIG;
    stacksServed = false;
    renderSection();
    await user.click(await screen.findByRole("button", { name: "head-on sweep" }));
    const button = await loadButton();
    await waitFor(() => expect(button).toHaveAttribute("title", "The control node's stacks could not be read, so the config's runs cannot be matched."));
    expect(button).toBeDisabled();
  });

  it("is not offered for a workbench run", async () => {
    const user = userEvent.setup();
    entryConfig = { trajectories: { monitor: "empty" } };
    renderSection();
    await user.click(await screen.findByRole("button", { name: "Trajectory generation" }));
    await screen.findByRole("heading", { name: "Trajectory generation", level: 3 });
    await waitFor(() => expect(screen.getByText(/version 1 of 1/)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /into the wizard/ })).not.toBeInTheDocument();
  });
});
