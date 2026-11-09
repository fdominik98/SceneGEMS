import { useEffect, useState } from "react";
import "./results.css";
import { useUiStore } from "../../app/uiStore";
import { EmptyState } from "../../components/EmptyState";
import { SectionFrame } from "../../components/SectionFrame";
import { useSelectedCluster } from "../../domain/cluster/clusterStore";
import { describeOperatorError, OperatorApiError } from "../../domain/cluster/operatorApi";
import { isShownCluster, selectShownEntry, useResultsStore } from "../../domain/cluster/resultsStore";
import type { CampaignSummary } from "../../domain/cluster/schemas";
import { CasePage } from "./CasePage";
import { EntryHeader } from "./EntryHeader";
import { EntryPicker } from "./EntryPicker";
import { FindingsPanel } from "./FindingsPanel";
import { StepTabs } from "./StepTabs";
import { chooseStep, executedSteps, hasStepViews, STEP_LABEL, type KindFilter } from "./stepViews";
import { useCampaignDetail, useFindings, useHistoryList } from "./useResultsData";
import { VerdictBrowser } from "./VerdictBrowser";

const NAME_DEBOUNCE_MS = 300;

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

/**
 * The Results section: the monitor findings of one entry of Campaign History (a campaign or a
 * workbench run), with a view per executed step, the verdicts of that step, and the recorded run
 * of one case. Steps without monitoring give partial findings.
 */
export function ResultsSection() {
  const cluster = useSelectedCluster();
  const operatorUrl = cluster?.operatorUrl ?? null;
  const clusterId = cluster?.id ?? null;
  // An entry opened on another cluster (switched while this section was hidden) counts as none
  const campaignId = useResultsStore((state) => selectShownEntry(state, clusterId));
  const chosenStep = useResultsStore((state) => (isShownCluster(state, clusterId) ? state.step : null));
  const caseId = useResultsStore((state) => (isShownCluster(state, clusterId) ? state.caseId : null));
  const [kind, setKind] = useState<KindFilter>("any");
  const [name, setName] = useState("");
  const nameFilter = useDebounced(name.trim(), NAME_DEBOUNCE_MS);
  const history = useHistoryList(operatorUrl, { kind: kind === "any" ? undefined : kind, q: nameFilter === "" ? undefined : nameFilter });

  // Another cluster has other entries: forget the one that was open, with its filters and page.
  useEffect(() => {
    const state = useResultsStore.getState();
    if (!isShownCluster(state, clusterId)) {
      state.reset();
    }
  }, [clusterId]);

  const list = history.data?.items ?? [];
  // Without a pick the newest entry is shown, pinned while it stays in the list: a run that starts while the page is read does not replace it.
  const listKey = `${operatorUrl}|${kind}|${nameFilter}`;
  const newestId = list[0]?.campaign_id ?? null;
  const [pinned, setPinned] = useState<{ key: string; id: string } | null>(null);
  const pinValid = pinned !== null && pinned.key === listKey && list.some((entry) => entry.campaign_id === pinned.id);
  if (campaignId !== null && pinned !== null) {
    setPinned(null); // a pick replaces the pin, so going back to no pick shows the newest entry again
  } else if (campaignId === null && newestId !== null && !pinValid && !history.isPlaceholderData) {
    setPinned({ key: listKey, id: newestId });
  }
  const effectiveId = campaignId ?? (pinValid ? pinned.id : newestId);
  const detail = useCampaignDetail(operatorUrl, effectiveId);
  // The shown entry need not be in the filtered list (opened from another section, or filtered away).
  const selected: CampaignSummary | null = list.find((entry) => entry.campaign_id === effectiveId) ?? detail.data ?? null;
  const legacy = selected !== null && !hasStepViews(selected);
  const steps = executedSteps(selected);
  const step = chooseStep(selected, chosenStep);
  const findings = useFindings(operatorUrl, effectiveId, step, selected !== null && !legacy);
  const unmonitored = findings.data !== undefined && !findings.data.monitored;
  // Whether a monitor judged the step decides if there is a verdict table: wait for the findings (an error shows the table anyway).
  const awaitingFindings = !legacy && findings.data === undefined && !findings.isError;
  const gone = detail.isError && detail.error instanceof OperatorApiError && detail.error.status === 404 && !list.some((entry) => entry.campaign_id === effectiveId);

  const picker = cluster && (
    <EntryPicker
      entries={list}
      total={history.data?.total ?? null}
      loading={history.isPending}
      selectedId={effectiveId}
      selected={selected}
      kind={kind}
      name={name}
      onKind={setKind}
      onName={setName}
      onPick={(id) => useResultsStore.getState().openCampaign(id)}
    />
  );

  let body: React.ReactNode;
  if (!cluster || operatorUrl === null) {
    body = (
      <EmptyState title="No cluster selected">
        <p>Select a cluster in the left pane to see the results of its campaigns and workbench runs.</p>
      </EmptyState>
    );
  } else if (history.isError && effectiveId === null) {
    const unreachable = history.error instanceof OperatorApiError && history.error.unreachable;
    body = (
      <EmptyState
        title={unreachable ? "The master cannot be reached" : "Campaign History cannot be listed"}
        tone="error"
        action={
          <button type="button" className="primary-btn accent" onClick={() => void history.refetch()}>
            Try again
          </button>
        }
      >
        <p>{describeOperatorError(history.error)}</p>
        {unreachable && <p>The Cluster section shows how to open the SSH tunnel to the master&apos;s operator API.</p>}
      </EmptyState>
    );
  } else if (history.isPending && effectiveId === null) {
    body = (
      <p className="meta" role="status">
        Loading Campaign History.
      </p>
    );
  } else if (effectiveId === null) {
    body =
      kind !== "any" || nameFilter !== "" ? (
        <EmptyState title="No entry matches">
          <p>No entry of Campaign History has this kind and name. Change the filters above.</p>
        </EmptyState>
      ) : (
        <EmptyState title="No entry yet">
          <p>Start a campaign in the Campaigns section or run a step in the workbench; its findings appear here as the cases finish.</p>
        </EmptyState>
      );
  } else if (gone) {
    body = (
      <EmptyState
        title="This entry no longer exists"
        action={
          <button type="button" className="primary-btn accent" onClick={() => useResultsStore.getState().reset()}>
            Show the newest entry
          </button>
        }
      >
        <p>Someone deleted it from Campaign History.</p>
      </EmptyState>
    );
  } else if (selected === null) {
    // The steps come from the entry: wait for it rather than showing the full chain.
    body = detail.isError ? (
      <div className="results-notice results-notice--bad" role="alert">
        <strong>The entry cannot be loaded.</strong>
        <span>{describeOperatorError(detail.error)}</span>
      </div>
    ) : (
      <p className="meta" role="status">
        Loading the entry.
      </p>
    );
  } else if (caseId !== null) {
    body = (
      <CasePage
        key={`${effectiveId}:${caseId}`}
        operatorUrl={operatorUrl}
        campaignId={effectiveId}
        caseId={caseId}
        steps={steps}
        onBack={() => useResultsStore.getState().closeCase()}
      />
    );
  } else {
    body = (
      <div className="results-stack">
        <EntryHeader entry={selected} />
        {!legacy && <StepTabs steps={steps} shown={step} onPick={(next) => useResultsStore.getState().setStep(next)} />}
        <div className="results-stack" id="results-step-panel" role={legacy ? undefined : "tabpanel"} aria-labelledby={legacy ? undefined : `results-step-${step}`}>
          {!legacy && <FindingsPanel findings={findings.data} loading={findings.isFetching} error={findings.error} />}
          {awaitingFindings ? null : unmonitored ? (
            <section className="results-panel" aria-label="Monitor summaries">
              <p className="meta">
                No monitor judged {STEP_LABEL[step].toLowerCase()} in this entry, so there are no monitor summaries to list. The outputs of the step are in Campaign History.
              </p>
              <button type="button" className="results-back" onClick={() => useUiStore.getState().setSection("history")}>
                Open Campaign History
              </button>
            </section>
          ) : (
            <VerdictBrowser key={`${effectiveId}:${step}`} operatorUrl={operatorUrl} campaignId={effectiveId} step={step} stepFilter={!legacy} />
          )}
        </div>
      </div>
    );
  }

  return (
    <SectionFrame title="Results" subtitle="Monitor findings of an entry of Campaign History, per executed step, down to the recorded run of one case." actions={picker}>
      {body}
    </SectionFrame>
  );
}
