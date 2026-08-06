import { forwardRef, useEffect, useId, useImperativeHandle, useRef, useState } from "react";
import { usePersistedState } from "../../app/usePersistedState";
import { usePlaybackStore } from "../../domain/playback/playbackStore";
import type { ActorStaticInfo } from "../../domain/simulation/types";
import { downloadBlob } from "../scene/sceneExport";
import type { WaveInfoWire } from "../../domain/simulation/wireTypes";
import type { SimulationStreamControls } from "./types";
import {
  buildInitializeSimulationConnectionsByAgentIdMap,
  buildInitialVesselConnectionDrafts,
  mergePersistedVesselSettings,
  round2,
  toPersistedVesselDrafts,
  toTopicSegment,
  type ControlMode,
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
  generateSimulationWorld: () => void;
}

const SDF_FILE_ACCEPT = ".sdf,.xml,.world,.model,text/xml,application/xml";

function ModelFileControls(props: {
  content: string | undefined;
  exportFileName: string;
  onLoad: (text: string) => void;
  onClear: () => void;
}) {
  const { content, exportFileName, onLoad, onClear } = props;
  const inputRef = useRef<HTMLInputElement | null>(null);
  const hasContent = typeof content === "string" && content.length > 0;
  return (
    <div className="sim-init-model-controls">
      <span className={`sim-init-model-status ${hasContent ? "loaded" : "auto"}`}>
        {hasContent ? "loaded" : "auto (server)"}
      </span>
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
      <button
        type="button"
        className="sim-init-small-btn"
        onClick={() => inputRef.current?.click()}
      >
        Load
      </button>
      <button
        type="button"
        className="sim-init-small-btn"
        disabled={!hasContent}
        onClick={() =>
          downloadBlob(
            new Blob([content ?? ""], { type: "application/xml" }),
            exportFileName
          )
        }
      >
        Export
      </button>
      <button
        type="button"
        className="sim-init-small-btn danger"
        disabled={!hasContent}
        onClick={onClear}
      >
        Clear
      </button>
    </div>
  );
}

interface Props {
  streamControls: SimulationStreamControls;
  /** Fired when the number of vessels in the init table changes (for parent action bar). */
  onScenarioVesselCount?: (count: number) => void;
}

const EMPTY_ACTORS: ActorStaticInfo[] = [];

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

function PreciseParam(props: {
  label: string;
  value: number;
  min: number;
  max: number;
  sliderStep?: number;
  integer?: boolean;
  onChange: (v: number) => void;
  suffix?: string;
}) {
  const { label, value, min, max, onChange, suffix, integer = false } = props;
  const sliderStep = props.sliderStep ?? (integer ? 1 : 0.01);
  const normalize = (n: number) =>
    integer ? Math.round(clamp(n, min, max)) : round2(clamp(n, min, max));
  const displayValue = normalize(value);
  return (
    <label className="field sim-init-precise-field">
      <span className="sim-init-precise-label">
        {label}
        {suffix ? <span className="meta">{suffix}</span> : null}
      </span>
      <div className="sim-init-precise-row">
        <input
          type="range"
          min={min}
          max={max}
          step={sliderStep}
          value={displayValue}
          onChange={(e) => onChange(normalize(Number(e.target.value)))}
        />
        <input
          type="number"
          className="sim-init-number"
          step={integer ? 1 : 0.01}
          value={Number.isFinite(displayValue) ? displayValue : 0}
          onChange={(e) => {
            const raw = Number(e.target.value);
            if (!Number.isFinite(raw)) {
              return;
            }
            onChange(normalize(raw));
          }}
        />
      </div>
    </label>
  );
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

/** Avoid re-applying the same server `simulation_models` payload when the init panel remounts. */
let lastAppliedSimulationModelsToken: number | null = null;

const LEGACY_VESSEL_DRAFTS_WITH_MODELS_KEY = "scenegems:sim-init-vessel-drafts";

function removeLegacyVesselDraftsWithModels(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(LEGACY_VESSEL_DRAFTS_WITH_MODELS_KEY);
}

export const SimulationInitControls = forwardRef<SimulationInitControlsHandle, Props>(
  function SimulationInitControls({ streamControls, onScenarioVesselCount }, ref) {
  const baseId = useId();
  const simulationInitialized = usePlaybackStore((s) => s.simulationInitialized);
  const warapsStatus = usePlaybackStore((s) => s.warapsStatus);
  const visualizedActors = usePlaybackStore((s) => s.latestGeneratedScene?.scene?.actors ?? EMPTY_ACTORS);
  const animationActors = usePlaybackStore((s) => s.frames[0]?.actors ?? visualizedActors);
  const simulationActors = usePlaybackStore((s) => s.simulationFrames[0]?.actors ?? EMPTY_ACTORS);
  const [vesselConnectionDrafts, setVesselConnectionDrafts] = useState<VesselInitConnectionDraft[]>(
    []
  );
  const [persistedVesselSettings, setPersistedVesselSettings] = usePersistedState<
    PersistedVesselConnectionDraft[]
  >("sim-init-vessel-settings", []);
  const [scenarioVesselCount, setScenarioVesselCount] = useState(0);

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

  useImperativeHandle(
    ref,
    () => {
      const buildPayloadBase = () => {
        const waveWire = waveToWire(wave);
        return {
          simulatorType,
          simulationSpeed: Math.round(
            clamp(simulationSpeed, SIMULATION_SPEED_MIN, SIMULATION_SPEED_MAX)
          ),
          windVector: [round2(windEast), round2(windNorth), round2(windUp)],
          wave: waveWire,
          waves: [waveWire] as [WaveInfoWire],
          connectionsByAgentId:
            buildInitializeSimulationConnectionsByAgentIdMap(vesselConnectionDrafts),
        };
      };
      return {
        initializeSimulation: () => {
          streamControls.sendMessage({
            type: "initialize_simulation",
            ...buildPayloadBase(),
          });
        },
        generateSimulationWorld: () => {
          streamControls.sendMessage({
            type: "generate_simulation_models",
            ...buildPayloadBase(),
          });
        },
      };
    },
    [
      streamControls,
      simulatorType,
      simulationSpeed,
      windEast,
      windNorth,
      windUp,
      wave,
      vesselConnectionDrafts,
    ]
  );

  useEffect(() => {
    removeLegacyVesselDraftsWithModels();
  }, []);

  useEffect(() => {
    if (vesselConnectionDrafts.length === 0) {
      return;
    }
    setPersistedVesselSettings(toPersistedVesselDrafts(vesselConnectionDrafts));
  }, [vesselConnectionDrafts, setPersistedVesselSettings]);

  useEffect(() => {
    if (!receivedSimulationModels) {
      lastAppliedSimulationModelsToken = null;
      return;
    }
    if (lastAppliedSimulationModelsToken === receivedSimulationModels.receivedToken) {
      return;
    }
    lastAppliedSimulationModelsToken = receivedSimulationModels.receivedToken;
    const { vesselModelsByAgentId } = receivedSimulationModels;
    setVesselConnectionDrafts((drafts) =>
      drafts.map((draft) => {
        const model = vesselModelsByAgentId[draft.vesselId];
        return model != null ? { ...draft, gazeboVesselModel: model } : draft;
      })
    );
  }, [receivedSimulationModels, setVesselConnectionDrafts]);

  useEffect(() => {
    onScenarioVesselCount?.(scenarioVesselCount);
  }, [scenarioVesselCount, onScenarioVesselCount]);

  useEffect(() => {
    const mergeWithExistingDrafts = (vessels: { id: string; isOwnShip: boolean }[]) => {
      const vesselIds = vessels.map((v) => v.id).join("|");
      setScenarioVesselCount((current) => (current === vessels.length ? current : vessels.length));
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
    setScenarioVesselCount,
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

  return (
    <>
      <details
        className="sim-init-subpanel sim-init-subpanel-collapsible"
        open
        aria-labelledby={`${baseId}-agent-conn`}
      >
        <summary>
          <h4 id={`${baseId}-agent-conn`}>Agent connection</h4>
        </summary>
        <div style={{ maxHeight: 220, overflow: "auto" }}>
          <table className="sim-init-table">
            <thead>
              <tr>
                <th align="left">ID</th>
                <th align="left">Control mode</th>
                <th align="left">Agent name</th>
                <th align="left">Topic</th>
                <th align="left">Port</th>
              </tr>
            </thead>
            <tbody>
              {vesselConnectionDrafts.length > 0 ? (
                vesselConnectionDrafts.map((draft) => (
                  <tr key={draft.vesselId}>
                    <td>{draft.vesselId}</td>
                    <td>
                      <select
                        value={draft.controlMode}
                        onChange={(e) =>
                          updateConnection(
                            draft.vesselId,
                            "controlMode",
                            e.target.value as ControlMode
                          )
                        }
                      >
                        <option value="autonomous">autonomous</option>
                        <option value="external">external</option>
                      </select>
                    </td>
                    <td>
                      <input
                        value={draft.agentName}
                        onChange={(e) =>
                          updateConnection(draft.vesselId, "agentName", e.target.value)
                        }
                      />
                    </td>
                    <td>
                      <input
                        value={draft.topic}
                        className="sim-init-topic-input"
                        onChange={(e) => updateConnection(draft.vesselId, "topic", e.target.value)}
                      />
                    </td>
                    <td>
                      {draft.context === "simulation" ? (
                        <input
                          type="number"
                          step={1}
                          value={draft.port}
                          onChange={(e) =>
                            updateConnection(
                              draft.vesselId,
                              "port",
                              Number.isFinite(Number(e.target.value))
                                ? Math.trunc(Number(e.target.value))
                                : draft.port
                            )
                          }
                        />
                      ) : (
                        <span className="meta" title="Port is not used for real context">
                          -
                        </span>
                      )}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5} className="meta">
                    No vessels received from backend stream yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </details>

      <details
        className="sim-init-subpanel sim-init-subpanel-collapsible"
        open
        aria-labelledby={`${baseId}-vessel-models`}
      >
        <summary>
          <h4 id={`${baseId}-vessel-models`}>Vessel Physics Models</h4>
        </summary>
        <p className="meta" style={{ marginTop: 0 }}>
          Load a Gazebo SDF model per vessel, export it, or clear it to let the server
          generate one automatically.
        </p>
        <div style={{ maxHeight: 220, overflow: "auto" }}>
          <table className="sim-init-table">
            <thead>
              <tr>
                <th align="left">ID</th>
                <th align="left">Context</th>
                <th align="left">Gazebo model (.sdf)</th>
              </tr>
            </thead>
            <tbody>
              {vesselConnectionDrafts.length > 0 ? (
                vesselConnectionDrafts.map((draft) => (
                  <tr key={draft.vesselId}>
                    <td>{draft.vesselId}</td>
                    <td>
                      <select
                        value={draft.context}
                        onChange={(e) =>
                          updateConnection(
                            draft.vesselId,
                            "context",
                            e.target.value as SimulationContext
                          )
                        }
                      >
                        <option value="simulation">simulation</option>
                        <option value="real">real</option>
                      </select>
                    </td>
                    <td>
                      {draft.context === "real" ? (
                        <span
                          className="meta"
                          title="A Gazebo model is not required for real vessels"
                        >
                          not required (real vessel)
                        </span>
                      ) : (
                        <ModelFileControls
                          content={draft.gazeboVesselModel}
                          exportFileName={`${draft.agentName || draft.vesselId}.sdf`}
                          onLoad={(text) =>
                            updateConnection(draft.vesselId, "gazeboVesselModel", text)
                          }
                          onClear={() =>
                            updateConnection(draft.vesselId, "gazeboVesselModel", undefined)
                          }
                        />
                      )}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={3} className="meta">
                    No vessels received from backend stream yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </details>

      <details
        className="sim-init-subpanel sim-init-subpanel-collapsible"
        open
        aria-labelledby={`${baseId}-sim-params`}
      >
        <summary>
          <h4 id={`${baseId}-sim-params`}>Simulation parameters</h4>
        </summary>
        <label className="field">
          <span>Simulator type</span>
          <select
            value={simulatorType}
            onChange={(e) => setSimulatorType(e.target.value as GlobalSimulatorType)}
          >
            {GLOBAL_SIMULATOR_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>

        <PreciseParam
          label="Simulation speed"
          value={simulationSpeed}
          min={SIMULATION_SPEED_MIN}
          max={SIMULATION_SPEED_MAX}
          integer
          onChange={setSimulationSpeed}
        />

        <details
          className="sim-init-nested-collapsible"
          aria-labelledby={`${baseId}-wind`}
        >
          <summary>
            <h5 id={`${baseId}-wind`}>Wind</h5>
            <span className="meta sim-init-nested-summary-hint">m/s</span>
          </summary>
          <div className="sim-init-nested-body">
            <div className="sim-init-param-grid">
              <PreciseParam
                label="East (+X)"
                suffix="Ux"
                value={windEast}
                min={-50}
                max={50}
                onChange={setWindEast}
              />
              <PreciseParam
                label="North (+Y)"
                suffix="Uy"
                value={windNorth}
                min={-50}
                max={50}
                onChange={setWindNorth}
              />
              <PreciseParam
                label="Up (+Z)"
                suffix="Uz"
                value={windUp}
                min={-20}
                max={20}
                onChange={setWindUp}
              />
            </div>
          </div>
        </details>

        <details
          className="sim-init-nested-collapsible"
          aria-labelledby={`${baseId}-waves`}
        >
          <summary>
            <h5 id={`${baseId}-waves`}>Waves</h5>
            <span className="meta sim-init-nested-summary-hint">m/s</span>
          </summary>
          <div className="sim-init-nested-body">
            <div className="sim-init-param-grid">
              <PreciseParam
                label="Amplitude"
                suffix="m"
                value={wave.amplitude}
                min={0}
                max={20}
                onChange={(v) => updateWave({ amplitude: v })}
              />
              <PreciseParam
                label="Period"
                suffix="s"
                value={wave.period}
                min={0.5}
                max={60}
                onChange={(v) => updateWave({ period: v })}
              />
              <PreciseParam
                label="Steepness"
                value={wave.steepness}
                min={0}
                max={1}
                onChange={(v) => updateWave({ steepness: v })}
              />
              <PreciseParam
                label="East (+X)"
                suffix="Ux"
                value={wave.east}
                min={-50}
                max={50}
                onChange={(v) => updateWave({ east: v })}
              />
              <PreciseParam
                label="North (+Y)"
                suffix="Uy"
                value={wave.north}
                min={-50}
                max={50}
                onChange={(v) => updateWave({ north: v })}
              />
            </div>
          </div>
        </details>
      </details>

      <p className="meta" style={{ marginTop: 6 }}>
        Requirements: scenario initialized={simulationInitialized ? "yes" : "no"} | WARA-PS status=
        {warapsStatus}
      </p>
    </>
  );
  }
);
