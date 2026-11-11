import type { ArchitectureDocument, Fact } from "../../domain/cluster/architectureApi";
import { buildMatrix, clusterJobOf, factTone, formatFactValue, words, type MatrixCell } from "./capabilitiesModel";

function fact(cell: MatrixCell, key: string): Fact | undefined {
  return cell.combination.facts.find((item) => item.key === key);
}

function Cell({ cell }: { cell: MatrixCell | undefined }) {
  if (cell === undefined) {
    return <td className="cap-matrix-cell" />;
  }
  const { combination } = cell;
  if (combination.status !== "available") {
    const reason = cell.reason ?? combination.reasons.join("; ");
    return (
      <td className={`cap-matrix-cell cap-matrix-cell--${combination.status === "planned" ? "planned" : "off"}`}>
        <span className="cap-matrix-status">{combination.status === "planned" ? "planned" : "not possible"}</span>
        {reason && <span className="cap-matrix-reason">{reason}</span>}
      </td>
    );
  }
  const tier = fact(cell, "repeatability_tier");
  const speedup = fact(cell, "max_speedup");
  const wind = fact(cell, "wind");
  const waves = fact(cell, "waves");
  const job = clusterJobOf(combination);
  return (
    <td className="cap-matrix-cell cap-matrix-cell--on">
      <span className="cap-matrix-status">available</span>
      <span className="cap-matrix-facts">
        {job && (
          <span className={`cap-fact-value cap-fact-value--${factTone(job)}`} title={job.note ?? undefined}>
            {job.value === null ? "no cluster job" : `job ${formatFactValue(job)}`}
          </span>
        )}
        {tier && <span className={`cap-fact-value cap-fact-value--${factTone(tier)}`}>{formatFactValue(tier)}</span>}
        {speedup && <span className="cap-matrix-detail">speedup {speedup.value === null ? "not measured" : formatFactValue(speedup)}</span>}
        {(wind || waves) && (
          <span className="cap-matrix-detail">
            wind {wind ? formatFactValue(wind) : "?"}, waves {waves ? formatFactValue(waves) : "?"}
          </span>
        )}
      </span>
    </td>
  );
}

/** Every combination of the three lanes as a table: which stacks exist, what the weakest link of each allows, and why the others do not. */
export function MatrixView({ document }: { document: ArchitectureDocument }) {
  const matrix = buildMatrix(document);
  if (matrix === null) {
    return <p className="cap-detail-text">This document has no availability matrix.</p>;
  }
  const [first, second, last] = document.lanes;
  return (
    <div className="cap-matrix-wrap">
      <table className="cap-matrix">
        <caption className="cap-matrix-caption">
          Each row is an {first.label} on a {second.label}; each column the {last.label} under it. The values of a stack are the weakest link over its layers and adapters.
        </caption>
        <thead>
          <tr>
            <th scope="col">{first.label}</th>
            <th scope="col">{second.label}</th>
            {matrix.columns.map((column) => (
              <th key={column.id} scope="col">
                {words(column.label)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.rows.map((row, index) => (
            <tr key={row.key}>
              {(index === 0 || matrix.rows[index - 1].upper.id !== row.upper.id) && (
                <th scope="rowgroup" rowSpan={matrix.rows.filter((item) => item.upper.id === row.upper.id).length} className="cap-matrix-group">
                  {words(row.upper.label)}
                </th>
              )}
              <th scope="row">{words(row.middle.label)}</th>
              {matrix.columns.map((column) => (
                <Cell key={column.id} cell={row.cells.get(column.id)} />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
