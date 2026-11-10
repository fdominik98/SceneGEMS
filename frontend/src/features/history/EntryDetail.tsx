import { useEffect, useState } from "react";
import { Disclosure } from "../../components/Disclosure";
import { describeOperatorError } from "../../domain/cluster/operatorApi";
import type { CampaignDetail as CampaignDetailView, CampaignStep } from "../../domain/cluster/schemas";
import { showCampaignResults } from "../results/showResults";
import { formatDateTime, plural, runDuration } from "../campaigns/campaignFormat";
import { baseSeed, campaignProgress, isFinalState, runNames, stepMonitored } from "./campaignModel";
import { EmptyState, ProgressBar, StateBadge, Tile, ToneBadge } from "./campaignParts";
import { ConfigPanel } from "./ConfigPanel";
import { ControlsBar } from "./ControlsBar";
import { CoverageTable } from "./CoverageTable";
import { DeleteEntry } from "./DeleteEntry";
import { EventsFeed } from "./EventsFeed";
import { entryKind, entrySteps, initialStep, KIND_LABELS, originLabel, STEP_LABELS, STEP_OUTPUT_NOUNS } from "./historyModel";
import { MadeFrom } from "./historyParts";
import { StepOutputs } from "./StepOutputs";
import { useCampaignConfig, useCampaignEvents, useCampaignFeed, useStartBlocker } from "./useCampaignFeed";
import { useKnownEntryNames } from "./useHistoryData";

function useNow(intervalMs: number, ticking: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!ticking) {
      return undefined;
    }
    // The clock may have stood still since the entry was shown: catch up at once, then tick
    const first = setTimeout(() => setNow(Date.now()), 0);
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [intervalMs, ticking]);
  return now;
}

/** How long the entry ran; it counts up each second while the entry runs, and only this text renders again. */
export function RunDuration({ startedAt, finishedAt, prefix = "" }: { startedAt: string | null; finishedAt: string | null; prefix?: string }) {
  const now = useNow(1_000, startedAt !== null && finishedAt === null);
  return (
    <>
      {prefix}
      {runDuration(startedAt, finishedAt, now)}
    </>
  );
}

function Totals({ detail }: { detail: CampaignDetailView }) {
  const progress = campaignProgress(detail.totals);
  const { totals } = detail;
  const verdicts = totals.verdicts;
  const failed = verdicts.failed ?? 0;
  return (
    <>
      <div className="stat-tiles camp-tiles">
        <div className="stat-tile camp-tile-wide">
          <span className="stat-tile-label">Complete cases</span>
          <span className="stat-tile-value">
            {progress.complete} <span className="camp-tile-of">of {progress.quota}</span>
          </span>
          <ProgressBar fraction={progress.fraction} tone={detail.actual_state === "completed" ? "ok" : "info"} />
          <span className="stat-tile-detail">
            {progress.inFlight} in flight
            {progress.dropped > 0 ? `, ${progress.dropped} dropped (they count against the failure budgets)` : ""}
          </span>
        </div>
        <Tile
          label="Monitor result summaries"
          value={Object.values(verdicts).reduce((sum, count) => sum + count, 0)}
          detail={`${verdicts.passed ?? 0} passed, ${failed} failed`}
          tone={failed > 0 ? "warn" : undefined}
        />
        {totals.fecs_abandoned > 0 && <Tile label="Abandoned FECs" value={totals.fecs_abandoned} detail="out of failure budget" tone="bad" />}
      </div>
      <Disclosure id="campaign:more-numbers" variant="link" headingLevel={null} title="More numbers" openTitle="Fewer numbers">
        <div className="stat-tiles camp-tiles">
          <Tile label="In flight" value={progress.inFlight} detail="cases being worked on" />
          <Tile label="Dropped" value={progress.dropped} detail="count against the failure budgets" tone={progress.dropped > 0 ? "warn" : undefined} />
          <Tile
            label="FECs"
            value={totals.fecs}
            detail={`${totals.fecs_open} open, ${totals.fecs_complete} complete, ${totals.fecs_abandoned} abandoned`}
            tone={totals.fecs_abandoned > 0 ? "bad" : undefined}
          />
          <Tile label="Unmonitored runs" value={verdicts.unmonitored ?? 0} detail="runs without a monitor result summary" />
        </div>
      </Disclosure>
    </>
  );
}

function StepTabs({ steps, step, onSelect }: { steps: readonly CampaignStep[]; step: CampaignStep; onSelect: (step: CampaignStep) => void }) {
  return (
    <div className="history-tabs" role="tablist" aria-label="Executed steps">
      {steps.map((entry) => (
        <button
          key={entry}
          type="button"
          role="tab"
          id={`history-tab-${entry}`}
          aria-selected={entry === step}
          aria-controls="history-step-panel"
          className={`history-tab${entry === step ? " history-tab--on" : ""}`}
          onClick={() => onSelect(entry)}
        >
          {STEP_LABELS[entry]}
        </button>
      ))}
    </div>
  );
}

export interface EntryDetailProps {
  campaignId: string;
  /** The step tab to show; null opens the last executed step. */
  step: CampaignStep | null;
  onStep: (step: CampaignStep) => void;
  onBack: () => void;
  onOpenEntry: (campaignId: string) => void;
}

/**
 * One entry of Campaign History: the header (kind, origin, made-from links, controls of a
 * campaign, delete once final), a tab per executed step with its outputs, and for campaigns the
 * coverage per class, the activity log and the config. The numbers follow `campaign:<id>`.
 */
export function EntryDetail({ campaignId, step: rememberedStep, onStep, onBack, onOpenEntry }: EntryDetailProps) {
  const feed = useCampaignFeed(campaignId);
  const events = useCampaignEvents(campaignId, feed.lastEventId, feed.pushedEvents, feed.source === "poll");
  const config = useCampaignConfig(campaignId);
  const { detail } = feed;
  const startBlocker = useStartBlocker(config.data);
  const knownNames = useKnownEntryNames();

  const back = (
    <button type="button" className="camp-back" onClick={onBack}>
      Back to the history
    </button>
  );

  if (feed.loading) {
    return (
      <div className="camp-detail">
        {back}
        <p className="meta" role="status">Loading the entry...</p>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="camp-detail">
        {back}
        <EmptyState title="The entry did not load" tone="error">
          <p className="meta">{feed.error ? describeOperatorError(feed.error) : `No entry ${campaignId} on this master. It may have been deleted.`}</p>
          <div>
            <button type="button" onClick={feed.refetch}>
              Try again
            </button>
          </div>
        </EmptyState>
      </div>
    );
  }

  const kind = entryKind(detail);
  const steps = entrySteps(detail);
  const step = initialStep(steps, rememberedStep);
  const names = runNames(config.data);
  const seed = baseSeed(config.data);
  const isCampaign = kind === "campaign";
  const final = isFinalState(detail.actual_state);

  return (
    <div className="camp-detail">
      <div className="camp-detail-head panel">
        <div className="camp-detail-title">
          {back}
          <h3>{detail.name}</h3>
          <ToneBadge tone={isCampaign ? "info" : "idle"}>{KIND_LABELS[kind]}</ToneBadge>
          <StateBadge state={detail.actual_state} desired={detail.desired_state} />
          <span
            className={`camp-badge camp-badge--${feed.source === "live" ? "ok" : "warn"}`}
            title={feed.source === "live" ? "Coverage and events arrive over the live channel." : "The live channel is not delivering; the page polls the master every 4 s."}
          >
            {feed.source === "live" ? "live" : feed.liveStatus === "error" ? "polling, live channel refused" : "polling"}
          </span>
        </div>
        <dl className="camp-facts history-origin">
          <div>
            <dt>Made by</dt>
            <dd>{originLabel(detail.origin)}</dd>
          </div>
          <div>
            <dt>Made from</dt>
            <dd>
              <MadeFrom ids={detail.made_from ?? []} names={knownNames} onOpen={onOpenEntry} />
            </dd>
          </div>
          <div>
            <dt>Input</dt>
            <dd>
              {detail.input && detail.input.item_count > 0
                ? `${plural(detail.input.item_count, "item")} for ${STEP_LABELS[detail.input.first_step].toLowerCase()}`
                : steps[0] === "scene_generation"
                  ? "catalog FECs or scenarios"
                  : "not reported"}
            </dd>
          </div>
          <div title="Case k of every FEC runs with this seed + k in every step">
            <dt>Base seed</dt>
            <dd className="mono">{seed ?? (config.isLoading ? "loading" : "not reported")}</dd>
          </div>
        </dl>
        {detail.state_reason && (
          <p className={`camp-state-reason camp-state-reason--${detail.actual_state}`} role="status">
            <strong>{detail.actual_state === "stalled" ? "Why it is stalled." : "State reason."}</strong> {detail.state_reason}
          </p>
        )}
        <Disclosure
          id="campaign:details"
          variant="link"
          headingLevel={null}
          title="Entry details"
          openTitle="Hide entry details"
          hint={<RunDuration startedAt={detail.started_at} finishedAt={detail.finished_at} prefix="ran for " />}
        >
          <dl className="camp-facts">
            <div>
              <dt>Entry id</dt>
              <dd>
                <code>{detail.campaign_id}</code>
              </dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>{formatDateTime(detail.created_at)}</dd>
            </div>
            <div>
              <dt>Started</dt>
              <dd>{formatDateTime(detail.started_at)}</dd>
            </div>
            <div>
              <dt>Finished</dt>
              <dd>{detail.finished_at ? formatDateTime(detail.finished_at) : "not finished"}</dd>
            </div>
            <div>
              <dt>Ran for</dt>
              <dd>
                <RunDuration startedAt={detail.started_at} finishedAt={detail.finished_at} />
              </dd>
            </div>
            <div>
              <dt>Config</dt>
              <dd>
                version {detail.config_version}
                {steps.includes("simulation") ? `, ${plural(names.length || 1, "run")}` : ""}
              </dd>
            </div>
          </dl>
        </Disclosure>
        <div className="camp-results-link">
          <button type="button" className="primary-btn accent" onClick={() => showCampaignResults(campaignId)} title="Findings, monitor result summaries, cases and recorded runs are in the Results section">
            Open the results
          </button>
          {final && <DeleteEntry entry={detail} onDeleted={onBack} />}
        </div>
      </div>
      {feed.error && <p className="meta warning">The numbers may be stale: {describeOperatorError(feed.error)}</p>}
      {isCampaign && <ControlsBar campaign={detail} onChanged={feed.applySummary} startBlocker={startBlocker} />}
      <Totals detail={detail} />
      <section className="panel history-steps" aria-label="Outputs per step">
        <StepTabs steps={steps} step={step} onSelect={onStep} />
        <div id="history-step-panel" role="tabpanel" aria-labelledby={`history-tab-${step}`}>
          <h4 className="history-step-title">
            {STEP_LABELS[step]}: {STEP_OUTPUT_NOUNS[step].many}
          </h4>
          <StepOutputs key={step} campaignId={campaignId} step={step} running={!final} monitored={stepMonitored(config.data, step)} onOpenEntry={onOpenEntry} />
        </div>
      </section>
      {isCampaign && <CoverageTable classes={detail.fecs} runNames={names} />}
      <Disclosure id="campaign:events" title="Activity log" hint={`${events.length} ${events.length === 1 ? "event" : "events"}${feed.source === "live" ? ", live" : ""}`} headingLevel={3}>
        <EventsFeed events={events} live={feed.source === "live"} />
      </Disclosure>
      <ConfigPanel config={config.data} error={config.error} loading={config.isLoading} />
    </div>
  );
}
