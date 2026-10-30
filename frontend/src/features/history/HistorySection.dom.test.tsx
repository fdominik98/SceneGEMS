import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useUiStore } from "../../app/uiStore";
import { resetLiveChannels } from "../../domain/cluster/liveChannels";
import { sampleCampaignDetail } from "../../test/fixtures/clusterViews";
import { sampleCampaignRow, sampleHistoryRows, sampleRunningWorkbenchRow, sampleTrajectoryOutput, sampleWorkbenchRow } from "../../test/fixtures/historyViews";
import { MockWebSocket } from "../../test/mockWebSocket";
import { useWorkbenchTargetStore } from "../workbench/pages/workbenchTarget";
import { HistorySection } from "./HistorySection";
import { useHistoryStore } from "./historyStore";

// Campaign History against a fake operator API (fetch) and a fake live channel socket.

interface Call {
  method: string;
  path: string;
  query: URLSearchParams;
}

let calls: Call[] = [];
let deleteStatus = 204;

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
    return json([sampleTrajectoryOutput()], 1);
  }
  if (parts[3] === "events" || url.pathname === "/cluster/nodes") {
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
  MockWebSocket.reset();
  resetLiveChannels({ createSocket: MockWebSocket.factory });
  vi.stubGlobal("fetch", vi.fn(fakeFetch));
  useHistoryStore.setState({ clusterId: null, entryId: null, step: null });
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

    const output = (await screen.findByText("partial")).closest("tr") as HTMLElement;
    expect(within(output).getByText("failed")).toBeInTheDocument();
    expect(within(output).getByText("rule_15")).toBeInTheDocument();
    await user.click(within(output).getByRole("button", { name: "Open in workbench" }));
    expect(useWorkbenchTargetStore.getState().pending.trajectoryGeneration).toEqual({ page: "trajectoryGeneration", campaignId: "wb1", caseId: 6, step: "trajectory_generation" });
    expect(useUiStore.getState().section).toBe("workbench");
  });

  it("deletes a final entry after a confirmation, and says to stop one the master refuses", async () => {
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
