import type { VesselInitConnectionDraft } from "./simulationInitConfig";

/**
 * The server's Gazebo vessel models (`simulation_models`) on the vessels they were made for. A vessel
 * that gets a model also takes the preset the answer names for it (none: the automatic model), so
 * the draft says what its model was made from.
 */
export function applySimulationModels(
  drafts: VesselInitConnectionDraft[],
  modelsByVesselId: Record<string, string | null>,
  presetByVesselId: Record<string, string | null> = {}
): VesselInitConnectionDraft[] {
  return drafts.map((draft) => {
    const model = modelsByVesselId[draft.vesselId];
    if (model == null) {
      return draft;
    }
    const withModel: VesselInitConnectionDraft = { ...draft, gazeboVesselModel: model };
    const preset = presetByVesselId[draft.vesselId];
    if (preset != null && preset.length > 0) {
      return { ...withModel, vesselModelPreset: preset };
    }
    delete withModel.vesselModelPreset;
    return withModel;
  });
}

/**
 * A loaded run's stack on the vessel table: every vessel simulated and replaying, on the kinematic
 * layer (control layer none) or on ArduPilot, and with USV Navigation or MOOS-IvP the own ship steered by it
 * (as `planSimulationRun` plans such a run).
 */
export function applySetupRequestToDrafts(
  drafts: VesselInitConnectionDraft[],
  mode: "replay" | "usv_navigation" | "moos_ivp",
  ownShipIds: ReadonlySet<string>,
  controlLayer: "none" | "ardupilot" | "custom" = "none"
): VesselInitConnectionDraft[] {
  return drafts.map((draft) => ({
    ...draft,
    context: "simulation",
    asvSystem: mode !== "replay" && ownShipIds.has(draft.vesselId) ? mode : "replay",
    controlLayer,
  }));
}
