import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { listHistory, listOutputs, type OutputRow } from "../../../domain/cluster/historyApi";
import { describeOperatorError, type OperatorClient } from "../../../domain/cluster/operatorApi";
import type { CampaignRow } from "../../../domain/cluster/schemas";
import type { CampaignStep } from "../../../domain/cluster/schemas";
import { formatDateTime, plural } from "../campaignFormat";
import { itemFromOutput, outputProblem, sameOutput } from "./inputItems";
import { CAMPAIGN_STEP_LABELS, CHAIN } from "./stepPlan";
import type { InputItemDraft } from "./wizardState";

const ENTRIES_SHOWN = 50;
/** The name search reads the list once typing pauses, as the other searches of the console do. */
const SEARCH_DEBOUNCE_MS = 300;
const OUTPUTS_PER_PAGE = 25;
/** "Add every output" reads pages of this size and stops at the cap, so a huge entry does not freeze the wizard. */
const BULK_PAGE = 200;
export const BULK_CAP = 1000;

export interface HistoryPickerProps {
  client: OperatorClient | null;
  /** The steps of Campaign History whose outputs fit the campaign's first step. */
  sourceSteps: readonly CampaignStep[];
  /** The item kinds the first step takes. */
  kinds: readonly string[];
  /** What the picked outputs are called in the interface ("scenes", "trajectories"). */
  noun: string;
  items: readonly InputItemDraft[];
  onAdd: (items: InputItemDraft[]) => void;
}

function stepsOfRow(row: CampaignRow): readonly CampaignStep[] {
  // A row of a master without Phase 6 has no steps: it ran the whole chain
  return row.steps ?? CHAIN;
}

function flagsOf(output: OutputRow): string {
  const flags: string[] = [];
  if (output.valid === true) {
    flags.push("valid");
  }
  if (output.complete === false) {
    flags.push("partial");
  }
  return flags.join(", ");
}

function EntryList({ client, sourceSteps, noun, onChoose }: { client: OperatorClient; sourceSteps: readonly CampaignStep[]; noun: string; onChoose: (row: CampaignRow) => void }) {
  const [search, setSearch] = useState("");
  const [name, setName] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setName(search.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [search]);
  const query = useQuery({
    queryKey: ["wizard-history", client.baseUrl, name],
    queryFn: ({ signal }) => listHistory(client, { q: name || undefined, limit: ENTRIES_SHOWN }, signal),
    placeholderData: keepPreviousData,
  });
  const rows = (query.data?.items ?? []).filter((row) => stepsOfRow(row).some((step) => sourceSteps.includes(step)));
  return (
    <div className="wiz-history">
      <input type="search" placeholder="Find an entry by name" aria-label="Find an entry by name" value={search} onChange={(event) => setSearch(event.target.value)} />
      {query.isLoading && <p className="meta" role="status">Loading Campaign History...</p>}
      {query.error && (
        <div className="wiz-error" role="alert">
          <p>Campaign History did not load: {describeOperatorError(query.error)}</p>
          <button type="button" onClick={() => void query.refetch()}>
            Try again
          </button>
        </div>
      )}
      {query.data && rows.length === 0 && <p className="meta">No entry has {noun} to start from{name ? " with this name" : ""}. Run a workbench page or a campaign first, or upload a file.</p>}
      {rows.length > 0 && (
        <div className="camp-table-wrap wiz-class-scroll">
          <table className="camp-table camp-table--dense">
            <thead>
              <tr>
                <th>Entry</th>
                <th>Kind</th>
                <th>Steps</th>
                <th>State</th>
                <th>Created</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.campaign_id}>
                  <td title={row.campaign_id}>{row.name}</td>
                  <td>{row.kind === "workbench" ? "Workbench" : "Campaign"}</td>
                  <td>{stepsOfRow(row).map((step) => CAMPAIGN_STEP_LABELS[step]).join(", ")}</td>
                  <td>{row.actual_state}</td>
                  <td>{formatDateTime(row.created_at)}</td>
                  <td>
                    <button type="button" aria-label={`Choose ${row.name}`} onClick={() => onChoose(row)}>
                      Choose
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function OutputList({
  client,
  entry,
  step,
  kinds,
  noun,
  items,
  onAdd,
}: {
  client: OperatorClient;
  entry: CampaignRow;
  step: CampaignStep;
  kinds: readonly string[];
  noun: string;
  items: readonly InputItemDraft[];
  onAdd: (items: InputItemDraft[]) => void;
}) {
  const [page, setPage] = useState(0);
  const [bulk, setBulk] = useState<{ busy: boolean; message: string | null }>({ busy: false, message: null });
  const query = useQuery({
    queryKey: ["wizard-outputs", client.baseUrl, entry.campaign_id, step, page],
    queryFn: ({ signal }) => listOutputs(client, entry.campaign_id, { step, limit: OUTPUTS_PER_PAGE, offset: page * OUTPUTS_PER_PAGE }, signal),
    placeholderData: keepPreviousData,
  });
  const total = query.data?.total ?? 0;
  const rows = query.data?.items ?? [];
  const pages = Math.max(1, Math.ceil(total / OUTPUTS_PER_PAGE));

  const makeItems = (outputs: readonly OutputRow[]): InputItemDraft[] => {
    const taken = items.map((item) => item.name.trim());
    const made: InputItemDraft[] = [];
    for (const output of outputs) {
      if ([...items, ...made].some((item) => sameOutput(item, entry.campaign_id, step, output))) {
        continue;
      }
      const item = itemFromOutput(entry.name, entry.campaign_id, step, output, kinds, [...taken, ...made.map((entryItem) => entryItem.name)]);
      if (item) {
        made.push(item);
      }
    }
    return made;
  };

  const addPage = () => {
    const made = makeItems(rows);
    onAdd(made);
    setBulk({ busy: false, message: made.length === 0 ? "Nothing new on this page." : `Added ${plural(made.length, "output")} of this page.` });
  };

  const addEvery = async () => {
    setBulk({ busy: true, message: null });
    try {
      const all: OutputRow[] = [];
      let offset = 0;
      let available = total;
      while (offset < available && all.length < BULK_CAP) {
        const result = await listOutputs(client, entry.campaign_id, { step, limit: BULK_PAGE, offset });
        available = result.total ?? available;
        all.push(...result.items);
        if (result.items.length === 0) {
          break;
        }
        offset += result.items.length;
      }
      const made = makeItems(all.slice(0, BULK_CAP));
      onAdd(made);
      const skipped = Math.max(0, available - BULK_CAP);
      setBulk({
        busy: false,
        message: `Added ${plural(made.length, "output")}${skipped > 0 ? `; the first ${BULK_CAP} were read, ${plural(skipped, "more output")} not added` : ""}.`,
      });
    } catch (error) {
      setBulk({ busy: false, message: `The outputs did not load: ${describeOperatorError(error)}` });
    }
  };

  return (
    <div className="wiz-history">
      {query.isLoading && <p className="meta" role="status">Loading the outputs...</p>}
      {query.error && (
        <div className="wiz-error" role="alert">
          <p>The outputs did not load: {describeOperatorError(query.error)}</p>
          <button type="button" onClick={() => void query.refetch()}>
            Try again
          </button>
        </div>
      )}
      {query.data && (
        <>
          <div className="wiz-class-bar">
            <span className="meta">
              {plural(total, "output")} in {CAMPAIGN_STEP_LABELS[step].toLowerCase()}
            </span>
            <button type="button" disabled={bulk.busy || rows.length === 0} onClick={addPage}>
              Add the {rows.length} shown
            </button>
            <button type="button" disabled={bulk.busy || total === 0} onClick={() => void addEvery()}>
              {bulk.busy ? "Adding..." : `Add every output (${total})`}
            </button>
          </div>
          {bulk.message && <p className="wiz-hint" role="status">{bulk.message}</p>}
          {rows.length === 0 ? (
            <p className="meta">This step has no {noun} yet.</p>
          ) : (
            <div className="camp-table-wrap wiz-class-scroll">
              <table className="camp-table camp-table--dense">
                <thead>
                  <tr>
                    <th>Case</th>
                    <th>FEC</th>
                    <th>State</th>
                    <th>Output</th>
                    <th>Monitor</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const problem = outputProblem(row, kinds);
                    const added = items.some((item) => sameOutput(item, entry.campaign_id, step, row));
                    return (
                      <tr key={`${row.case_id}/${row.run_record_id ?? "-"}/${row.run_index ?? "-"}/${row.repeat_index ?? "-"}`}>
                        <td className="camp-num">
                          {row.case_index}
                          {row.run_index !== null ? `, run ${row.run_index + 1}` : ""}
                        </td>
                        <td title={row.fec_id}>{row.fec_id}</td>
                        <td>{row.state}</td>
                        <td>{problem ?? (flagsOf(row) || "available")}</td>
                        <td>{row.verdict ? row.verdict.state : "none"}</td>
                        <td>
                          <button
                            type="button"
                            disabled={problem !== null || added}
                            aria-label={`${added ? "Added" : "Add"} case ${row.case_index}${row.run_index !== null ? ` run ${row.run_index + 1}` : ""}`}
                            onClick={() => onAdd(makeItems([row]))}
                          >
                            {added ? "Added" : "Add"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {pages > 1 && (
            <div className="wiz-class-bar">
              <button type="button" disabled={page === 0} onClick={() => setPage(page - 1)}>
                Previous page
              </button>
              <span className="meta">
                Page {page + 1} of {pages}
              </span>
              <button type="button" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>
                Next page
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** Picks the outputs of an earlier step from Campaign History: an entry, then a step of it, then all or chosen outputs. */
export function HistoryPicker({ client, sourceSteps, kinds, noun, items, onAdd }: HistoryPickerProps) {
  const [entry, setEntry] = useState<CampaignRow | null>(null);
  const [chosenStep, setChosenStep] = useState<CampaignStep | null>(null);
  if (!client) {
    return <p className="meta">Select a cluster to browse Campaign History.</p>;
  }
  if (!entry) {
    return <EntryList client={client} sourceSteps={sourceSteps} noun={noun} onChoose={(row) => { setEntry(row); setChosenStep(null); }} />;
  }
  const available = stepsOfRow(entry).filter((step) => sourceSteps.includes(step));
  const step = chosenStep && available.includes(chosenStep) ? chosenStep : available[0];
  return (
    <div className="wiz-history">
      <div className="wiz-class-bar">
        <strong>{entry.name}</strong>
        <button type="button" onClick={() => setEntry(null)}>
          Choose another entry
        </button>
      </div>
      {available.length > 1 && (
        <div className="ce-tabs" role="group" aria-label="Step of the entry">
          {available.map((candidate) => (
            <button key={candidate} type="button" className={`ce-tab${candidate === step ? " active" : ""}`} aria-pressed={candidate === step} onClick={() => setChosenStep(candidate)}>
              {CAMPAIGN_STEP_LABELS[candidate]}
            </button>
          ))}
        </div>
      )}
      <OutputList key={`${entry.campaign_id}-${step}`} client={client} entry={entry} step={step} kinds={kinds} noun={noun} items={items} onAdd={onAdd} />
    </div>
  );
}
