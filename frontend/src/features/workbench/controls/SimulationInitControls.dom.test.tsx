import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useDisclosureStore } from "../../../components/disclosureStore";
import { usePlaybackStore } from "../../../domain/playback/playbackStore";
import type { SimulationFrame } from "../../../domain/simulation/types";
import type { VesselModelPresetWire } from "../../../domain/simulation/wireTypes";
import { sampleFrames } from "../../../test/fixtures/sampleFrames";
import type { SimulationSetup } from "../cluster/simulationJobs";
import { SimulationInitControls } from "./SimulationInitControls";
import type { SimulationStreamControls } from "./types";

const initialPlayback = usePlaybackStore.getState();

/** A scenario of the own ship (id 0) and two targets (ids 1 and 2), as the backend numbers them. */
function threeVessels(): SimulationFrame {
  const base = sampleFrames[0]!;
  const own = base.actors.find((actor) => actor.isOwnShip)!;
  const target = base.actors.find((actor) => !actor.isOwnShip)!;
  const state = Object.values(base.statesByActorId)[0]!;
  return {
    ...base,
    actors: [
      { ...own, id: "0", name: "os" },
      { ...target, id: "1", name: "ts1" },
      { ...target, id: "2", name: "ts2" },
    ],
    statesByActorId: { 0: state, 1: { ...state, x: state.x + 500 }, 2: { ...state, y: state.y + 500 } },
  };
}

const streamControls = { sendMessage: vi.fn() } as unknown as SimulationStreamControls;

beforeEach(() => {
  usePlaybackStore.setState(initialPlayback, true);
  usePlaybackStore.getState().setTrajectoryPreviewFrames([threeVessels()]);
  useDisclosureStore.setState({ open: {} });
  vi.mocked(streamControls.sendMessage).mockClear();
});

describe("SimulationInitControls", () => {
  it("names each vessel as the scenario does, with what it is written out", () => {
    render(<SimulationInitControls streamControls={streamControls} attended paceApplies />);
    const table = screen.getByRole("table");
    const names = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((row) => row.querySelector(".sim-vessel-name")?.textContent);
    expect(names).toEqual(["os own ship", "ts1 target ship", "ts2 target ship"]);
    expect(screen.getByRole("combobox", { name: "Kind of os, own ship" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "ASV system of ts2, target ship" })).toBeInTheDocument();
  });

  it("lets nobody name a vessel, and asks for a topic only where a real vessel publishes", async () => {
    const user = userEvent.setup();
    render(<SimulationInitControls streamControls={streamControls} attended paceApplies />);
    await user.click(screen.getByRole("button", { name: /Agent connections/ }));
    expect(screen.queryByRole("textbox", { name: /Agent name of/ })).toBeNull();
    expect(screen.queryByRole("textbox", { name: /Topic of/ })).toBeNull();
    await user.selectOptions(screen.getByRole("combobox", { name: "Kind of ts2, target ship" }), "real");
    expect(screen.getByRole("textbox", { name: "Topic of ts2, target ship" })).toHaveValue("waraps/unit/surface/real/ts2");
    expect(screen.queryByRole("textbox", { name: "Topic of os, own ship" })).toBeNull();
  });
});

describe("the vessel model of a vessel", () => {
  const preset = (id: string, name: string, source: string, notes: string): VesselModelPresetWire => ({ id, name, source, steeringType: "rudder", bounds: { length: [100, 300] }, particulars: { length: 200 }, notes });
  const hanjin = preset("hanjin_pretoria", "Hanjin Pretoria, Panamax container ship", "MSS dataPretoria.m (A. D. Pipchenko, 2007)", "The source gives no speed.");
  const mariner = preset("mariner", "Mariner class cargo ship", "MSS mariner.m", "The hull fullness stays the vessel's own.");
  /** The own ship can take both presets, ts2 the Mariner only, ts1 none. */
  const PRESETS = { "0": [hanjin, mariner], "1": [], "2": [mariner] };
  const SCENARIO = "scenario-1";

  /** The gateway's list for the loaded scenario. */
  function listPresets(presetsByAgentId: Record<string, VesselModelPresetWire[]> = PRESETS) {
    act(() => {
      usePlaybackStore.setState({ activeScenarioId: SCENARIO });
      usePlaybackStore.getState().setVesselModelPresets({ scenarioId: SCENARIO, presetsByAgentId });
    });
  }

  /** The controls of an attended run, with the setup they report. */
  function renderControls(props: { attended?: boolean } = {}) {
    const onSetupChange = vi.fn<(setup: SimulationSetup) => void>();
    render(<SimulationInitControls streamControls={streamControls} onSetupChange={onSetupChange} attended={props.attended ?? true} paceApplies />);
    const connections = () => (onSetupChange.mock.lastCall![0].body as { connectionsByAgentId: Record<string, Record<string, unknown>> }).connectionsByAgentId;
    return { connections };
  }

  async function openModels(user: UserEvent) {
    await user.click(screen.getByRole("button", { name: /Gazebo models/ }));
  }

  const modelOf = (vessel: string) => screen.getByRole("combobox", { name: `Vessel model of ${vessel}` });
  const rowOf = (vessel: string) => modelOf(vessel).closest("tr")!;

  /** A saved setup in which the vessels replay on ArduPilot with these presets chosen. */
  function saveSettings(presetByVesselId: Record<string, string>) {
    const saved = Object.entries({ "0": "os", "1": "ts1", "2": "ts2" }).map(([vesselId, agentName]) => ({
      vesselId,
      context: "simulation",
      asvSystem: "replay",
      controlLayer: "ardupilot",
      agentName,
      topic: `waraps/unit/surface/simulation/${agentName}`,
      ...(presetByVesselId[vesselId] ? { vesselModelPreset: presetByVesselId[vesselId] } : {}),
    }));
    window.localStorage.setItem("scenegems:sim-init-vessel-settings", JSON.stringify(saved));
  }

  it("is automatic by default, with the presets the vessel can take to choose from", async () => {
    const user = userEvent.setup();
    listPresets();
    const { connections } = renderControls();
    await openModels(user);

    expect(modelOf("os, own ship")).toHaveValue("");
    expect(within(modelOf("os, own ship")).getAllByRole("option").map((option) => option.textContent)).toEqual(["Automatic", hanjin.name, mariner.name]);
    expect(within(modelOf("ts2, target ship")).getAllByRole("option").map((option) => option.textContent)).toEqual(["Automatic", mariner.name]);
    // A vessel no preset fits has nothing to choose.
    expect(screen.queryByRole("combobox", { name: "Vessel model of ts1, target ship" })).toBeNull();
    const ts1Row = screen.getByRole("button", { name: "Load a Gazebo model for ts1, target ship" }).closest("tr")!;
    expect(within(ts1Row).getByText("Automatic")).toBeInTheDocument();

    for (const connection of Object.values(connections())) {
      expect(connection).not.toHaveProperty("vesselModelPreset");
    }
  });

  it("offers only the automatic model while the gateway has not listed the presets", async () => {
    const user = userEvent.setup();
    renderControls();
    await openModels(user);
    expect(screen.queryByRole("combobox", { name: /Vessel model of/ })).toBeNull();
    expect(screen.getAllByText("Automatic")).toHaveLength(3);
  });

  it("shows the chosen preset's source and notes, clears the vessel's Gazebo model and goes into the setup", async () => {
    const user = userEvent.setup();
    listPresets();
    const { connections } = renderControls();
    await openModels(user);
    // A model the server made for the automatic choice.
    act(() => usePlaybackStore.getState().setReceivedSimulationModels({ vesselModelsByAgentId: { "0": "<sdf>automatic</sdf>" }, vesselModelPresetByAgentId: { "0": null }, receivedToken: 1 }));
    expect(within(rowOf("os, own ship")).getByText("from a file")).toBeInTheDocument();
    expect(connections()["0"]).toMatchObject({ gazeboVesselModel: "<sdf>automatic</sdf>" });

    await user.selectOptions(modelOf("os, own ship"), "hanjin_pretoria");
    expect(modelOf("os, own ship")).toHaveValue("hanjin_pretoria");
    expect(within(rowOf("os, own ship")).getByText("Source: MSS dataPretoria.m (A. D. Pipchenko, 2007). The source gives no speed.")).toBeInTheDocument();
    expect(within(rowOf("os, own ship")).getByText("made by the server")).toBeInTheDocument();
    expect(connections()["0"]).toMatchObject({ vesselModelPreset: "hanjin_pretoria" });
    expect(connections()["0"]).not.toHaveProperty("gazeboVesselModel");
    // Only the vessel it was chosen for.
    expect(connections()["1"]).not.toHaveProperty("vesselModelPreset");
    expect(connections()["2"]).not.toHaveProperty("vesselModelPreset");
    expect(screen.getByRole("button", { name: /Hide the Gazebo models/ })).toHaveTextContent("1 from a preset");
  });

  it("clears the Gazebo model made from a preset when the choice goes back to automatic", async () => {
    const user = userEvent.setup();
    listPresets();
    const { connections } = renderControls();
    await openModels(user);
    await user.selectOptions(modelOf("os, own ship"), "mariner");
    // The server's answer to "Generate the models" names the preset: the draft keeps it beside the model.
    act(() => usePlaybackStore.getState().setReceivedSimulationModels({ vesselModelsByAgentId: { "0": "<sdf>mariner</sdf>" }, vesselModelPresetByAgentId: { "0": "mariner" }, receivedToken: 2 }));
    expect(modelOf("os, own ship")).toHaveValue("mariner");
    expect(connections()["0"]).toMatchObject({ vesselModelPreset: "mariner", gazeboVesselModel: "<sdf>mariner</sdf>" });

    await user.selectOptions(modelOf("os, own ship"), "");
    expect(modelOf("os, own ship")).toHaveValue("");
    expect(connections()["0"]).not.toHaveProperty("vesselModelPreset");
    expect(connections()["0"]).not.toHaveProperty("gazeboVesselModel");
    expect(screen.queryByText(/^Source:/)).toBeNull();
  });

  it("takes the preset a generated model was made from", async () => {
    const user = userEvent.setup();
    listPresets();
    const { connections } = renderControls();
    await openModels(user);
    act(() => usePlaybackStore.getState().setReceivedSimulationModels({ vesselModelsByAgentId: { "2": "<sdf>mariner</sdf>" }, vesselModelPresetByAgentId: { "2": "mariner" }, receivedToken: 3 }));
    expect(modelOf("ts2, target ship")).toHaveValue("mariner");
    expect(connections()["2"]).toMatchObject({ vesselModelPreset: "mariner", gazeboVesselModel: "<sdf>mariner</sdf>" });
  });

  it("asks the server for the models of the choice", async () => {
    const user = userEvent.setup();
    listPresets();
    renderControls();
    await openModels(user);
    await user.selectOptions(modelOf("ts2, target ship"), "mariner");
    await user.click(screen.getByRole("button", { name: "Generate the models" }));

    expect(streamControls.sendMessage).toHaveBeenCalledTimes(1);
    const message = vi.mocked(streamControls.sendMessage).mock.calls[0]![0] as { type: string; connectionsByAgentId: Record<string, Record<string, unknown>> };
    expect(message.type).toBe("generate_simulation_models");
    expect(message.connectionsByAgentId["2"]).toMatchObject({ vesselModelPreset: "mariner" });
    expect(message.connectionsByAgentId["0"]).not.toHaveProperty("vesselModelPreset");
  });

  it("restores a saved choice the vessel can still take, and falls back to automatic for one it cannot", async () => {
    const user = userEvent.setup();
    // The own ship's saved preset is not among its presets any more; ts2 keeps its own.
    saveSettings({ "0": "container_ship_175", "2": "mariner" });
    listPresets();
    const { connections } = renderControls();
    await openModels(user);

    expect(modelOf("os, own ship")).toHaveValue("");
    expect(modelOf("ts2, target ship")).toHaveValue("mariner");
    expect(connections()["0"]).not.toHaveProperty("vesselModelPreset");
    expect(connections()["2"]).toMatchObject({ vesselModelPreset: "mariner" });
    // The fallback is saved too: the choice does not come back with another scenario.
    await waitFor(() => {
      const saved = JSON.parse(window.localStorage.getItem("scenegems:sim-init-vessel-settings") ?? "[]") as { vesselId: string; vesselModelPreset?: string }[];
      expect(saved.map((draft) => draft.vesselModelPreset)).toEqual([undefined, undefined, "mariner"]);
    });
  });

  it("holds a saved choice back until the gateway lists the presets, then checks it", async () => {
    const user = userEvent.setup();
    saveSettings({ "0": "container_ship_175", "2": "mariner" });
    const { connections } = renderControls();
    await openModels(user);
    // Not known yet: nothing is sent, nothing is lost.
    expect(connections()["0"]).not.toHaveProperty("vesselModelPreset");
    expect(connections()["2"]).not.toHaveProperty("vesselModelPreset");

    listPresets();
    expect(modelOf("ts2, target ship")).toHaveValue("mariner");
    expect(modelOf("os, own ship")).toHaveValue("");
    expect(connections()["2"]).toMatchObject({ vesselModelPreset: "mariner" });
    expect(connections()["0"]).not.toHaveProperty("vesselModelPreset");
  });

  it("drops a choice when the presets of another scenario do not have it", async () => {
    const user = userEvent.setup();
    listPresets();
    const { connections } = renderControls();
    await openModels(user);
    await user.selectOptions(modelOf("os, own ship"), "hanjin_pretoria");
    expect(connections()["0"]).toMatchObject({ vesselModelPreset: "hanjin_pretoria" });

    // Another scenario with the same vessel ids, whose own ship takes the Mariner only.
    listPresets({ "0": [mariner], "1": [], "2": [mariner] });
    expect(modelOf("os, own ship")).toHaveValue("");
    expect(connections()["0"]).not.toHaveProperty("vesselModelPreset");
  });

  it("is offered for simulated vessels of an attended run in a Gazebo world only", async () => {
    const user = userEvent.setup();
    listPresets();
    const { connections } = renderControls();
    await openModels(user);
    await user.selectOptions(modelOf("os, own ship"), "hanjin_pretoria");
    await user.selectOptions(modelOf("ts2, target ship"), "mariner");

    // A real vessel is its own physics: no model, no preset.
    await user.selectOptions(screen.getByRole("combobox", { name: "Kind of ts2, target ship" }), "real");
    expect(screen.queryByRole("combobox", { name: "Vessel model of ts2, target ship" })).toBeNull();
    expect(connections()["2"]).not.toHaveProperty("vesselModelPreset");
    expect(connections()["0"]).toMatchObject({ vesselModelPreset: "hanjin_pretoria" });

    // Another simulator generates no Gazebo model.
    await user.selectOptions(screen.getByRole("combobox", { name: "Simulator" }), "ArduPilot Sim");
    expect(screen.queryByRole("button", { name: /Gazebo models/ })).toBeNull();
    expect(connections()["0"]).not.toHaveProperty("vesselModelPreset");

    // The choice is kept for the Gazebo world.
    await user.selectOptions(screen.getByRole("combobox", { name: "Simulator" }), "Gazebo");
    expect(modelOf("os, own ship")).toHaveValue("hanjin_pretoria");
    expect(connections()["0"]).toMatchObject({ vesselModelPreset: "hanjin_pretoria" });
  });

  it("is not shown for a run that is not attended", () => {
    listPresets();
    renderControls({ attended: false });
    expect(screen.queryByRole("button", { name: /Gazebo models/ })).toBeNull();
  });
});
