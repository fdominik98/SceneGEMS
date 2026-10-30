import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { campaignEventSchema } from "../../domain/cluster/schemas";
import { EVENTS_KEPT } from "./campaignModel";
import { useCampaignEvents } from "./useCampaignFeed";

const { listEvents, client } = vi.hoisted(() => {
  const listEvents = vi.fn();
  return { listEvents, client: { baseUrl: "http://master", listEvents } }; // one client for every render, as the real hook memoizes it
});
vi.mock("../campaigns/useCampaignData", () => ({
  useOperatorClient: () => client,
  retryUnlessUnreachable: () => false,
}));

function event(id: number) {
  return campaignEventSchema.parse({ event_id: id, at: "2026-10-30T10:00:00+00:00", kind: "started", fec_id: null, detail: {} });
}

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

describe("useCampaignEvents", () => {
  it("reads the newest page first, then pages forward from its last event", async () => {
    listEvents.mockReset();
    listEvents.mockImplementation(async (_id: string, filters: { after?: number; newest?: number }) => ({
      items: filters.newest !== undefined ? [event(998), event(999), event(1000)] : [],
      total: 1000,
    }));
    const { result } = renderHook(() => useCampaignEvents("c1", null, [], false), { wrapper });
    await waitFor(() => expect(result.current.map((item) => item.event_id)).toEqual([998, 999, 1000]));
    expect(listEvents.mock.calls[0][1]).toEqual({ newest: EVENTS_KEPT, limit: 200 });
    // a later trigger asks for what came after the newest page, not for the newest page again
    const forward = listEvents.mock.calls.slice(1).map((call) => call[1]);
    expect(forward.every((filters) => filters.newest === undefined)).toBe(true);
  });

  it("falls back to paging from event 0 when the master ignores newest", async () => {
    listEvents.mockReset();
    const everything = Array.from({ length: 250 }, (_, index) => event(index + 1));
    listEvents.mockImplementation(async (_id: string, filters: { after?: number; limit?: number }) => ({
      items: everything.filter((item) => item.event_id > (filters.after ?? 0)).slice(0, filters.limit ?? 100),
      total: 250,
    }));
    const { result } = renderHook(() => useCampaignEvents("c1", null, [], false), { wrapper });
    await waitFor(() => expect(result.current).toHaveLength(250));
    expect(listEvents.mock.calls.map((call) => call[1].after)).toEqual([undefined, 200, 250].slice(0, listEvents.mock.calls.length));
  });
});
