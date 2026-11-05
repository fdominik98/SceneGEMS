import { useRef } from "react";
import { IconButton } from "../../../components/IconButton";
import { DownloadIcon } from "../../../components/icons";
import type { GeneratedSceneData } from "../../../domain/simulation/types";
import { describeResources, type JobTypeResources } from "../cluster/workbenchResources";
import { EntrySeedField } from "../pages/EntrySeedField";
import { PageEntryStatus } from "../pages/PageEntryStatus";
import { useScenePageStore } from "../pages/pageStore";
import { NumberSetting, StepPanel, StepRow, type StepNotice, type StepStatus } from "../pages/StepPanel";

interface SceneGenerationControlsProps {
  resources: JobTypeResources;
  /** A generation (one scene or a batch) is running. */
  busy: boolean;
  /** The right pane's Batch tab is shown: the run generates the selected presets. */
  batch: boolean;
  batchCount: number;
  /** What the scenario of a single run is: the preset or file it came from, or null. */
  scenarioLabel: string | null;
  /** The editor holds a scenario (written or loaded). */
  hasScenario: boolean;
  /** A scenario is loading into the editor. */
  loadingLabel: string | null;
  /** Why the cluster's domain configuration does not allow generating, or null. */
  domainProblem: string | null;
  /** The right pane shows the monitor preview, not the specification editor. */
  specificationHidden: boolean;
  onShowSpecification: () => void;
  onGenerate: () => void;
  onStop: () => void;
  timeoutSeconds: number;
  onTimeoutSecondsChange: (seconds: number) => void;
  enforceLowTcpa: boolean;
  onEnforceLowTcpaChange: (value: boolean) => void;
  livePreview: boolean;
  onLivePreviewChange: (value: boolean) => void;
  /** The scene the page shows: generated, opened from a file, or loaded from an entry. */
  scene: GeneratedSceneData | null;
  /** The file the shown scene came from, or null. */
  sceneFileName: string | null;
  onOpenFile: (file: File) => void;
  onExport: () => void;
  onNext: () => void;
}

/**
 * The scene page's panel: the functional scenario (edited in the right pane), the generation
 * settings, and the scene the page shows with the way on to the trajectory page.
 */
export function SceneGenerationControls(props: SceneGenerationControlsProps) {
  const {
    resources,
    busy,
    batch,
    batchCount,
    scenarioLabel,
    hasScenario,
    loadingLabel,
    domainProblem,
    specificationHidden,
    onShowSpecification,
    onGenerate,
    onStop,
    scene,
    sceneFileName,
  } = props;
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const usable = scene?.valid === true && scene.evaluationData !== undefined;

  const notices: StepNotice[] = [];
  if (resources.blocker !== null) {
    notices.push({ text: resources.blocker });
  }
  if (domainProblem !== null) {
    notices.push({ text: domainProblem });
  }
  // The Input row says what the scenario lacks; the notices are what blocks the run elsewhere.
  const hasInput = batch ? batchCount > 0 : hasScenario;
  const canGenerate = notices.length === 0 && hasInput && !busy && loadingLabel === null;
  const status: StepStatus = busy
    ? { label: batch ? "Generating the batch" : "Generating", tone: "busy" }
    : scene
      ? scene.valid
        ? { label: "Valid scene", tone: "ok" }
        : { label: "No valid scene", tone: "warn" }
      : { label: "Idle", tone: "idle" };

  return (
    <StepPanel
      step={1}
      title="Scene Generation"
      status={status}
      where={`Generates as a job on the cluster: ${describeResources(resources)}. Every run is kept in Campaign History.`}
      notices={notices}
      actions={
        busy ? (
          <button type="button" onClick={onStop}>
            Stop
          </button>
        ) : (
          <button
            className="primary-btn accent"
            type="button"
            disabled={!canGenerate}
            title={hasInput ? undefined : batch ? "Select the FECs of the batch in the specification pane first" : "Choose a FEC or write one in the specification pane first"}
            onClick={onGenerate}
          >
            {batch ? (batchCount === 1 ? "Generate 1 scene" : `Generate ${batchCount} scenes`) : "Generate scene"}
          </button>
        )
      }
    >
      <StepRow label="Input">
        <span className="step-value" role="status">
          <span className="step-value-name">{batch ? "Batch" : "FEC"}</span>{" "}
          <span className={`step-value-text${(batch ? batchCount > 0 : hasScenario || loadingLabel !== null) ? "" : " is-empty"}`} title={scenarioLabel ?? undefined}>
            {batch
              ? batchCount === 0
                ? "no FECs selected"
                : `${batchCount} FEC${batchCount === 1 ? "" : "s"} selected`
              : loadingLabel !== null
                ? `loading ${loadingLabel}...`
                : (scenarioLabel ?? (hasScenario ? "written in the editor" : "none chosen"))}
          </span>{" "}
          <span className="step-value-note">{batch ? "in the batch list of the specification pane" : "in the specification pane"}</span>
        </span>
        {specificationHidden ? (
          <button type="button" className="link-btn" onClick={onShowSpecification}>
            Show the specification
          </button>
        ) : null}
      </StepRow>

      <StepRow label="Setup">
        <EntrySeedField disabled={busy} />
        <NumberSetting
          label="Timeout"
          unit="s"
          integer
          min={1}
          max={86400}
          width={5}
          value={props.timeoutSeconds}
          disabled={busy}
          title="How long one generation may search for a valid scene"
          onChange={props.onTimeoutSecondsChange}
        />
        <label className="step-check" title="Generate the COLREGS situation with a low time to the closest point of approach">
          <input type="checkbox" checked={props.enforceLowTcpa} disabled={busy} onChange={(e) => props.onEnforceLowTcpaChange(e.target.checked)} />
          Low TCPA
        </label>
        <label className="step-check" title="Draw the scenes the search tries on the canvas while it runs">
          <input type="checkbox" checked={props.livePreview} onChange={(e) => props.onLivePreviewChange(e.target.checked)} />
          Live preview
        </label>
      </StepRow>

      <StepRow
        label="Result"
        aside={
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept="application/json,.json"
              hidden
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) {
                  props.onOpenFile(file);
                }
              }}
            />
            <button type="button" disabled={busy} title="Show a scene from a scenario file instead of generating one" onClick={() => fileInputRef.current?.click()}>
              Open file...
            </button>
            <IconButton label="Export the scene (JSON)" icon={<DownloadIcon />} disabled={busy || !usable} onClick={props.onExport} />
            <button
              type="button"
              className={usable && !busy ? "primary-btn accent" : undefined}
              disabled={busy || !usable}
              title={usable ? "Make this scene the trajectory page's input and open it" : "Generate a valid scene, or open one, first"}
              onClick={props.onNext}
            >
              Next: Trajectory Generation
            </button>
          </>
        }
      >
        <span className="step-value">
          <span className="step-value-name">Scene</span>{" "}
          <span className={`step-value-text${scene ? "" : " is-empty"}`} title={sceneFileName ?? undefined}>
            {scene ? (sceneFileName ?? (busy ? "searching" : "generated")) : "none yet"}
          </span>
          {scene && !busy ? (
            <>
              {" "}
              <span className="step-value-note">{scene.valid ? "complies with the specification" : "the best attempt, it does not comply"}</span>
            </>
          ) : null}
        </span>
        <PageEntryStatus store={useScenePageStore} />
      </StepRow>
    </StepPanel>
  );
}
