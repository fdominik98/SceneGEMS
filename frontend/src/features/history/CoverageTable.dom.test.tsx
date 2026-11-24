import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { classViewSchema } from "../../domain/cluster/schemas";
import { sampleClass } from "../../test/fixtures/clusterViews";
import { CoverageTable } from "./CoverageTable";

const fec = (overrides: Record<string, unknown>) => classViewSchema.parse(sampleClass(overrides));

function rowOf(name: string): HTMLElement {
  return screen.getByText(name).closest("tr") as HTMLElement;
}

describe("the coverage per FEC", () => {
  it("shows no budget left for an abandoned FEC, which the control node counts below zero", () => {
    render(
      <CoverageTable
        classes={[
          fec({ fec_id: "folder/spent", state: "abandoned", state_reason: "4 dropped or failed cases exceed the failure budget of 3", failure_budget: 3, failure_budget_left: -1 }),
          fec({ fec_id: "folder/none", state: "abandoned", state_reason: "1 dropped or failed cases exceed the failure budget of 0", failure_budget: 0, failure_budget_left: -1 }),
          fec({ fec_id: "folder/open", failure_budget: 5, failure_budget_left: 4 }),
        ]}
        runNames={["baseline"]}
      />
    );
    const spent = within(rowOf("spent")).getByText("0", { selector: "td.camp-num--bad" });
    expect(spent).toHaveTextContent("0 of 3");
    expect(within(rowOf("none")).getByText("0", { selector: "td.camp-num--bad" })).toHaveTextContent("0 of 0");
    expect(screen.queryByText(/-1/)).not.toBeInTheDocument();
    const open = within(rowOf("open")).getByText("4", { selector: "td" });
    expect(open).toHaveTextContent("4 of 5");
    expect(open).not.toHaveClass("camp-num--bad");
  });

  it("says why a FEC is open or abandoned, and keeps the reason of a complete one for the tooltip", () => {
    render(
      <CoverageTable
        classes={[
          fec({ fec_id: "folder/done", state: "complete", state_reason: "1 complete cases up to index 1" }),
          fec({ fec_id: "folder/spent", state: "abandoned", state_reason: "4 dropped or failed cases exceed the failure budget of 3", failure_budget: 3, failure_budget_left: -1 }),
        ]}
        runNames={[]}
      />
    );
    expect(screen.queryByText("1 complete cases up to index 1")).not.toBeInTheDocument();
    expect(within(rowOf("done")).getByText("Complete")).toHaveAttribute("title", "1 complete cases up to index 1");
    expect(within(rowOf("spent")).getByText("4 dropped or failed cases exceed the failure budget of 3")).toBeInTheDocument();
  });
});
