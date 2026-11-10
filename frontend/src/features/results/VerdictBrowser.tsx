import { useMemo } from "react";
import { describeOperatorError } from "../../domain/cluster/operatorApi";
import { hasActiveFilters, toApiFilters, type VerdictPaging, type VerdictSort } from "../../domain/cluster/resultsApi";
import { useResultsStore } from "../../domain/cluster/resultsStore";
import type { Verdict } from "../../domain/cluster/schemas";
import { VerdictFilterBar } from "./VerdictFilterBar";
import { VerdictSummaryPanel } from "./VerdictSummaryPanel";
import { VerdictTable } from "./VerdictTable";
import { verdictStepOf, type MonitoredStep } from "./stepViews";
import { useCampaignDetail, useResultsClient, useVerdictPage, useVerdictSummary } from "./useResultsData";

interface VerdictBrowserProps {
  operatorUrl: string;
  campaignId: string;
  /** The step view shown. */
  step: MonitoredStep;
  /** Whether the control node filters verdicts by step; one without Phase 6 lists the verdicts of the whole campaign. */
  stepFilter: boolean;
}

/** The verdicts of the shown step of an entry: filters, a summary of the filtered runs and the paged table. */
export function VerdictBrowser({ operatorUrl, campaignId, step, stepFilter }: VerdictBrowserProps) {
  const verdictStep = stepFilter ? verdictStepOf(step) : undefined;
  // Scene and trajectory verdicts have run index 0 only, so the run filter and the per-run counts are for the simulation.
  const byRun = step === "simulation";
  const filters = useResultsStore((state) => state.filters);
  const page = useResultsStore((state) => state.page);
  const pageSize = useResultsStore((state) => state.pageSize);
  const direction = useResultsStore((state) => state.direction);
  const sort = useResultsStore((state) => state.sort);
  const { setFilters, resetFilters, setPage, setPageSize, setDirection, sortBy, openCase } = useResultsStore.getState();

  const paging = useMemo<VerdictPaging>(() => ({ page, pageSize, direction, sort }), [page, pageSize, direction, sort]);
  const client = useResultsClient(operatorUrl);
  const detail = useCampaignDetail(operatorUrl, campaignId);
  const verdicts = useVerdictPage(operatorUrl, campaignId, filters, paging, verdictStep);
  const summary = useVerdictSummary(operatorUrl, campaignId, filters, verdictStep, byRun);
  const total = verdicts.data?.total ?? null;
  // An older control node answers false once it was seen ignoring the sort: it has the FEC order only.
  const sortable = verdicts.data?.serverSort !== false;
  const csvUrl = client ? client.verdictsCsvUrl(campaignId, { ...toApiFilters(filters, verdictStep), ...(sortable && (sort !== "fec_id" || direction === "desc") ? { sort, order: direction } : {}) }) : null;
  const onSort = (next: VerdictSort) => (sortable ? sortBy(next) : setDirection(direction === "asc" ? "desc" : "asc"));

  const open = (verdict: Verdict) => openCase(campaignId, verdict.case_id);

  return (
    <div className="results-stack">
      <VerdictFilterBar detail={detail.data} filters={filters} onChange={setFilters} onReset={resetFilters} csvUrl={csvUrl} total={total} showRun={byRun} />
      {byRun && <VerdictSummaryPanel summary={summary.data} loading={summary.isFetching} filtered={hasActiveFilters(filters)} />}
      {byRun && summary.isError && <p className="error">The summary could not be loaded: {describeOperatorError(summary.error)}</p>}
      {verdicts.isError ? (
        <div className="results-notice results-notice--bad" role="alert">
          <strong>The monitor result summaries cannot be loaded.</strong>
          <span>{describeOperatorError(verdicts.error)}</span>
        </div>
      ) : (
        <VerdictTable
          verdicts={verdicts.data?.items ?? []}
          total={total}
          paging={paging}
          loading={verdicts.isFetching}
          onOpenCase={open}
          onPage={(next) => setPage(next, total)}
          onPageSize={setPageSize}
          sortable={sortable}
          onSort={onSort}
        />
      )}
    </div>
  );
}
