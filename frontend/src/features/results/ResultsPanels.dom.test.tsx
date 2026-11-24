import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { findingsSchema } from "../../domain/cluster/historyApi";
import { summarizeVerdicts } from "../../domain/cluster/resultsApi";
import { verdictSchema } from "../../domain/cluster/schemas";
import { sampleVerdict } from "../../test/fixtures/clusterViews";
import { sampleFindings } from "../../test/fixtures/historyViews";
import { FindingsPanel } from "./FindingsPanel";
import { VerdictSummaryPanel } from "./VerdictSummaryPanel";

/** What the Results panels leave out so that the outcome of a step is read once. */

const findings = (overrides: Record<string, unknown> = {}) => findingsSchema.parse(sampleFindings(overrides));
const verdict = (overrides: Record<string, unknown>) => verdictSchema.parse({ ...sampleVerdict, ...overrides });

describe("the findings of a step", () => {
  it("makes a tile of the valid and the complete outputs only when some are not", () => {
    render(<FindingsPanel findings={findings({ outputs: { count: 5, valid: 4, complete: 3 } })} loading={false} error={null} />);
    expect(screen.getByText("Valid trajectory sets")).toBeInTheDocument();
    expect(screen.getByText("Complete")).toBeInTheDocument();
    expect(screen.queryByText(/all valid/)).not.toBeInTheDocument();
  });

  it("says in a word that every output is valid and complete", () => {
    render(<FindingsPanel findings={findings({ step: "simulation", outputs: { count: 33, valid: 33, complete: 33 } })} loading={false} error={null} />);
    expect(screen.queryByText("Valid simulated runs")).not.toBeInTheDocument();
    expect(screen.queryByText("Complete")).not.toBeInTheDocument();
    expect(screen.getByText("33 simulated runs stored, all valid and complete")).toBeInTheDocument();
    // The verdicts are what the step was run for: they keep their tiles
    expect(screen.getByText("Passed")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });
});

describe("the summary of the listed monitor result summaries", () => {
  const oneRun = summarizeVerdicts([verdict({ verdict_id: 1, state: "failed" }), verdict({ verdict_id: 2, state: "passed", failed_rules: [] })]);
  const twoRuns = summarizeVerdicts([verdict({ verdict_id: 1, run_index: 0 }), verdict({ verdict_id: 2, run_index: 1 })]);

  it("is left out without a filter when the step has one run: the findings say the same", () => {
    const { container } = render(<VerdictSummaryPanel summary={oneRun} loading={false} filtered={false} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("is left out while the unfiltered summary loads", () => {
    const { container } = render(<VerdictSummaryPanel summary={undefined} loading filtered={false} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("compares the runs without a filter when the step has several, and repeats no totals", () => {
    render(<VerdictSummaryPanel summary={twoRuns} loading={false} filtered={false} />);
    expect(screen.getByRole("heading", { name: "Runs compared" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Monitor result summary counts per run and state" })).toBeInTheDocument();
    expect(screen.queryByText("Which rules failed")).not.toBeInTheDocument();
    expect(screen.queryByText("Passed", { selector: ".results-tile-label" })).not.toBeInTheDocument();
  });

  it("summarizes what a filter left: the counts and the failed rules", () => {
    render(<VerdictSummaryPanel summary={oneRun} loading={false} filtered />);
    expect(screen.getByRole("heading", { name: "Filtered runs" })).toBeInTheDocument();
    expect(screen.getByText("Passed", { selector: ".results-tile-label" })).toBeInTheDocument();
    expect(screen.getByText("Which rules failed")).toBeInTheDocument();
  });
});
