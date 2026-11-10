import { useMemo, useState } from "react";
import type { ClassView } from "../../domain/cluster/schemas";
import { isExplorationFec } from "../../domain/designSpace/explorationResult";
import { plural, splitClassId } from "../campaigns/campaignFormat";
import {
  classProgress,
  closedWithoutCases,
  countByState,
  COVERAGE_PAGE,
  filterAndSortClasses,
  runIndexes,
  runVerdicts,
  type ClassFilter,
  type CoverageSortKey,
  type Tone,
} from "./campaignModel";
import { ProgressBar, ToneBadge } from "./campaignParts";

const CLASS_STATE_TONE: Record<ClassView["state"], Tone> = { open: "info", complete: "ok", abandoned: "bad" };
const CLASS_STATE_LABEL: Record<ClassView["state"], string> = { open: "Open", complete: "Complete", abandoned: "Abandoned" };

const COLUMNS: { key: CoverageSortKey; label: string; title: string }[] = [
  { key: "class", label: "FEC", title: "Catalog order" },
  { key: "state", label: "State", title: "Open, complete or abandoned" },
  { key: "progress", label: "Complete of quota", title: "Cases with a monitor result summary for every run, against the quota" },
  { key: "dropped", label: "Dropped", title: "Cases that could not be completed and count against the failure budget" },
  { key: "budget", label: "Budget left", title: "Failure budget left before the FEC is abandoned" },
];

function Verdicts({ entry, run }: { entry: ClassView; run: number }) {
  const counts = runVerdicts(entry, run);
  if (counts.passed + counts.failed + counts.unmonitored === 0) {
    return <span className="camp-verdict camp-verdict--none">none</span>;
  }
  return (
    <span className="camp-verdicts">
      {counts.passed > 0 && <span className="camp-verdict camp-verdict--passed" title="passed">{counts.passed} passed</span>}
      {counts.failed > 0 && <span className="camp-verdict camp-verdict--failed" title="failed">{counts.failed} failed</span>}
      {counts.unmonitored > 0 && <span className="camp-verdict camp-verdict--unmonitored" title="unmonitored">{counts.unmonitored} unmonitored</span>}
    </span>
  );
}

/** The coverage of each class: state, quota and what is complete, dropped and in flight, the failure budget, and the verdicts per run. */
export function CoverageTable({ classes, runNames }: { classes: readonly ClassView[]; runNames: readonly string[] }) {
  const [state, setState] = useState<ClassFilter>("all");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<CoverageSortKey>("class");
  const [descending, setDescending] = useState(false);
  const [limit, setLimit] = useState(COVERAGE_PAGE);

  const runs = useMemo(() => runIndexes(classes, runNames.length), [classes, runNames.length]);
  const counts = useMemo(() => countByState(classes), [classes]);
  const rows = useMemo(() => filterAndSortClasses(classes, { state, search }, sort, descending), [classes, state, search, sort, descending]);

  const sortBy = (key: CoverageSortKey) => {
    if (key === sort) {
      setDescending((value) => !value);
    } else {
      setSort(key);
      setDescending(key !== "class" && key !== "state");
    }
  };

  const visible = rows.slice(0, limit);

  return (
    <section className="panel camp-coverage" aria-label="Coverage per FEC">
      <div className="camp-section-head">
        <h3>Coverage per FEC</h3>
        <div className="camp-filters" role="group" aria-label="Filter FECs by state">
          {(["all", "open", "complete", "abandoned"] as const).map((key) => (
            <button key={key} type="button" className={`camp-chip${state === key ? " camp-chip--on" : ""}`} aria-pressed={state === key} onClick={() => setState(key)}>
              {key === "all" ? "All" : CLASS_STATE_LABEL[key]} {counts[key]}
            </button>
          ))}
          <input type="search" className="camp-search" placeholder="Find a FEC" aria-label="Find a FEC" value={search} onChange={(event) => setSearch(event.target.value)} />
        </div>
      </div>
      {classes.length === 0 ? (
        <p className="meta">This campaign has no FECs.</p>
      ) : rows.length === 0 ? (
        <p className="meta">No FEC matches the filter.</p>
      ) : (
        <div className="camp-table-wrap camp-coverage-scroll">
          <table className="camp-table camp-table--dense">
            <thead>
              <tr>
                {COLUMNS.map((column) => (
                  <th key={column.key} title={column.title} aria-sort={sort === column.key ? (descending ? "descending" : "ascending") : "none"}>
                    <button type="button" className="camp-sort" onClick={() => sortBy(column.key)}>
                      {column.label}
                      {sort === column.key && <span aria-hidden="true">{descending ? " v" : " ^"}</span>}
                    </button>
                  </th>
                ))}
                <th title="Cases that were submitted and are not finished">In flight</th>
                {runs.map((run) => (
                  <th key={run} title="Monitor result summaries of this run by state">
                    {runNames[run] ?? `Run ${run}`}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((entry) => {
                const id = splitClassId(entry.fec_id);
                return (
                  <tr key={entry.fec_id} className={`camp-class camp-class--${entry.state}`}>
                    <td className="camp-cell-class" title={entry.fec_id}>
                      <span className="camp-class-name">{id.name}</span>
                      <span className="camp-class-folder">{id.folder}</span>
                      <span className="camp-class-counts">
                        {isExplorationFec(entry.fec_id) ? "the design space exploration itself" : `${entry.vessel_count} vessels, ${plural(entry.obstacle_count, "obstacle")}`}
                      </span>
                    </td>
                    <td>
                      <ToneBadge tone={CLASS_STATE_TONE[entry.state]} title={entry.state_reason ?? undefined}>
                        {CLASS_STATE_LABEL[entry.state]}
                      </ToneBadge>
                      {entry.state_reason && <span className="camp-reason">{entry.state_reason}</span>}
                    </td>
                    <td className="camp-cell-progress">
                      <ProgressBar
                        compact
                        fraction={classProgress(entry)}
                        tone={entry.state === "complete" ? "ok" : entry.state === "abandoned" ? "bad" : "info"}
                        label={
                          closedWithoutCases(entry) ? (
                            "no cases needed"
                          ) : (
                            <>
                              <strong>{entry.complete}</strong> of {entry.quota}
                            </>
                          )
                        }
                      />
                    </td>
                    <td className={`camp-num${entry.dropped > 0 ? " camp-num--warn" : ""}`}>{entry.dropped}</td>
                    {entry.failure_budget === null || entry.failure_budget_left === null ? (
                      <td className="camp-num" title="Never abandoned: dropped and failed cases are replaced until the quota is complete">
                        unlimited
                      </td>
                    ) : (
                      <td className={`camp-num${entry.failure_budget_left === 0 && entry.failure_budget > 0 ? " camp-num--bad" : ""}`}>
                        {entry.failure_budget_left} <span className="camp-num-of">of {entry.failure_budget}</span>
                      </td>
                    )}
                    <td className="camp-num">{entry.in_flight}</td>
                    {runs.map((run) => (
                      <td key={run}>
                        <Verdicts entry={entry} run={run} />
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {rows.length > visible.length && (
        <div className="camp-more">
          <span className="meta">
            Showing {visible.length} of {plural(rows.length, "FEC")}.
          </span>
          <button type="button" onClick={() => setLimit((value) => value + COVERAGE_PAGE)}>
            Show {Math.min(COVERAGE_PAGE, rows.length - visible.length)} more
          </button>
        </div>
      )}
    </section>
  );
}
