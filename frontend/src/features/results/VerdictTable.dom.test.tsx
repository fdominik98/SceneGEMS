import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { verdictSchema } from "../../domain/cluster/schemas";
import { sampleVerdict } from "../../test/fixtures/clusterViews";
import { VerdictTable } from "./VerdictTable";

const verdicts = [verdictSchema.parse({ ...sampleVerdict, case_index: 1 })];
const paging = { page: 0, pageSize: 50, direction: "asc" as const };

function show(props: Partial<Parameters<typeof VerdictTable>[0]>) {
  const onSort = vi.fn();
  render(<VerdictTable verdicts={verdicts} total={1} paging={paging} loading={false} onOpenCase={vi.fn()} onPage={vi.fn()} onPageSize={vi.fn()} sortable onSort={onSort} {...props} />);
  return onSort;
}

describe("VerdictTable sorting", () => {
  it("lets FEC, Case, Run, State and First failure sort on a master that sorts", async () => {
    const onSort = show({ paging: { ...paging, sort: "first_failure_time_s", direction: "desc" } });
    for (const [label, key] of [["FEC", "fec_id"], ["Case", "case_index"], ["Run", "run_index"], ["State", "state"], ["First failure", "first_failure_time_s"]] as const) {
      await userEvent.click(screen.getByRole("button", { name: new RegExp(`^${label}`) }));
      expect(onSort).toHaveBeenLastCalledWith(key);
    }
    expect(screen.getByRole("columnheader", { name: /First failure/ })).toHaveAttribute("aria-sort", "descending");
    expect(screen.getByRole("columnheader", { name: /^State/ })).not.toHaveAttribute("aria-sort");
    expect(screen.queryByRole("button", { name: /^Monitor/ })).toBeNull();
  });

  it("keeps the FEC order only, flipped by FEC, Case and Run, on a master that does not sort", () => {
    show({ sortable: false });
    for (const label of ["FEC", "Case", "Run"]) {
      expect(screen.getByRole("button", { name: new RegExp(`^${label}`) })).toBeInTheDocument();
      expect(screen.getByRole("columnheader", { name: new RegExp(`^${label}`) })).toHaveAttribute("aria-sort", "ascending");
    }
    expect(screen.queryByRole("button", { name: /^State/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^First failure/ })).toBeNull();
  });
});
