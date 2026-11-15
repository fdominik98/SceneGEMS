import { describe, expect, it } from "vitest";
import { buildInitialVesselConnectionDrafts } from "./simulationInitConfig";
import { applySetupRequestToDrafts, applySimulationModels } from "./simulationSetupDrafts";
import { useSimulationSetupRequestStore } from "./simulationSetupRequest";

const drafts = buildInitialVesselConnectionDrafts([
  { id: "0", isOwnShip: true },
  { id: "1", isOwnShip: false },
]).map((draft) => ({ ...draft, asvSystem: "mission_planner" as const, controlLayer: "ardupilot" as const }));

describe("a loaded run's setup", () => {
  it("replays every vessel on the kinematic layer", () => {
    const applied = applySetupRequestToDrafts(drafts, "replay", new Set(["0"]));
    expect(applied.map((draft) => [draft.asvSystem, draft.controlLayer, draft.context])).toEqual([
      ["replay", "none", "simulation"],
      ["replay", "none", "simulation"],
    ]);
  });

  it("steers the own ship with USV Navigation", () => {
    const applied = applySetupRequestToDrafts(drafts, "usv_navigation", new Set(["0"]));
    expect(applied.map((draft) => draft.asvSystem)).toEqual(["usv_navigation", "replay"]);
  });

  it("steers the own ship with MOOS-IvP", () => {
    const applied = applySetupRequestToDrafts(drafts, "moos_ivp", new Set(["0"]), "custom");
    expect(applied.map((draft) => [draft.asvSystem, draft.controlLayer])).toEqual([
      ["moos_ivp", "custom"],
      ["replay", "custom"],
    ]);
  });

  it("replays every vessel on ArduPilot when the run was an ArduPilot run", () => {
    const applied = applySetupRequestToDrafts(drafts, "replay", new Set(["0"]), "ardupilot");
    expect(applied.map((draft) => [draft.asvSystem, draft.controlLayer, draft.context])).toEqual([
      ["replay", "ardupilot", "simulation"],
      ["replay", "ardupilot", "simulation"],
    ]);
  });

  it("asks again with a new token for the same setup", () => {
    const setup = { simulatorType: "Kinematic" as const, mode: "replay" as const, controlLayer: "none" as const, speedup: null, windVector: [0, 0, 0] as [number, number, number], wave: null };
    useSimulationSetupRequestStore.getState().requestSetup(setup);
    const first = useSimulationSetupRequestStore.getState().request?.token ?? 0;
    useSimulationSetupRequestStore.getState().requestSetup(setup);
    expect(useSimulationSetupRequestStore.getState().request?.token).toBe(first + 1);
  });
});

describe("server vessel models", () => {
  it("go on the vessels they were made for", () => {
    const applied = applySimulationModels(drafts, { "1": "<sdf/>", "0": null });
    expect(applied.map((draft) => draft.gazeboVesselModel)).toEqual([undefined, "<sdf/>"]);
  });

  it("keep the preset the answer names for a vessel", () => {
    const chosen = drafts.map((draft) => (draft.vesselId === "0" ? { ...draft, vesselModelPreset: "hanjin_pretoria" } : draft));
    const applied = applySimulationModels(chosen, { "0": "<sdf><os/></sdf>", "1": "<sdf><ts1/></sdf>" }, { "0": "hanjin_pretoria", "1": null });
    expect(applied[0]).toMatchObject({ gazeboVesselModel: "<sdf><os/></sdf>", vesselModelPreset: "hanjin_pretoria" });
    expect(applied[1]).toMatchObject({ gazeboVesselModel: "<sdf><ts1/></sdf>" });
    expect(applied[1]).not.toHaveProperty("vesselModelPreset");
  });

  it("say what a model was made from when the choice changed while the server made it", () => {
    // Asked for with the automatic model, then a preset was chosen: the model that arrives is the automatic one.
    const chosenLater = drafts.map((draft) => ({ ...draft, vesselModelPreset: "mariner" }));
    const applied = applySimulationModels(chosenLater, { "0": "<sdf/>", "1": "<sdf/>" }, { "0": null, "1": "container_ship_175" });
    expect(applied[0]).not.toHaveProperty("vesselModelPreset");
    expect(applied[1]?.vesselModelPreset).toBe("container_ship_175");
  });

  it("leave the choice of a vessel that got no model", () => {
    const chosen = drafts.map((draft) => ({ ...draft, vesselModelPreset: "mariner" }));
    const applied = applySimulationModels(chosen, { "0": null }, { "0": null });
    expect(applied.map((draft) => draft.vesselModelPreset)).toEqual(["mariner", "mariner"]);
    expect(applied[0]).toBe(chosen[0]);
  });
});
