import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BackendWsClient, type BackendWsHandlers } from "./wsClient";

/** A WebSocket that the test drives by hand. */
class FakeSocket {
  static readonly OPEN = 1;
  static created: FakeSocket[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  readonly url: string;
  constructor(url: string) {
    this.url = url;
    FakeSocket.created.push(this);
  }
  close() {
    this.readyState = 3;
  }
  send() {}
}

function handlers(): BackendWsHandlers & { statuses: string[] } {
  const statuses: string[] = [];
  return {
    statuses,
    onServerMessage: vi.fn(),
    onStatus: (status) => statuses.push(status),
    onError: vi.fn(),
  };
}

beforeEach(() => {
  FakeSocket.created = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal("window", { setTimeout: () => 1, clearTimeout: () => undefined });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("BackendWsClient", () => {
  it("ignores the events of a socket it has closed", () => {
    const h = handlers();
    const client = new BackendWsClient("ws://old", h);
    client.connect();
    const old = FakeSocket.created[0]!;
    client.disconnect();
    h.statuses.length = 0;

    old.onclose?.();
    old.onerror?.();
    old.onmessage?.({ data: JSON.stringify({ type: "monitor_status", status: "connected" }) });
    expect(h.statuses).toEqual([]);
    expect(h.onServerMessage).not.toHaveBeenCalled();
    expect(h.onError).not.toHaveBeenCalled();
  });

  it("reports the current socket's events", () => {
    const h = handlers();
    const client = new BackendWsClient("ws://new", h);
    client.connect();
    const socket = FakeSocket.created[0]!;
    socket.readyState = FakeSocket.OPEN;
    socket.onopen?.();
    socket.onmessage?.({ data: JSON.stringify({ type: "monitor_status", status: "connected" }) });
    expect(h.statuses).toEqual(["connecting", "connected"]);
    expect(h.onServerMessage).toHaveBeenCalledTimes(1);
  });
});
