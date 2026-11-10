import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { usePlaybackStore } from "../../../domain/playback/playbackStore";
import { sampleControlNodeStatus } from "../../../test/fixtures/clusterViews";
import { MqttBrokerPanel } from "./MqttBrokerPanel";

function serveStatus(liveSessions: boolean | undefined) {
  const status = liveSessions === undefined ? { ...sampleControlNodeStatus, live_sessions: undefined } : { ...sampleControlNodeStatus, live_sessions: liveSessions };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) =>
      new URL(String(input)).pathname === "/cluster/status"
        ? new Response(JSON.stringify(status), { status: 200, headers: { "Content-Type": "application/json" } })
        : new Response("{}", { status: 404 })
    )
  );
}

function renderPanel() {
  usePlaybackStore.setState({ streamStatus: "connected", mqttBrokerStatus: "disconnected" });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MqttBrokerPanel sendMessage={vi.fn()} />
    </QueryClientProvider>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Connections page on a control node without live sessions", () => {
  it("says live sessions are off and does not offer to connect", async () => {
    serveStatus(false);
    renderPanel();
    expect(await screen.findByText(/Live sessions are off on this control node/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect" })).toBeDisabled();
  });

  it("says nothing when the control node has them on", async () => {
    serveStatus(true);
    renderPanel();
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(screen.queryByText(/Live sessions are off/)).not.toBeInTheDocument();
  });
});
