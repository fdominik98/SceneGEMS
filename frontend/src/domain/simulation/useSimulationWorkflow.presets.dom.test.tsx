import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePlaybackStore } from "../playback/playbackStore";
import { useSimulationWorkflow } from "./useSimulationWorkflow";

// The workbench on a selected cluster whose worker nodes play no part here: only the gateway socket does.
vi.mock("../../features/workbench/cluster/useWorkbenchCluster", () => {
  const view = { operatorUrl: "http://control-node:5174", cluster: null, resources: () => ({ jobType: "", components: [], workerNodes: 0, slots: 0, freeSlots: 0, blocker: null }) };
  return { useWorkbenchCluster: () => view };
});

/** The gateway's WebSocket, driven by the test: what the console sent, and messages put in by hand. */
class FakeSocket {
  static readonly OPEN = 1;
  static created: FakeSocket[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  readonly url: string;
  readonly sent: { type: string }[] = [];
  constructor(url: string) {
    this.url = url;
    FakeSocket.created.push(this);
  }
  close() {
    this.readyState = 3;
  }
  send(data: string) {
    this.sent.push(JSON.parse(data) as { type: string });
  }
  open() {
    this.readyState = FakeSocket.OPEN;
    act(() => this.onopen?.());
  }
  receive(message: Record<string, unknown>) {
    act(() => this.onmessage?.({ data: JSON.stringify(message) }));
  }
  sentOfType(type: string) {
    return this.sent.filter((message) => message.type === type);
  }
}

const mariner = { id: "mariner", name: "Mariner class cargo ship", source: "MSS", steeringType: "rudder", bounds: { length: [137, 185] }, particulars: { length: 160.93 }, notes: "" };
const presetsFor = (scenarioId: string, presetsByAgentId: Record<string, unknown[]> = { "0": [mariner], "1": [] }) => ({ type: "vessel_model_presets", scenarioId, presetsByAgentId });
const loaded = (scenarioId: string) => ({ type: "initial_state", scenarioId, timeStep: 1, trajectoryLength: 120 });

const initialPlayback = usePlaybackStore.getState();

/** The workbench with its gateway socket open. */
function connect(): FakeSocket {
  renderHook(() => useSimulationWorkflow());
  const socket = FakeSocket.created[0]!;
  socket.open();
  return socket;
}

beforeEach(() => {
  FakeSocket.created = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  usePlaybackStore.setState(initialPlayback, true);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the vessel model presets of the scenario the gateway loaded", () => {
  it("are not asked for before a scenario is loaded", () => {
    const socket = connect();
    expect(socket.url).toBe("ws://control-node:5174/ws/scenegems_backend_service");
    expect(socket.sentOfType("query_stack_options")).toHaveLength(1);
    expect(socket.sentOfType("query_vessel_model_presets")).toHaveLength(0);
    expect(usePlaybackStore.getState().vesselModelPresets).toBeNull();
  });

  it("are asked for once the gateway says it loaded the scenario, and kept with its id", () => {
    const socket = connect();
    socket.receive(loaded("scenario-1"));
    expect(socket.sentOfType("query_vessel_model_presets")).toEqual([{ type: "query_vessel_model_presets" }]);
    expect(usePlaybackStore.getState().vesselModelPresets).toBeNull();

    socket.receive(presetsFor("scenario-1"));
    expect(usePlaybackStore.getState().vesselModelPresets).toEqual({ scenarioId: "scenario-1", presetsByAgentId: { "0": [mariner], "1": [] } });
    expect(usePlaybackStore.getState().errorMessage).toBeNull();
  });

  it("are dropped when the answer is for another scenario than the loaded one", () => {
    const socket = connect();
    socket.receive(loaded("scenario-1"));
    socket.receive(presetsFor("scenario-0"));
    expect(usePlaybackStore.getState().vesselModelPresets).toBeNull();
  });

  it("go when another scenario is loaded, are asked for again, and a late answer for the former one is dropped", () => {
    const socket = connect();
    socket.receive(loaded("scenario-1"));
    socket.receive(presetsFor("scenario-1"));

    socket.receive(loaded("scenario-2"));
    expect(usePlaybackStore.getState().vesselModelPresets).toBeNull();
    expect(socket.sentOfType("query_vessel_model_presets")).toHaveLength(2);

    socket.receive(presetsFor("scenario-1"));
    expect(usePlaybackStore.getState().vesselModelPresets).toBeNull();
    socket.receive(presetsFor("scenario-2", { "0": [] }));
    expect(usePlaybackStore.getState().vesselModelPresets).toEqual({ scenarioId: "scenario-2", presetsByAgentId: { "0": [] } });
  });

  it("go with the gateway's socket, whose scenario is gone with it", () => {
    const socket = connect();
    socket.receive(loaded("scenario-1"));
    socket.receive(presetsFor("scenario-1"));
    act(() => socket.onclose?.());
    expect(usePlaybackStore.getState().vesselModelPresets).toBeNull();
  });

  it("stay unknown, without an error, on a control node of an earlier release that does not know the request", () => {
    const socket = connect();
    socket.receive(loaded("scenario-1"));
    socket.receive({ type: "error", message: "Unknown message type: query_vessel_model_presets" });
    expect(usePlaybackStore.getState().errorMessage).toBeNull();
    expect(usePlaybackStore.getState().vesselModelPresets).toBeNull();
    // Any other error of the gateway is still shown.
    socket.receive({ type: "error", message: "Invalid simulation configuration: unknown vessel model preset" });
    expect(usePlaybackStore.getState().errorMessage).toBe("Invalid simulation configuration: unknown vessel model preset");
  });

  it("keeps the preset a generated model was made from beside the model", () => {
    const socket = connect();
    socket.receive({ type: "simulation_models", connectionsByAgentId: { "0": { gazeboVesselModel: "<sdf/>", vesselModelPreset: "mariner" }, "1": { gazeboVesselModel: "<sdf/>" } } });
    expect(usePlaybackStore.getState().receivedSimulationModels).toMatchObject({
      vesselModelsByAgentId: { "0": "<sdf/>", "1": "<sdf/>" },
      vesselModelPresetByAgentId: { "0": "mariner", "1": null },
    });
  });
});
