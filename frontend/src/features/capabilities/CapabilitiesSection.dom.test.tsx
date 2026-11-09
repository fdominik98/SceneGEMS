import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sampleStackDocument } from "../../test/fixtures/architectureDocuments";
import { CapabilitiesSection } from "./CapabilitiesSection";

// The Capabilities section against a fake operator API that serves one architecture document.

/** Reading the architecture fails while set: "http" with an answer of the master, "network" without one. */
let failure: "http" | "network" | null = null;

async function fakeFetch(input: RequestInfo | URL): Promise<Response> {
  const url = new URL(String(input));
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
  return new Response(JSON.stringify({ schema_version: 1, documents: [sampleStackDocument()] }), { status: 200, headers: { "Content-Type": "application/json" } });
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
  vi.stubGlobal("fetch", vi.fn(fakeFetch));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the Capabilities section", () => {
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
