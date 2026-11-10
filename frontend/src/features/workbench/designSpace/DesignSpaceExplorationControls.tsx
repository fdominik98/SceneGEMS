import type { CSSProperties } from "react";
import { IconButton } from "../../../components/IconButton";
import { DownloadIcon } from "../../../components/icons";
import { describeExploration } from "../../../domain/designSpace/explorationResult";
import { NumberField } from "../../campaigns/wizard/fields";
import { describeResources, type JobTypeResources } from "../cluster/workbenchResources";
import { EntrySeedField } from "../pages/EntrySeedField";
import { PageEntryStatus } from "../pages/PageEntryStatus";
import { useExplorationPageStore } from "../pages/pageStore";
import { NumberSetting, Setting, StepPanel, StepRow, type StepNotice, type StepStatus } from "../pages/StepPanel";
import { useExplorationInputStore } from "./explorationInputStore";
import { useExplorationStore } from "./explorationStore";
import { explorationInputProblem } from "./explorationModel";
import { ScopeInput } from "./ScopeInput";

interface Props {
  resources: JobTypeResources;
  /** The exploration runs or a running one is followed. */
  busy: boolean;
  onExplore: () => void;
  onStop: () => void;
  /** Shows the specification editor (focuses it). */
  onShowSpecification: () => void;
  /** Every explored FEC's text as a ZIP; resolves once saved. */
  onExport: () => void;
  exporting: boolean;
  /** Puts the selected FEC (or the first) into the scene page's editor and shows it. */
  onNext: () => void;
}

function lineCount(text: string): number {
  return text.length === 0 ? 0 : text.replace(/\n$/, "").split("\n").length;
}

/**
 * The design space exploration page's panel: the specification (edited in the right pane) and the
 * scope, the search's seed and limits, and the FECs found with the way on to the scene page.
 */
export function DesignSpaceExplorationControls({ resources, busy, onExplore, onStop, onShowSpecification, onExport, exporting, onNext }: Props) {
  const specification = useExplorationInputStore((s) => s.specification);
  const label = useExplorationInputStore((s) => s.specificationLabel);
  const scope = useExplorationInputStore((s) => s.scope);
  const setScope = useExplorationInputStore((s) => s.setScope);
  const maxFecs = useExplorationInputStore((s) => s.maxFecs);
  const setMaxFecs = useExplorationInputStore((s) => s.setMaxFecs);
  const timeoutSeconds = useExplorationInputStore((s) => s.timeoutSeconds);
  const setTimeoutSeconds = useExplorationInputStore((s) => s.setTimeoutSeconds);
  const shownEntry = useExplorationStore((s) => s.campaignId);
  const result = useExplorationStore((s) => s.result);
  const fecs = useExplorationStore((s) => s.fecs);
  const running = useExplorationStore((s) => s.running);
  const selectedFecId = useExplorationStore((s) => s.selectedFecId);

  const notices: StepNotice[] = resources.blocker !== null ? [{ text: resources.blocker }] : [];
  const inputProblem = explorationInputProblem(specification, scope);
  const canExplore = notices.length === 0 && inputProblem === null && !busy;
  const lines = lineCount(specification);
  const shown = shownEntry !== null;
  const status: StepStatus = busy
    ? { label: "Exploring", tone: "busy" }
    : shown
      ? fecs.length > 0
        ? { label: `${fecs.length} FEC${fecs.length === 1 ? "" : "s"} found`, tone: result?.stop_reason === "exhausted" ? "ok" : "warn" }
        : { label: "No FEC found", tone: "warn" }
      : { label: "Idle", tone: "idle" };

  return (
    <StepPanel
      page="designSpaceExploration"
      title="Design Space Exploration"
      status={status}
      where={`Runs as a job on the cluster: ${describeResources(resources)}. Every run is kept in Campaign History.`}
      notices={notices}
      actions={
        busy ? (
          <button type="button" onClick={onStop}>
            Stop
          </button>
        ) : (
          <button className="primary-btn accent" type="button" disabled={!canExplore} title={inputProblem ?? undefined} onClick={onExplore}>
            Explore
          </button>
        )
      }
    >
      <StepRow label="Input">
        <span className="step-value" role="status">
          <span className="step-value-name">Specification</span>{" "}
          <span className={`step-value-text${lines > 0 ? "" : " is-empty"}`} title={label ?? undefined}>
            {lines === 0 ? "none written" : `${label ?? "written in the editor"}, ${lines} line${lines === 1 ? "" : "s"}`}
          </span>{" "}
          <button type="button" className="link-btn" onClick={onShowSpecification}>
            Edit in the specification pane
          </button>
        </span>
        <span className="step-setting step-scope">
          <label className="step-setting-label" htmlFor="design-space-scope">
            Scope
          </label>
          <ScopeInput id="design-space-scope" value={scope} onChange={setScope} disabled={busy} />
        </span>
      </StepRow>

      <StepRow label="Setup">
        <EntrySeedField disabled={busy} />
        <Setting label="Max FECs" title="Stop after this many FECs; empty explores every FEC of the design space">
          <span className="step-number" style={{ "--field-ch": 6 } as CSSProperties}>
            <NumberField integer min={1} value={maxFecs} placeholder="every" ariaLabel="Max FECs" disabled={busy} onChange={(value) => setMaxFecs(value === null ? null : Math.max(1, value))} />
          </span>
        </Setting>
        <NumberSetting
          label="Timeout"
          unit="s"
          integer
          min={1}
          max={86400}
          width={5}
          value={timeoutSeconds}
          disabled={busy}
          title="How long the search may run; the FECs found until then are kept"
          onChange={setTimeoutSeconds}
        />
      </StepRow>

      <StepRow
        label="Result"
        aside={
          <>
            <IconButton
              label="Export the FECs (ZIP of .problem files)"
              icon={<DownloadIcon />}
              disabled={busy || exporting || fecs.length === 0}
              title={exporting ? "Reading the FECs' texts..." : undefined}
              onClick={onExport}
            />
            <button
              type="button"
              className={fecs.length > 0 && !busy ? "primary-btn accent" : undefined}
              disabled={busy || fecs.length === 0}
              title={fecs.length > 0 ? `Put ${selectedFecId ?? fecs[0].fecId} into the scene page's editor and open it` : "Explore the design space first"}
              onClick={onNext}
            >
              Next: Scene Generation
            </button>
          </>
        }
      >
        <span className="step-value">
          <span className="step-value-name">FECs</span>{" "}
          <span className={`step-value-text${shown ? "" : " is-empty"}`}>
            {busy ? (running?.message ?? "exploring") : shown ? (result !== null ? describeExploration(result, fecs.length) : `${fecs.length} found`) : "none yet"}
          </span>
        </span>
        {busy && typeof running?.progress === "number" ? <progress className="fec-progress" max={1} value={running.progress} aria-label="Share of the cap found" /> : null}
        <PageEntryStatus store={useExplorationPageStore} />
      </StepRow>
    </StepPanel>
  );
}
