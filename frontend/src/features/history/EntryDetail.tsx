import { useEffect, useState } from "react";
import { Disclosure } from "../../components/Disclosure";
import { isExploredFec } from "../../domain/designSpace/explorationResult";
import { describeOperatorError } from "../../domain/cluster/operatorApi";
import type { CampaignDetail as CampaignDetailView, CampaignStep } from "../../domain/cluster/schemas";
import { showCampaignResults } from "../results/showResults";
import { formatDateTime, plural, runDuration } from "../campaigns/campaignFormat";
import { baseSeed, campaignProgress, isFinalState, runNames, stepMonitored } from "./campaignModel";
import { EmptyState, ProgressBar, StateBadge, Tile, ToneBadge } from "./campaignParts";
import { ConfigPanel, type ConfigVersion } from "./ConfigPanel";
import { ControlsBar } from "./ControlsBar";
import { CoverageTable } from "./CoverageTable";
import { DeleteEntry } from "./DeleteEntry";
import { EventsFeed } from "./EventsFeed";
import { ExploredFecOutputs } from "./ExploredFecOutputs";
import { FailureReasons } from "./FailureReasons";
import { entryKind, entrySteps, initialStep, KIND_LABELS, originLabel, STEP_LABELS, STEP_OUTPUT_NOUNS, stepsRangeLabel } from "./historyModel";
import { MadeFrom } from "./historyParts";
import { StepOutputs } from "./StepOutputs";
import { useCampaignConfig, useCampaignEvents, useCampaignFeed, useStartBlocker } from "./useCampaignFeed";
import { useKnownEntryNames } from "./useHistoryData";
import { useLoadIntoWizard } from "./useLoadIntoWizard";

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
  // A campaign that only explores the design space: its FECs are closed complete at once, with no cases to count
  const exploredOnly = detail.steps?.length === 1 && detail.steps[0] === "design_space_exploration";
  if (exploredOnly) {
    const explored = detail.fecs.filter((entry) => isExploredFec(entry.fec_id)).length;
    return (
      <div className="stat-tiles camp-tiles">
        <Tile label="Explored FECs" value={explored} detail="The campaign runs no step after the exploration, so they need no cases." />
      </div>
    );
  }
  // The totals count the scenarios' cases, not the exploration's own: until it found its FECs there is nothing to count
  const exploring = detail.steps?.[0] === "design_space_exploration" && !isFinalState(detail.actual_state) && !detail.fecs.some((entry) => isExploredFec(entry.fec_id));
  return (
    <>
      <div className="stat-tiles camp-tiles">
        <div className="stat-tile camp-tile-wide">
          <span className="stat-tile-label">Complete cases</span>
          <span className="stat-tile-value">
            {progress.complete} <span className="camp-tile-of">of {progress.quota}</span>
          </span>
          <ProgressBar fraction={progress.fraction} tone={detail.actual_state === "completed" ? "ok" : "info"} />
          {exploring ? (
            <span className="stat-tile-detail">The design space exploration is finding the FECs; their cases follow.</span>
          ) : (
            <span className="stat-tile-detail">
              {progress.inFlight} in flight
              {/* The control node's count holds the dropped and the failed cases */}
              {progress.dropped > 0 ? `, ${progress.dropped} dropped or failed (they count against the failure budgets)` : ""}
            </span>
          )}
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
          <Tile label="Dropped or failed" value={progress.dropped} detail="count against the failure budgets" tone={progress.dropped > 0 ? "warn" : undefined} />
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
 * One entry of Campaign History, what matters first: its name and state with the way to its
 * results, the controls that apply to a campaign now, the numbers, why cases did not complete, a
 * tab per executed step with its outputs, and for campaigns the coverage per class, the activity
 * log and the config. Who made the entry, its input, seed, id and times are under Entry details.
 * The numbers follow `campaign:<id>`.
 */
export function EntryDetail({ campaignId, step: rememberedStep, onStep, onBack, onOpenEntry }: EntryDetailProps) {
  const feed = useCampaignFeed(campaignId);
  const events = useCampaignEvents(campaignId, feed.lastEventId, feed.pushedEvents, feed.source === "poll");
  const config = useCampaignConfig(campaignId);
  const { detail } = feed;
  const startBlocker = useStartBlocker(config.data);
  const knownNames = useKnownEntryNames();
  const wizard = useLoadIntoWizard();

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
          <p className="meta">{feed.error ? describeOperatorError(feed.error) : `No entry ${campaignId} on this control node. It may have been deleted.`}</p>
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
  const madeFrom = detail.made_from ?? [];
  // A campaign's config can start a new campaign in the wizard; a workbench run is run again on its workbench page
  const stored = config.data;
  const currentConfig = stored?.versions.find((version) => version.version === stored.current_version);
  const loadVersion = (version: ConfigVersion) => wizard.load(version.config, { name: detail.name, version: version.version });
  const loadBlocker = wizard.blocker ?? (currentConfig ? null : config.isLoading ? "Reading the config" : "The config did not load");

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
            title={feed.source === "live" ? "Coverage and events arrive over the live channel." : "The live channel is not delivering; the page polls the control node every 4 s."}
          >
            {feed.source === "live" ? "live" : feed.liveStatus === "error" ? "polling, live channel refused" : "polling"}
          </span>
        </div>
        <p className="history-entry-line">
          {stepsRangeLabel(steps)}, <RunDuration startedAt={detail.started_at} finishedAt={detail.finished_at} prefix={final ? "ran for " : "running for "} />
          {madeFrom.length > 0 && (
            <>
              , made from <MadeFrom ids={madeFrom} names={knownNames} onOpen={onOpenEntry} />
            </>
          )}
        </p>
        {detail.state_reason && (
          <p className={`camp-state-reason camp-state-reason--${detail.actual_state}`} role="status">
            <strong>{detail.actual_state === "stalled" ? "Why it is stalled." : "State reason."}</strong> {detail.state_reason}
          </p>
        )}
        <div className="camp-results-link">
          <button type="button" className="primary-btn accent" onClick={() => showCampaignResults(campaignId)} title="Findings, monitor result summaries, cases and recorded runs are in the Results section">
            Open the results
          </button>
          {isCampaign && (
            <button
              type="button"
              disabled={loadBlocker !== null}
              title={loadBlocker ?? "Start a new campaign from this config in the Campaigns section: run it again, or adjust it first"}
              onClick={() => currentConfig && loadVersion(currentConfig)}
            >
              Load the config into the wizard
            </button>
          )}
          {final && <DeleteEntry entry={detail} onDeleted={onBack} />}
        </div>
        <Disclosure id="campaign:details" variant="link" headingLevel={null} title="Entry details" openTitle="Hide entry details" hint="origin, input, seed, id, times">
          <dl className="camp-facts">
            <div>
              <dt>Made by</dt>
              <dd>{originLabel(detail.origin)}</dd>
            </div>
            <div>
              <dt>Made from</dt>
              <dd>
                <MadeFrom ids={madeFrom} names={knownNames} onOpen={onOpenEntry} />
              </dd>
            </div>
            <div>
              <dt>Input</dt>
              <dd>
                {detail.input && detail.input.item_count > 0
                  ? `${plural(detail.input.item_count, "item")} for ${STEP_LABELS[detail.input.first_step].toLowerCase()}`
                  : steps[0] === "design_space_exploration"
                    ? "the FECs of the design space exploration"
                    : steps[0] === "scene_generation"
                      ? "catalog FECs or scenarios"
                      : "not reported"}
              </dd>
            </div>
            <div title="Case k of every FEC runs with this seed + k in every step">
              <dt>Base seed</dt>
              <dd className="mono">{seed ?? (config.isLoading ? "loading" : "not reported")}</dd>
            </div>
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
      </div>
      {feed.error && <p className="meta warning">The numbers may be stale: {describeOperatorError(feed.error)}</p>}
      {isCampaign && <ControlsBar campaign={detail} onChanged={feed.applySummary} startBlocker={startBlocker} />}
      <Totals detail={detail} />
      <FailureReasons campaignId={campaignId} count={detail.totals.dropped} running={!final} />
      <section className="panel history-steps" aria-label="Outputs per step">
        <StepTabs steps={steps} step={step} onSelect={onStep} />
        <div id="history-step-panel" role="tabpanel" aria-labelledby={`history-tab-${step}`}>
          <h4 className="history-step-title">
            {STEP_LABELS[step]}: {STEP_OUTPUT_NOUNS[step].many}
          </h4>
          {step === "design_space_exploration" ? (
            <ExploredFecOutputs key={step} campaignId={campaignId} running={!final} />
          ) : (
            <StepOutputs key={step} campaignId={campaignId} step={step} running={!final} monitored={stepMonitored(config.data, step)} onOpenEntry={onOpenEntry} />
          )}
        </div>
      </section>
      {isCampaign && <CoverageTable classes={detail.fecs} runNames={names} />}
      <Disclosure id="campaign:events" title="Activity log" hint={`${events.length} ${events.length === 1 ? "event" : "events"}${feed.source === "live" ? ", live" : ""}`} headingLevel={3}>
        <EventsFeed events={events} live={feed.source === "live"} />
      </Disclosure>
      <ConfigPanel config={config.data} error={config.error} loading={config.isLoading} onLoad={isCampaign ? loadVersion : undefined} loadBlocker={wizard.blocker} />
    </div>
  );
}
