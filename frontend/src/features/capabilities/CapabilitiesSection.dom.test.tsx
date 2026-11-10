import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ArchitectureDocument } from "../../domain/cluster/architectureApi";
import { resetLiveChannels } from "../../domain/cluster/liveChannels";
import { useNodesStore } from "../../domain/cluster/nodesStore";
import { sampleStackDocument, sampleStackDocumentWithoutChain } from "../../test/fixtures/architectureDocuments";
import { sampleNode } from "../../test/fixtures/clusterViews";
import { MockWebSocket } from "../../test/mockWebSocket";
import { CapabilitiesSection } from "./CapabilitiesSection";

// The Capabilities section against a fake operator API that serves architecture documents and the cluster's machines.

/** Reading the architecture fails while set: "http" with an answer of the master, "network" without one. */
let failure: "http" | "network" | null = null;
/** The documents the fake master serves. */
let documents: unknown[] = [];

function part(id: string, title: string, overrides: Partial<ArchitectureDocument> = {}): ArchitectureDocument {
  return { ...sampleStackDocument(), id, title, summary: `${title} in a sentence.`, ...overrides };
}

/** The chain as a master states it: two steps and a supporting part. The sample machine has scene generation and simulation slots only. */
function chainDocuments(): ArchitectureDocument[] {
  return [
    part("exploration", "Design space exploration", { step: "Design space exploration", takes: "a specification and a scope", gives: "FECs", job_types: ["design_space_exploration"], combinations: [] }),
    part("stack", "Vessel stack", { step: "Simulation", takes: "trajectories", gives: "a simulated run", job_types: ["simulation"] }),
    part("monitoring", "Monitoring", { role: "support", step: "", takes: "runs", gives: "rule outcomes", job_types: ["scene_generation"], combinations: [] }),
  ];
}

async function fakeFetch(input: RequestInfo | URL): Promise<Response> {
  const url = new URL(String(input));
  if (url.pathname === "/cluster/nodes") {
    return new Response(JSON.stringify([sampleNode()]), { status: 200, headers: { "Content-Type": "application/json", "X-Total-Count": "1" } });
  }
  if (url.pathname !== "/cluster/catalog/architecture") {
    return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
  }
  if (failure === "network") {
    throw new TypeError("Failed to fetch");
  }
  if (failure === "http") {
    return new Response(JSON.stringify({ detail: { message: "the specs could not be read", reasons: ["vessel_stack: no layers"] } }), {
      status: 422,
      headers: { "Content-Type": "application/json" },
    });
  }
  return new Response(JSON.stringify({ schema_version: 2, documents }), { status: 200, headers: { "Content-Type": "application/json" } });
}

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <CapabilitiesSection />
    </QueryClientProvider>
  );
  return { ...view, queryClient: client };
}

beforeEach(() => {
  failure = null;
  documents = [sampleStackDocument()];
  MockWebSocket.reset();
  resetLiveChannels({ createSocket: MockWebSocket.factory });
  useNodesStore.setState({ operatorUrl: null, nodes: [], loaded: false, source: null, error: null, unreachable: false, updatedAt: null });
  vi.stubGlobal("fetch", vi.fn(fakeFetch));
});

afterEach(() => {
  resetLiveChannels();
  vi.unstubAllGlobals();
});

describe("the Capabilities section", () => {
  it("opens on the overview: the chain with what each step takes and gives and what the cluster offers", async () => {
    documents = chainDocuments();
    renderSection();
    expect(await screen.findByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { name: "The chain" })).toBeVisible();

    const exploration = screen.getByRole("article", { name: "Design space exploration" });
    expect(within(exploration).getByText("a specification and a scope")).toBeVisible();
    expect(within(exploration).getByText("FECs")).toBeVisible();
    expect(within(exploration).getByText("the design space exploration job")).toBeVisible();
    // the sample machine has no slot for it
    expect(await within(exploration).findByText("no machine offers it")).toBeVisible();

    // the vessel stack performs the simulation step, and the machine has eight simulation slots
    const simulation = screen.getByRole("article", { name: "Simulation" });
    expect(within(simulation).getByText("done by the vessel stack")).toBeVisible();
    expect(await within(simulation).findByText("8 slots on 1 machine")).toBeVisible();
    expect(within(simulation).getByText("6 implementations, 4 measured values")).toBeVisible();

    // the supporting part stands apart from the chain
    expect(screen.getByRole("heading", { name: "Alongside every step" })).toBeVisible();
    expect(screen.getByRole("article", { name: "Monitoring" })).toBeVisible();
    expect(screen.getAllByRole("listitem").filter((item) => item.className === "cap-chain-step")).toHaveLength(2);
  });

  it("opens a part from its card and goes back to the overview", async () => {
    documents = chainDocuments();
    const user = userEvent.setup();
    renderSection();
    await user.click(await screen.findByRole("button", { name: "Open vessel stack" }));
    expect(screen.getByRole("tab", { name: "Vessel stack" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: "Implemented" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/What exists now and what connects the parts/)).toBeVisible();
    expect(screen.queryByRole("heading", { name: "The chain" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Matrix" }));
    expect(screen.getByText(/Every combination of the layers/)).toBeVisible();

    await user.click(screen.getByRole("tab", { name: "Overview" }));
    expect(screen.getByRole("heading", { name: "The chain" })).toBeVisible();
  });

  it("shows the parts without a chain when the master states none", async () => {
    documents = [sampleStackDocumentWithoutChain()];
    renderSection();
    expect(await screen.findByRole("heading", { name: "The parts" })).toBeVisible();
    const card = screen.getByRole("article", { name: "Stack" });
    expect(within(card).getByText("not stated by this master")).toBeVisible();
    expect(within(card).queryByText("Takes")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "The chain" })).not.toBeInTheDocument();
  });

  it("keeps the documents shown when reading them again fails, and says they may be out of date", async () => {
    const { queryClient } = renderSection();
    expect(await screen.findByRole("tab", { name: "Stack" })).toBeVisible();
    failure = "network";
    await act(() => queryClient.refetchQueries({ queryKey: ["architecture"] }));
    expect(await screen.findByText(/may be out of date/)).toHaveTextContent("cannot reach");
    expect(screen.getByRole("tab", { name: "Stack" })).toBeVisible();
    expect(screen.getAllByText("A stack of three layers.").length).toBeGreaterThan(0);
    expect(screen.queryByText("The master cannot be reached")).not.toBeInTheDocument();
  });

  it("shows the master's reasons when the first read fails", async () => {
    failure = "http";
    renderSection();
    expect(await screen.findByText("The architecture could not be read")).toBeVisible();
    expect(screen.getByText("the specs could not be read: vessel_stack: no layers")).toBeVisible();
  });
});
