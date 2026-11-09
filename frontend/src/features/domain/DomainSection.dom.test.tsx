import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DomainSection } from "./DomainSection";
import { useDomainDraftStore } from "./domainDraftStore";

// The Domain Configuration section against a fake operator API: the cluster's configuration and the master's presets.

const GENERAL = "SAFE_DISTANCE: 400\n";
const WARA_PS = "SAFE_DISTANCE: 250\n";
const PRESETS = {
  colregs_constants: [
    { name: "general_maritime_constants", default: true, content: GENERAL },
    { name: "wara_ps_constants", default: false, content: WARA_PS },
  ],
  vessel_types: [{ name: "vessel_types", default: true, content: "UnspecifiedVesselType:\n  max_speed: 10\n" }],
  obstacle_types: [{ name: "static_obstacle_types", default: true, content: "UnspecifiedObstacleType:\n  radius: 5\n" }],
};

let domain: Record<string, unknown>;
let posted: unknown[] = [];
let saveStatus = 200;
/** Holds the answer to a save until the test lets it go; null answers at once. */
let saveGate: Promise<void> | null = null;
/** Reading the configuration fails while set. */
let readFails = false;

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

async function fakeFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const url = new URL(String(input));
  if (url.pathname === "/cluster/catalog/domain-presets") {
    return json(PRESETS);
  }
  if (url.pathname === "/cluster/domain" && init?.method === "POST") {
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    posted.push(body);
    if (saveGate !== null) {
      await saveGate;
    }
    if (saveStatus !== 200) {
      return json({ detail: { message: "the domain configuration is not valid", reasons: ["vessel_types: expected a YAML mapping"] } }, saveStatus);
    }
    domain = { ...body, saved: true, updated_at: "2026-10-29T09:30:00+00:00", editable: true };
    return json(domain);
  }
  if (url.pathname === "/cluster/domain") {
    return readFails ? json({ detail: "the database is down" }, 503) : json(domain);
  }
  return json({ detail: "not found" }, 404);
}

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <DomainSection />
    </QueryClientProvider>
  );
  return { ...view, queryClient: client };
}

beforeEach(() => {
  domain = { colregs_constants: GENERAL, vessel_types: PRESETS.vessel_types[0].content, obstacle_types: PRESETS.obstacle_types[0].content, saved: false, updated_at: null, editable: true };
  posted = [];
  saveStatus = 200;
  saveGate = null;
  readFails = false;
  useDomainDraftStore.setState({ drafts: {} });
  vi.stubGlobal("fetch", vi.fn(fakeFetch));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the Domain Configuration section", () => {
  it("shows the cluster's configuration with the preset it matches", async () => {
    renderSection();
    expect(await screen.findByText(/Not saved yet: the master's default presets apply/)).toBeVisible();
    const select = await screen.findByRole("combobox", { name: /Load a preset of the COLREGS constants/ });
    await waitFor(() => expect(select).toHaveValue("general_maritime_constants"));
    expect(screen.getByRole("button", { name: "Save to the cluster" })).toBeDisabled();
  });

  it("saves a preset chosen from the master for the whole cluster", async () => {
    const user = userEvent.setup();
    renderSection();
    const select = await screen.findByRole("combobox", { name: /Load a preset of the COLREGS constants/ });
    await waitFor(() => expect(select).not.toBeDisabled());
    await user.selectOptions(select, "wara_ps_constants");
    expect(screen.getByText(/You have unsaved changes/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Save to the cluster" }));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toEqual({ colregs_constants: WARA_PS, vessel_types: PRESETS.vessel_types[0].content, obstacle_types: PRESETS.obstacle_types[0].content });
    expect(await screen.findByText(/Saved on the master/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Save to the cluster" })).toBeDisabled();
  });

  it("keeps the draft and lists the reasons when the master refuses it", async () => {
    saveStatus = 422;
    const user = userEvent.setup();
    renderSection();
    const select = await screen.findByRole("combobox", { name: /Load a preset of the COLREGS constants/ });
    await waitFor(() => expect(select).not.toBeDisabled());
    await user.selectOptions(select, "wara_ps_constants");
    await user.click(screen.getByRole("button", { name: "Save to the cluster" }));
    expect(await screen.findByText("vessel_types: expected a YAML mapping")).toBeVisible();
    expect(screen.getByText(/You have unsaved changes/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(screen.queryByText(/You have unsaved changes/)).not.toBeInTheDocument();
  });

  it("keeps the edits made while a save was on its way as a draft", async () => {
    let release = () => undefined as void;
    saveGate = new Promise<void>((resolve) => (release = resolve));
    const user = userEvent.setup();
    renderSection();
    const select = await screen.findByRole("combobox", { name: /Load a preset of the COLREGS constants/ });
    await waitFor(() => expect(select).not.toBeDisabled());
    await user.selectOptions(select, "wara_ps_constants");
    await user.click(screen.getByRole("button", { name: "Save to the cluster" }));
    await waitFor(() => expect(posted).toHaveLength(1));
    // typed while the save is pending
    const [clusterUrl, sent] = Object.entries(useDomainDraftStore.getState().drafts)[0];
    act(() => useDomainDraftStore.getState().setTexts(clusterUrl, { ...sent, vessel_types: "Tug: {}\n" }));
    release();
    expect(await screen.findByText(/Saved on the master/)).toBeVisible();
    expect(useDomainDraftStore.getState().drafts[clusterUrl]?.vessel_types).toBe("Tug: {}\n");
    expect(screen.getByText(/You have unsaved changes/)).toBeVisible();
  });

  it("keeps the configuration shown when reading it again fails, and says it may be out of date", async () => {
    const { queryClient } = renderSection();
    await screen.findByRole("combobox", { name: /Load a preset of the COLREGS constants/ });
    readFails = true;
    await act(() => queryClient.refetchQueries({ queryKey: ["cluster-settings"] }));
    expect(await screen.findByText(/may be out of date/)).toHaveTextContent("the database is down");
    expect(screen.getByRole("combobox", { name: /Load a preset of the COLREGS constants/ })).toBeVisible();
    expect(screen.queryByText("The domain configuration could not be read")).not.toBeInTheDocument();
  });

  it("gives each text a tab of its own", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByRole("combobox", { name: /Load a preset of the COLREGS constants/ });
    const tabs = within(screen.getByRole("tablist", { name: "Domain configuration section" }));
    expect(tabs.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["Collision rules (COLREGS)", "Vessel types", "Static obstacle types"]);
    await user.click(screen.getByRole("tab", { name: "Vessel types" }));
    expect(screen.getByRole("tab", { name: "Vessel types" })).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(screen.getByRole("combobox", { name: /Load a preset of the Vessel types/ })).toHaveValue("vessel_types"));
    expect(screen.queryByRole("combobox", { name: /Load a preset of the Static obstacle types/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Static obstacle types" }));
    await waitFor(() => expect(screen.getByRole("combobox", { name: /Load a preset of the Static obstacle types/ })).toHaveValue("static_obstacle_types"));
  });

  it("says when the master keeps no configuration of its own", async () => {
    domain = { ...domain, editable: false };
    renderSection();
    expect(await screen.findByText(/runs without its database/)).toBeVisible();
  });
});
