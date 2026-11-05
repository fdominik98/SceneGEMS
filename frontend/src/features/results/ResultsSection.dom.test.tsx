import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useResultsStore } from "../../domain/cluster/resultsStore";
import { sampleCampaignDetail, sampleCase, sampleVerdict } from "../../test/fixtures/clusterViews";
import {
  sampleCampaignRow,
  sampleFindings,
  sampleSceneVerdict,
  sampleUnmonitoredFindings,
  sampleWorkbenchRow,
} from "../../test/fixtures/historyViews";
import { ResultsSection } from "./ResultsSection";

// The master is a table of routes behind fetch; every request is recorded to check the queries.
const requests: URL[] = [];

function json(body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json", ...headers } });
}

function gone(): Response {
  return new Response(JSON.stringify({ detail: "unknown campaign" }), { status: 404, headers: { "Content-Type": "application/json" } });
}

const CAMPAIGN = sampleCampaignRow({ actual_state: "completed" });
const WORKBENCH = sampleWorkbenchRow();

function master(url: URL): Response {
  const path = url.pathname;
  if (path === "/cluster/campaigns") {
    const kind = url.searchParams.get("kind");
    const rows = [WORKBENCH, CAMPAIGN].filter((row) => kind === null || row.kind === kind);
    return json(rows, { "X-Total-Count": String(rows.length) });
  }
  if (path === "/cluster/campaigns/c1") {
    return json({ ...sampleCampaignDetail(), ...CAMPAIGN, totals: (sampleCampaignDetail() as { totals: unknown }).totals });
  }
  if (path === "/cluster/campaigns/wb1") {
    return json({ ...sampleCampaignDetail(), ...WORKBENCH, campaign_id: "wb1", fecs: [], totals: (sampleCampaignDetail() as { totals: unknown }).totals });
  }
  const findings = path.match(/^\/cluster\/campaigns\/([^/]+)\/findings$/);
  if (findings) {
    const step = url.searchParams.get("step");
    return json(step === "scene_generation" ? sampleUnmonitoredFindings : sampleFindings({ step }));
  }
  if (path.endsWith("/verdicts")) {
    const step = url.searchParams.get("step");
    const row = step === "scene" ? sampleSceneVerdict : { ...sampleVerdict, step: "trajectories", run_index: 0, run_record_id: null };
    return json([row], { "X-Total-Count": "1" });
  }
  if (path === "/cluster/campaigns/c1/cases/5") {
    return json({
      ...sampleCase,
      progress: {},
      jobs: [],
      run_records: [],
      verdicts: [sampleSceneVerdict, { ...sampleVerdict, verdict_id: 4, step: "trajectories", state: "passed", failed_rules: [], run_index: 0, run_record_id: null }],
    });
  }
  return gone();
}

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ResultsSection />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  requests.length = 0;
  useResultsStore.getState().reset();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input));
      requests.push(url);
      return master(url);
    })
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function requested(pathEnd: string): URL[] {
  return requests.filter((url) => url.pathname.endsWith(pathEnd));
}

describe("Results section", () => {
  it("offers only the executed steps and shows the last one, with its findings and step verdicts", async () => {
    renderSection();
    const tabs = await screen.findByRole("tablist", { name: "Step of the entry" });
    // The newest entry is the finished workbench run of one step.
    expect(within(tabs).getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["Trajectory generation"]);
    const findings = await screen.findByRole("region", { name: "Findings of the step" });
    expect(await within(findings).findByText("monitored")).toBeVisible();
    expect(within(findings).getByText("rule_15")).toBeVisible();
    await waitFor(() => expect(requested("/verdicts").length).toBeGreaterThan(0));
    expect(requested("/findings")[0].searchParams.get("step")).toBe("trajectory_generation");
    expect(requested("/verdicts")[0].searchParams.get("step")).toBe("trajectories");
  });

  it("switches between the steps of a campaign and says plainly that an unmonitored step has partial findings", async () => {
    const user = userEvent.setup();
    useResultsStore.getState().openCampaign("c1");
    renderSection();
    const tabs = await screen.findByRole("tablist", { name: "Step of the entry" });
    const names = within(tabs).getAllByRole("tab").map((tab) => tab.textContent);
    expect(names).toEqual(["Scene generation", "Trajectory generation"]);
    expect(within(tabs).getByRole("tab", { name: "Trajectory generation" })).toHaveAttribute("aria-selected", "true");

    await user.click(within(tabs).getByRole("tab", { name: "Scene generation" }));
    const findings = await screen.findByRole("region", { name: "Findings of the step" });
    expect(await within(findings).findByText("partial findings")).toBeVisible();
    expect(within(findings).getByRole("note")).toHaveTextContent("No monitor judged this step");
    expect(within(findings).queryByText("Passed")).not.toBeInTheDocument();
    expect(await screen.findByText(/there are no monitor summaries to list/)).toBeVisible();
    expect(screen.queryByRole("region", { name: "Monitor summaries" })?.querySelector("table")).toBeNull();

    await user.click(within(tabs).getByRole("tab", { name: "Trajectory generation" }));
    expect(await screen.findByText("rule_15")).toBeVisible();
    expect(screen.queryByText(/there are no monitor summaries to list/)).not.toBeInTheDocument();
    const sceneVerdictQueries = requested("/verdicts").filter((url) => url.searchParams.get("step") === "scene");
    expect(sceneVerdictQueries).toHaveLength(0);
  });

  it("filters the entry list by kind and name through the list route", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByRole("tablist", { name: "Step of the entry" });
    await user.selectOptions(screen.getByRole("combobox", { name: "Kind of entry" }), "campaign");
    await waitFor(() => expect(requests.some((url) => url.pathname === "/cluster/campaigns" && url.searchParams.get("kind") === "campaign")).toBe(true));
    await user.type(screen.getByRole("searchbox", { name: "Name contains" }), "head");
    await waitFor(() => expect(requests.some((url) => url.searchParams.get("q") === "head")).toBe(true));
    const entries = within(screen.getByRole("combobox", { name: "Entry" })).getAllByRole("option");
    expect(entries.map((option) => option.textContent)).toEqual([expect.stringContaining("head-on sweep (Campaign, completed")]);
  });

  it("lists every step of a case with its verdict", async () => {
    useResultsStore.getState().openCase("c1", 5);
    renderSection();
    const steps = await screen.findByRole("region", { name: "Steps of the case" });
    const rows = within(steps).getAllByRole("row").slice(1);
    expect(rows.map((row) => row.querySelector("td")?.textContent)).toEqual(["Scene generation", "Trajectory generation", "Simulation"]);
    expect(rows[0]).toHaveTextContent("failed");
    expect(rows[1]).toHaveTextContent("passed");
    expect(rows[2]).toHaveTextContent("step not executed");
  });

  it("tells that an entry is gone when it was deleted", async () => {
    useResultsStore.getState().openCampaign("deleted-entry");
    renderSection();
    expect(await screen.findByText("This entry no longer exists")).toBeVisible();
    expect(screen.getByRole("button", { name: "Show the newest entry" })).toBeVisible();
  });
});
