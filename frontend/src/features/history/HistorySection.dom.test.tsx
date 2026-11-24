import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useUiStore } from "../../app/uiStore";
import { resetLiveChannels } from "../../domain/cluster/liveChannels";
import { sampleCampaignDetail } from "../../test/fixtures/clusterViews";
import { sampleCampaignRow, sampleHistoryRows, sampleMonitorVerdict, sampleRunningWorkbenchRow, sampleTrajectoryOutput, sampleWorkbenchRow } from "../../test/fixtures/historyViews";
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
  return { ...row, totals: detail.totals, fecs: row.kind === "campaign" ? detail.fecs : [] };
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
    expect(within(campaignRow).getByText("Scene generation, trajectory generation")).toBeInTheDocument();
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
    expect(screen.getByText("the trajectory generation page")).toBeInTheDocument();
    // The name of the entry it was made from is known from the list
    expect(screen.getByRole("button", { name: "Made from head-on sweep" })).toBeInTheDocument();
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
      resources: { fullUsage: true },
      policy: { seed: 7 },
    });
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
