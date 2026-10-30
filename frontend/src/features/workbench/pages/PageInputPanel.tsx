import { useRef, useState } from "react";
import "./pages.css";
import { describeOperatorError, type OperatorClient } from "../../../domain/cluster/operatorApi";
import type { CampaignStep } from "../../../domain/cluster/schemas";
import { fetchArtifact } from "./entryLoader";
import { HistoryOutputPicker } from "./HistoryOutputPicker";
import { inputOfHistoryOutput } from "./pageHandoff";
import type { PageInput } from "./pageStore";
import { StepRow } from "./StepPanel";

const ORIGIN_TEXT: Record<PageInput["origin"], string> = {
  previous_page: "from the previous page",
  history: "from Campaign History",
  file: "from a file",
};

interface Props {
  /** What the page takes, such as "Scene". */
  noun: string;
  input: PageInput | null;
  /** The button for the previous page's output, named after the page ("Scene page"). */
  previousLabel: string;
  /** What that button takes, as its tooltip. */
  previousTitle: string;
  previousAvailable: boolean;
  onUsePrevious: () => void | Promise<void>;
  /** The step of Campaign History whose outputs the page takes. */
  historyStep: CampaignStep;
  /** The active cluster's operator client, null without one (no history then). */
  client: OperatorClient | null;
  /** A history output was picked: its input and its content as the master stores it. */
  onPickHistory: (input: PageInput, document: unknown) => void | Promise<void>;
  onPickFile: (file: File) => void | Promise<void>;
  disabled?: boolean;
}

/**
 * The Input row of a workbench page: what the next run takes and where it came from, and the
 * three ways to set it: the previous page's output in one click, an output in Campaign
 * History, or a file.
 */
export function PageInputPanel({ noun, input, previousLabel, previousTitle, previousAvailable, onUsePrevious, historyStep, client, onPickHistory, onPickFile, disabled = false }: Props) {
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const run = async (work: () => Promise<void> | void) => {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (failure) {
      setError(describeOperatorError(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <StepRow label="Input">
      <span className="step-value" role="status">
        <span className="step-value-name">{noun}</span>{" "}
        <span className={`step-value-text${input ? "" : " is-empty"}`} title={input?.label}>
          {input ? input.label : "none chosen"}
        </span>
        {input ? (
          <>
            {" "}
            <span className="step-value-note">{ORIGIN_TEXT[input.origin]}</span>
          </>
        ) : null}
      </span>
      <span className="step-sources" role="group" aria-label={`Take the ${noun.toLowerCase()} from`}>
        <span className="step-sources-label" aria-hidden>
          Take from
        </span>
        <button type="button" disabled={disabled || busy || !previousAvailable} title={previousTitle} onClick={() => void run(onUsePrevious)}>
          {previousLabel}
        </button>
        <button
          type="button"
          disabled={disabled || busy || client === null}
          aria-expanded={picking}
          title={client === null ? "Select a cluster to use its Campaign History" : "Pick an output of an entry in Campaign History"}
          onClick={() => setPicking(!picking)}
        >
          Campaign History
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/json,.json"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file) {
              void run(() => onPickFile(file));
            }
          }}
        />
        <button type="button" disabled={disabled || busy} title="Open a JSON file" onClick={() => fileInputRef.current?.click()}>
          File...
        </button>
      </span>
      {busy ? <p className="step-line step-row-full">Loading the input...</p> : null}
      {error ? (
        <p className="step-line error step-row-full" role="alert">
          {error}
        </p>
      ) : null}
      {picking && client !== null ? (
        <div className="step-row-full">
          <HistoryOutputPicker
            client={client}
            step={historyStep}
            onClose={() => setPicking(false)}
            onPick={(entry, row) => {
              const picked = inputOfHistoryOutput(entry, row, historyStep);
              if (picked === null || picked.ref === null) {
                return;
              }
              const sha = picked.ref.sha256;
              setPicking(false);
              void run(async () => {
                const { document } = await fetchArtifact(client, sha);
                await onPickHistory(picked, document);
              });
            }}
          />
        </div>
      ) : null}
    </StepRow>
  );
}
