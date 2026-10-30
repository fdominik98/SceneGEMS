import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState, type ReactNode } from "react";
import { Disclosure } from "../../../components/Disclosure";
import { IconButton } from "../../../components/IconButton";
import { DownloadIcon } from "../../../components/icons";
import { NumberSetting, Setting, StepRow } from "../pages/StepPanel";
import { usePersistedState } from "../../../app/usePersistedState";
import { usePlaybackStore } from "../../../domain/playback/playbackStore";
import type { ActorStaticInfo } from "../../../domain/simulation/types";
import { downloadBlob } from "../scene/sceneExport";
import type { WaveInfoWire } from "../../../domain/simulation/wireTypes";
import type { SimulationStreamControls } from "./types";
import type { SimulationSetup } from "../cluster/simulationJobs";
import { applySetupRequestToDrafts, applySimulationModels } from "./simulationSetupDrafts";
import { useSimulationSetupRequestStore } from "./simulationSetupRequest";
import {
  ASV_SOFTWARE,
  ASV_SOFTWARE_LABELS,
  asvSoftwareChoice,
  buildInitializeSimulationConnectionsByAgentIdMap,
  buildInitialVesselConnectionDrafts,
  CONTROL_LAYER_LABELS,
  CONTROL_LAYERS,
  controlLayerChoice,
  mergePersistedVesselSettings,
  normalizeDraftStack,
  REAL_VESSEL_ASV_SOFTWARE,
  realVesselSoftwareChoice,
  round2,
  toPersistedVesselDrafts,
  toTopicSegment,
  type AsvSoftware,
  type ControlLayer,
  DEFAULT_SIMULATION_SPEED,
  GLOBAL_SIMULATOR_TYPES,
  SIMULATION_SPEED_MAX,
  SIMULATION_SPEED_MIN,
  type GlobalSimulatorType,
  type PersistedVesselConnectionDraft,
  type SimulationContext,
  type VesselInitConnectionDraft,
} from "./simulationInitConfig";

export interface SimulationInitControlsHandle {
  initializeSimulation: () => void;
}

const SDF_FILE_ACCEPT = ".sdf,.xml,.world,.model,text/xml,application/xml";

/** A vessel's Gazebo model: the server makes one unless a file is loaded. */
function ModelFileControls(props: {
  vesselId: string;
  content: string | undefined;
  exportFileName: string;
  onLoad: (text: string) => void;
  onClear: () => void;
}) {
  const { vesselId, content, exportFileName, onLoad, onClear } = props;
  const inputRef = useRef<HTMLInputElement | null>(null);
  const hasContent = typeof content === "string" && content.length > 0;
  return (
    <span className="sim-model-file">
      <span className={hasContent ? "sim-model-status is-loaded" : "sim-model-status"}>{hasContent ? "from a file" : "made by the server"}</span>
      <input
        ref={inputRef}
        hidden
        type="file"
        accept={SDF_FILE_ACCEPT}
        onChange={async (e) => {
          const file = e.target.files?.[0];
          if (file) {
            onLoad(await file.text());
          }
          e.target.value = "";
        }}
      />
      <button type="button" aria-label={`Load a Gazebo model for vessel ${vesselId}`} onClick={() => inputRef.current?.click()}>
        Load...
      </button>
      <IconButton
        label={`Export the Gazebo model of vessel ${vesselId}`}
        icon={<DownloadIcon />}
        disabled={!hasContent}
        onClick={() => downloadBlob(new Blob([content ?? ""], { type: "application/xml" }), exportFileName)}
      />
      {hasContent ? (
        <button type="button" className="link-btn" aria-label={`Clear the Gazebo model of vessel ${vesselId}`} onClick={onClear}>
          Clear
        </button>
      ) : null}
    </span>
  );
}

interface Props {
  streamControls: SimulationStreamControls;
  /** The setup as it changes, so the run panel can tell where it runs. */
  onSetupChange?: (setup: SimulationSetup) => void;
  /** Whether the setup runs as a live session (its connections and Gazebo models apply then only). */
  liveSession: boolean;
  /** Whether the real-time factor paces the run (a live session or an ArduPilot job; a kinematic job follows the watch speed). */
  paceApplies: boolean;
  /** Settings of the run panel shown with the simulator (the seed of a cluster run). */
  extraSettings?: ReactNode;
  disabled?: boolean;
}

const EMPTY_ACTORS: ActorStaticInfo[] = [];

function ownShipIdsOf(actors: ActorStaticInfo[]): Set<string> {
  return new Set(actors.filter((actor) => actor.isOwnShip).map((actor) => actor.id));
}

interface WaveParamDraft {
  amplitude: number;
  period: number;
  steepness: number;
  /** Propagation [east, north] in m/s; magnitude is wave speed. */
  east: number;
  north: number;
}

function clamp(n: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, n));
}

function waveToWire(w: WaveParamDraft): WaveInfoWire {
  return {
    amplitude: round2(w.amplitude),
    period: round2(w.period),
    steepness: round2(w.steepness),
    direction: [round2(w.east), round2(w.north)],
  };
}

const DEFAULT_WAVE: WaveParamDraft = {
  amplitude: 0,
  period: 8,
  steepness: 0,
  east: 0,
  north: 0,
};

const LEGACY_VESSEL_DRAFTS_WITH_MODELS_KEY = "scenegems:sim-init-vessel-drafts";

function removeLegacyVesselDraftsWithModels(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(LEGACY_VESSEL_DRAFTS_WITH_MODELS_KEY);
}

export const SimulationInitControls = forwardRef<SimulationInitControlsHandle, Props>(
  function SimulationInitControls({ streamControls, onSetupChange, liveSession, paceApplies, extraSettings, disabled = false }, ref) {
  // The simulation page's own trajectories: its input, or the run it replays.
  const animationActors = usePlaybackStore((s) => s.frames[0]?.actors ?? EMPTY_ACTORS);
  const simulationActors = usePlaybackStore((s) => s.simulationFrames[0]?.actors ?? EMPTY_ACTORS);
  const [vesselConnectionDrafts, setVesselConnectionDrafts] = useState<VesselInitConnectionDraft[]>(
    []
  );
  const [persistedVesselSettings, setPersistedVesselSettings] = usePersistedState<
    PersistedVesselConnectionDraft[]
  >("sim-init-vessel-settings", []);

  const [simulatorType, setSimulatorType] = usePersistedState<GlobalSimulatorType>(
    "sim-init-simulator-type",
    "Gazebo"
  );
  const [simulationSpeed, setSimulationSpeed] = usePersistedState(
    "sim-init-simulation-speed",
    DEFAULT_SIMULATION_SPEED
  );
  const [windEast, setWindEast] = usePersistedState("sim-init-wind-east", 0);
  const [windNorth, setWindNorth] = usePersistedState("sim-init-wind-north", 0);
  const [windUp, setWindUp] = usePersistedState("sim-init-wind-up", 0);
  const [wave, setWave] = usePersistedState<WaveParamDraft>("sim-init-wave", () => ({
    ...DEFAULT_WAVE,
  }));
  const receivedSimulationModels = usePlaybackStore((s) => s.receivedSimulationModels);
  const stackOptions = usePlaybackStore((s) => s.stackOptions);
  // The drafts as shown and sent: a simulator that does not run a vessel's control layer gets one
  // that runs its ASV software. The stored drafts keep the user's choice for the other simulators.
  const stackDrafts = useMemo(
    () => vesselConnectionDrafts.map((draft) => normalizeDraftStack(draft, simulatorType, stackOptions)),
    [vesselConnectionDrafts, simulatorType, stackOptions]
  );
  // Per-instance guard against re-applying the same server `simulation_models` payload, and the
  // same loaded run's setup. Component state (not a module global) so navigating away and back
  // re-applies the still-present models onto freshly rebuilt drafts. Both apply while rendering,
  // from the remembered token, rather than in an effect.
  const [appliedModelsToken, setAppliedModelsToken] = useState<number | null>(null);
  const modelsToken = receivedSimulationModels?.receivedToken ?? null;
  if (modelsToken !== appliedModelsToken && (modelsToken === null || vesselConnectionDrafts.length > 0)) {
    setAppliedModelsToken(modelsToken);
    if (receivedSimulationModels) {
      setVesselConnectionDrafts(applySimulationModels(vesselConnectionDrafts, receivedSimulationModels.vesselModelsByAgentId));
    }
  }
  const setupRequest = useSimulationSetupRequestStore((s) => s.request);
  const [appliedSetupToken, setAppliedSetupToken] = useState<number | null>(null);
  // A loaded run's setup waits for the vessels of its trajectories.
  if (setupRequest !== null && setupRequest.token !== appliedSetupToken && vesselConnectionDrafts.length > 0) {
    setAppliedSetupToken(setupRequest.token);
    setSimulatorType(setupRequest.simulatorType);
    if (setupRequest.speedup !== null) {
      setSimulationSpeed(setupRequest.speedup);
    }
    setWindEast(setupRequest.windVector[0]);
    setWindNorth(setupRequest.windVector[1]);
    setWindUp(setupRequest.windVector[2]);
    setWave(setupRequest.wave ?? { ...DEFAULT_WAVE });
    setVesselConnectionDrafts(applySetupRequestToDrafts(vesselConnectionDrafts, setupRequest.mode, ownShipIdsOf([...animationActors, ...simulationActors]), setupRequest.controlLayer));
  }

  // What `initialize_simulation` and `generate_simulation_models` both carry.
  const buildPayloadBase = () => ({
    simulatorType,
    simulationSpeed: Math.round(clamp(simulationSpeed, SIMULATION_SPEED_MIN, SIMULATION_SPEED_MAX)),
    windVector: [round2(windEast), round2(windNorth), round2(windUp)] as [number, number, number],
    wave: waveToWire(wave),
    connectionsByAgentId: buildInitializeSimulationConnectionsByAgentIdMap(stackDrafts),
  });

  useImperativeHandle(ref, () => ({
    initializeSimulation: () => {
      streamControls.sendMessage({ type: "initialize_simulation", ...buildPayloadBase() });
    },
  }));

  useEffect(() => {
    removeLegacyVesselDraftsWithModels();
  }, []);

  useEffect(() => {
    if (vesselConnectionDrafts.length === 0) {
      return;
    }
    setPersistedVesselSettings(toPersistedVesselDrafts(vesselConnectionDrafts));
  }, [vesselConnectionDrafts, setPersistedVesselSettings]);

  const ownShipIds = useMemo(
    () => new Set([...animationActors, ...simulationActors].filter((actor) => actor.isOwnShip).map((actor) => actor.id)),
    [animationActors, simulationActors]
  );
  useEffect(() => {
    onSetupChange?.({
      simulatorType,
      vessels: stackDrafts.map((draft) => ({
        vesselId: draft.vesselId,
        context: draft.context,
        asvSoftware: draft.asvSoftware,
        controlLayer: draft.controlLayer,
        isOwnShip: ownShipIds.has(draft.vesselId),
      })),
      windVector: [round2(windEast), round2(windNorth), round2(windUp)],
      waveAmplitude: round2(wave.amplitude),
      speedup: Math.round(clamp(simulationSpeed, SIMULATION_SPEED_MIN, SIMULATION_SPEED_MAX)),
    });
  }, [onSetupChange, ownShipIds, simulationSpeed, simulatorType, stackDrafts, wave.amplitude, windEast, windNorth, windUp]);

  useEffect(() => {
    const mergeWithExistingDrafts = (vessels: { id: string; isOwnShip: boolean }[]) => {
      const vesselIds = vessels.map((v) => v.id).join("|");
      setVesselConnectionDrafts((previousDrafts) => {
        const generated = buildInitialVesselConnectionDrafts(vessels);
        const previousIds = previousDrafts.map((draft) => draft.vesselId).join("|");
        if (previousIds === vesselIds && previousDrafts.length === generated.length) {
          return previousDrafts;
        }
        if (previousDrafts.length === 0) {
          return mergePersistedVesselSettings(persistedVesselSettings, generated);
        }
        const previousByVesselId = new Map(previousDrafts.map((draft) => [draft.vesselId, draft]));
        return generated.map((draft) => previousByVesselId.get(draft.vesselId) ?? draft);
      });
    };

    const typedSocketVessels = [...animationActors, ...simulationActors]
      .filter((actor) => actor.isVessel)
      .reduce<{ id: string; isOwnShip: boolean }[]>((acc, actor) => {
        if (!acc.some((item) => item.id === actor.id)) {
          acc.push({ id: actor.id, isOwnShip: actor.isOwnShip });
        }
        return acc;
      }, []);

    mergeWithExistingDrafts(typedSocketVessels);
  }, [
    animationActors,
    simulationActors,
    persistedVesselSettings,
    setVesselConnectionDrafts,
  ]);

  const updateConnection = <K extends keyof VesselInitConnectionDraft>(
    vesselId: string,
    key: K,
    value: VesselInitConnectionDraft[K]
  ) => {
    setVesselConnectionDrafts((drafts) =>
      drafts.map((draft) => {
        if (draft.vesselId !== vesselId) {
          return draft;
        }
        const updatedDraft = { ...draft, [key]: value };
        if (key === "context" || key === "agentName") {
          return {
            ...updatedDraft,
            topic: `waraps/unit/surface/${toTopicSegment(
              (key === "context" ? value : updatedDraft.context) as SimulationContext
            )}/${(key === "agentName" ? value : updatedDraft.agentName) as string}`,
          };
        }
        return updatedDraft;
      })
    );
  };

  const updateWave = (partial: Partial<WaveParamDraft>) => {
    setWave((prev) => ({ ...prev, ...partial }));
  };

  const updateKind = (vesselId: string, context: SimulationContext) => {
    updateConnection(vesselId, "context", context);
  };

  const vesselsWithKind = stackDrafts.length > 0;
  const simulatedDrafts = stackDrafts.filter((draft) => draft.context === "simulation");
  const loadedModels = simulatedDrafts.filter((draft) => (draft.gazeboVesselModel ?? "").length > 0).length;
  const windy = windEast !== 0 || windNorth !== 0 || windUp !== 0;
  const environmentHint = windy || wave.amplitude > 0 ? [windy ? `wind ${round2(Math.hypot(windEast, windNorth, windUp))} m/s` : null, wave.amplitude > 0 ? `waves ${round2(wave.amplitude)} m` : null].filter(Boolean).join(", ") : "calm";

  return (
    <StepRow label="Setup">
      <Setting label="Simulator">
        <select value={simulatorType} disabled={disabled} onChange={(e) => setSimulatorType(e.target.value as GlobalSimulatorType)}>
          {GLOBAL_SIMULATOR_TYPES.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
      </Setting>
      {paceApplies ? (
        <NumberSetting
          label="Pace"
          unit="x real time"
          integer
          min={SIMULATION_SPEED_MIN}
          max={SIMULATION_SPEED_MAX}
          width={3}
          value={simulationSpeed}
          disabled={disabled}
          title={`Real-time factor of a live session or an ArduPilot run, ${SIMULATION_SPEED_MIN} to ${SIMULATION_SPEED_MAX}`}
          onChange={setSimulationSpeed}
        />
      ) : null}
      {extraSettings}

      <div className="step-row-full step-table-scroll">
        <table className="step-table sim-vessel-table">
          <thead>
            <tr>
              <th>Vessel</th>
              <th>Kind</th>
              <th>ASV software</th>
              <th>Control layer</th>
            </tr>
          </thead>
          <tbody>
            {vesselsWithKind ? (
              stackDrafts.map((draft) => {
                const real = draft.context === "real";
                const softwareChoices = real ? REAL_VESSEL_ASV_SOFTWARE : ASV_SOFTWARE;
                const name = `${ownShipIds.has(draft.vesselId) ? "Own ship" : "Target"} ${draft.vesselId}`;
                return (
                  <tr key={draft.vesselId}>
                    <td className="sim-vessel-name">{name}</td>
                    <td>
                      <select aria-label={`Kind of ${name}`} value={draft.context} disabled={disabled} onChange={(e) => updateKind(draft.vesselId, e.target.value as SimulationContext)}>
                        <option value="simulation">Simulated</option>
                        <option value="real">Real vessel</option>
                      </select>
                    </td>
                    <td>
                      <select
                        aria-label={`ASV software of ${name}`}
                        value={draft.asvSoftware}
                        disabled={disabled}
                        onChange={(e) => updateConnection(draft.vesselId, "asvSoftware", e.target.value as AsvSoftware)}
                      >
                        {softwareChoices.map((software) => {
                          const choice = real ? realVesselSoftwareChoice(stackOptions, software) : asvSoftwareChoice(stackOptions, simulatorType, software);
                          return (
                            <option key={software} value={software} disabled={!choice.available} title={choice.reason}>
                              {ASV_SOFTWARE_LABELS[software]}
                            </option>
                          );
                        })}
                      </select>
                    </td>
                    <td>
                      {real ? (
                        <span className="step-value-note" title="A real vessel is its own control layer and its own physics, reached through its ArduAgent">
                          {CONTROL_LAYER_LABELS.real_vessel}
                        </span>
                      ) : (
                        <select
                          aria-label={`Control layer of ${name}`}
                          value={draft.controlLayer}
                          disabled={disabled}
                          title={controlLayerChoice(stackOptions, simulatorType, draft.asvSoftware, draft.controlLayer).reason}
                          onChange={(e) => updateConnection(draft.vesselId, "controlLayer", e.target.value as ControlLayer)}
                        >
                          {CONTROL_LAYERS.map((layer) => {
                            const choice = controlLayerChoice(stackOptions, simulatorType, draft.asvSoftware, layer);
                            return (
                              <option key={layer} value={layer} disabled={!choice.available} title={choice.reason}>
                                {CONTROL_LAYER_LABELS[layer]}
                              </option>
                            );
                          })}
                        </select>
                      )}
                    </td>
                  </tr>
                );
              })
            ) : (
              <tr>
                <td colSpan={4} className="step-value-note">
                  The vessels appear once the input trajectories are taken.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <Disclosure id="simulation:environment" variant="link" headingLevel={null} title="Wind and waves" openTitle="Hide wind and waves" hint={environmentHint} className="step-more">
        <div className="step-more-body">
          <span className="step-more-group">Wind</span>
          <NumberSetting label="East" unit="m/s" min={-50} max={50} width={5} value={windEast} disabled={disabled} onChange={setWindEast} />
          <NumberSetting label="North" unit="m/s" min={-50} max={50} width={5} value={windNorth} disabled={disabled} onChange={setWindNorth} />
          <NumberSetting label="Up" unit="m/s" min={-20} max={20} width={5} value={windUp} disabled={disabled} onChange={setWindUp} />
          <span className="step-row-full" aria-hidden />
          <span className="step-more-group">Waves</span>
          <NumberSetting label="Amplitude" unit="m" min={0} max={20} width={5} value={wave.amplitude} disabled={disabled} onChange={(v) => updateWave({ amplitude: v })} />
          <NumberSetting label="Period" unit="s" min={0.5} max={60} width={5} value={wave.period} disabled={disabled} onChange={(v) => updateWave({ period: v })} />
          <NumberSetting label="Steepness" min={0} max={1} width={4} value={wave.steepness} disabled={disabled} onChange={(v) => updateWave({ steepness: v })} />
          <NumberSetting label="Going east" unit="m/s" min={-50} max={50} width={5} value={wave.east} disabled={disabled} onChange={(v) => updateWave({ east: v })} />
          <NumberSetting label="Going north" unit="m/s" min={-50} max={50} width={5} value={wave.north} disabled={disabled} onChange={(v) => updateWave({ north: v })} />
        </div>
      </Disclosure>

      {liveSession ? (
        <Disclosure
          id="simulation:agent-connections"
          variant="link"
          headingLevel={null}
          title="Agent connections"
          openTitle="Hide the agent connections"
          className="step-more"
        >
          <div className="step-table-scroll">
            <table className="step-table sim-connection-table">
              <thead>
                <tr>
                  <th>Vessel</th>
                  <th>Agent name</th>
                  <th>Topic</th>
                  <th>Port</th>
                </tr>
              </thead>
              <tbody>
                {stackDrafts.map((draft) => (
                  <tr key={draft.vesselId}>
                    <td className="sim-vessel-name">{draft.vesselId}</td>
                    <td>
                      <input aria-label={`Agent name of vessel ${draft.vesselId}`} value={draft.agentName} disabled={disabled} onChange={(e) => updateConnection(draft.vesselId, "agentName", e.target.value)} />
                    </td>
                    <td>
                      <input aria-label={`Topic of vessel ${draft.vesselId}`} title={draft.topic} value={draft.topic} disabled={disabled} onChange={(e) => updateConnection(draft.vesselId, "topic", e.target.value)} />
                    </td>
                    <td className="sim-port-cell">
                      {draft.context === "simulation" ? (
                        <input
                          aria-label={`Simulator port of vessel ${draft.vesselId}`}
                          type="number"
                          step={1}
                          value={draft.port}
                          disabled={disabled}
                          onChange={(e) => updateConnection(draft.vesselId, "port", Number.isFinite(Number(e.target.value)) ? Math.trunc(Number(e.target.value)) : draft.port)}
                        />
                      ) : (
                        <span className="step-value-note" title="A real vessel needs no simulator port">
                          none
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Disclosure>
      ) : null}

      {liveSession && simulatorType === "Gazebo" ? (
        <Disclosure
          id="simulation:vessel-physics-models"
          variant="link"
          headingLevel={null}
          title="Gazebo models"
          openTitle="Hide the Gazebo models"
          hint={loadedModels > 0 ? `${loadedModels} from a file` : undefined}
          className="step-more"
        >
          <div className="step-more-body">
            <table className="step-table sim-model-table step-row-full">
              <tbody>
                {simulatedDrafts.map((draft) => (
                  <tr key={draft.vesselId}>
                    <td className="sim-vessel-name">{draft.vesselId}</td>
                    <td>
                      <ModelFileControls
                        vesselId={draft.vesselId}
                        content={draft.gazeboVesselModel}
                        exportFileName={`${draft.agentName || draft.vesselId}.sdf`}
                        onLoad={(text) => updateConnection(draft.vesselId, "gazeboVesselModel", text)}
                        onClear={() => updateConnection(draft.vesselId, "gazeboVesselModel", undefined)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <button
              type="button"
              disabled={disabled || simulatedDrafts.length === 0}
              title="Ask the server for the models it would make, to look at or change them"
              onClick={() => streamControls.sendMessage({ type: "generate_simulation_models", ...buildPayloadBase() })}
            >
              Generate the models
            </button>
          </div>
        </Disclosure>
      ) : null}
    </StepRow>
  );
  }
);
