import { useEffect, useState } from "react";
import { listHistory, listOutputs, type OutputRow } from "../../../domain/cluster/historyApi";
import { describeOperatorError, type OperatorClient } from "../../../domain/cluster/operatorApi";
import type { CampaignRow, CampaignStep } from "../../../domain/cluster/schemas";
import { entryRanStep } from "./pageHandoff";

const ENTRIES_SHOWN = 20;
const OUTPUTS_SHOWN = 20;

const STEP_OUTPUT: Record<CampaignStep, string> = {
  scene_generation: "scenes",
  trajectory_generation: "trajectory sets",
  simulation: "runs",
};

type Load<T> = { phase: "loading" } | { phase: "done"; items: T[]; total: number } | { phase: "error"; message: string };

interface Props {
  client: OperatorClient;
  /** The step whose outputs the page takes. */
  step: CampaignStep;
  onPick: (entry: CampaignRow, output: OutputRow) => void;
  onClose: () => void;
}

/**
 * Picks an output of Campaign History as a page's input: an entry that ran the step, then one of
 * its outputs of that step. Only outputs that exist (not dropped cases) can be picked.
 */
export function HistoryOutputPicker({ client, step, onPick, onClose }: Props) {
  const [query, setQuery] = useState("");
  const [entries, setEntries] = useState<Load<CampaignRow>>({ phase: "loading" });
  const [entry, setEntry] = useState<CampaignRow | null>(null);
  const [outputs, setOutputs] = useState<Load<OutputRow>>({ phase: "loading" });
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      listHistory(client, { q: query.trim() || undefined, limit: ENTRIES_SHOWN * 2 }, controller.signal)
        .then(({ items, total }) => setEntries({ phase: "done", items: items.filter((row) => entryRanStep(row, step)).slice(0, ENTRIES_SHOWN), total: total ?? items.length }))
        .catch((error: unknown) => {
          if (!controller.signal.aborted) {
            setEntries({ phase: "error", message: describeOperatorError(error) });
          }
        });
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [client, query, step]);

  useEffect(() => {
    if (entry === null) {
      return;
    }
    const controller = new AbortController();
    listOutputs(client, entry.campaign_id, { step, limit: OUTPUTS_SHOWN, offset }, controller.signal)
      .then(({ items, total }) => setOutputs({ phase: "done", items, total: total ?? items.length }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setOutputs({ phase: "error", message: describeOperatorError(error) });
        }
      });
    return () => controller.abort();
  }, [client, entry, offset, step]);

  const chooseEntry = (row: CampaignRow | null) => {
    setEntry(row);
    setOffset(0);
    setOutputs({ phase: "loading" });
  };

  return (
    <section className="history-output-picker" aria-label="Pick an output from Campaign History">
      <div className="history-output-picker-head">
        <h4>{entry === null ? `Entries with ${STEP_OUTPUT[step]}` : entry.name}</h4>
        <div className="toolbar-row">
          {entry !== null ? (
            <button type="button" onClick={() => chooseEntry(null)}>
              Back to the entries
            </button>
          ) : null}
          <button type="button" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
      {entry === null ? (
        <>
          <label className="field">
            <span>Name contains</span>
            <input value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Filter entries by name" />
          </label>
          {entries.phase === "loading" ? <p className="meta">Loading the entries...</p> : null}
          {entries.phase === "error" ? (
            <p className="error" role="alert">
              {entries.message}
            </p>
          ) : null}
          {entries.phase === "done" ? (
            entries.items.length === 0 ? (
              <p className="meta">No entry has {STEP_OUTPUT[step]} yet.</p>
            ) : (
              <ul className="history-output-list">
                {entries.items.map((row) => (
                  <li key={row.campaign_id}>
                    <button type="button" className="history-output-row" onClick={() => chooseEntry(row)}>
                      <span>{row.name}</span>
                      <span className="meta">
                        {row.kind === "workbench" ? "Workbench" : "Campaign"}, {row.actual_state}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )
          ) : null}
        </>
      ) : (
        <>
          {outputs.phase === "loading" ? <p className="meta">Loading the {STEP_OUTPUT[step]}...</p> : null}
          {outputs.phase === "error" ? (
            <p className="error" role="alert">
              {outputs.message}
            </p>
          ) : null}
          {outputs.phase === "done" ? (
            outputs.items.length === 0 ? (
              <p className="meta">This entry has no {STEP_OUTPUT[step]}.</p>
            ) : (
              <>
                <ul className="history-output-list">
                  {outputs.items.map((row) => (
                    <li key={`${row.case_id}-${row.run_record_id ?? "case"}`}>
                      <button type="button" className="history-output-row" disabled={row.artifact === null} onClick={() => onPick(entry, row)}>
                        <span>
                          {row.fec_id}, case {row.case_index + 1}
                          {row.run_index !== null ? `, run ${row.run_index + 1}` : ""}
                        </span>
                        <span className="meta">
                          {row.artifact === null ? (row.reason ?? row.state) : row.verdict ? `${row.state}, ${row.verdict.state}` : row.state}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
                {outputs.total > OUTPUTS_SHOWN ? (
                  <div className="toolbar-row">
                    <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - OUTPUTS_SHOWN))}>
                      Previous
                    </button>
                    <span className="meta">
                      {offset + 1} to {Math.min(offset + OUTPUTS_SHOWN, outputs.total)} of {outputs.total}
                    </span>
                    <button type="button" disabled={offset + OUTPUTS_SHOWN >= outputs.total} onClick={() => setOffset(offset + OUTPUTS_SHOWN)}>
                      Next
                    </button>
                  </div>
                ) : null}
              </>
            )
          ) : null}
        </>
      )}
    </section>
  );
}
