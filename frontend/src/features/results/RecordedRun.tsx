import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createFramesApi, isFramesBusy, runFramesFlow, type FramesPhase } from "../../domain/cluster/framesApi";
import { createOperatorClient } from "../../domain/cluster/operatorApi";
import type { RunRecord, Verdict } from "../../domain/cluster/schemas";
import { describeFramesPhase } from "./framesText";
import { formatTime, runLabel } from "./resultsFormat";
import { EncounterView } from "../encounter/EncounterView";

interface RecordedRunProps {
  operatorUrl: string;
  campaignId: string;
  runRecord: RunRecord;
  /** The run's verdict; the view opens at its first failure. */
  verdict?: Verdict | null;
  title: string;
  /** Request the frames as soon as the panel shows. */
  autoStart?: boolean;
}

function PhaseProgress({ phase }: { phase: FramesPhase }) {
  const job = "job" in phase ? phase.job : null;
  const fraction = job?.progress?.progress ?? null;
  return (
    <div className="run-progress" role="status" aria-live="polite">
      <span className="run-spinner" aria-hidden="true" />
      <div className="run-progress-text">
        <span>{describeFramesPhase(phase)}</span>
        {job && (
          <span className="meta">
            job {job.job_id.slice(0, 8)}, {job.state}
            {job.attempt > 1 ? `, attempt ${job.attempt} of ${job.max_attempts}` : ""}
            {job.lease_owner ? `, on ${job.lease_owner}` : ""}
          </span>
        )}
        {phase.phase === "running" && fraction !== null && <progress value={fraction} max={1} aria-label="Monitoring progress" />}
      </div>
    </div>
  );
}

/** "Show the run" for one run record: asks the control node for the frames, follows the job and plays the frames. */
export function RecordedRun({ operatorUrl, campaignId, runRecord, verdict, title, autoStart = false }: RecordedRunProps) {
  const [phase, setPhase] = useState<FramesPhase>({ phase: "idle" });
  const controller = useRef<AbortController | null>(null);
  const client = useMemo(() => createOperatorClient(operatorUrl), [operatorUrl]);
  const runRecordId = runRecord.run_record_id;

  const stop = useCallback(() => {
    controller.current?.abort();
    controller.current = null;
  }, []);

  // `retry` asks the control node for a new job when the last one failed or was cancelled; a job that runs or succeeded is returned as it is.
  const start = useCallback(
    (retry: boolean) => {
      stop();
      const abort = new AbortController();
      controller.current = abort;
      void runFramesFlow(createFramesApi(client, campaignId, runRecordId), {
        signal: abort.signal,
        onUpdate: setPhase,
        retry,
      });
    },
    [client, campaignId, runRecordId, stop]
  );

  // The parent keys this panel by run record, so another run starts clean; leaving ends the request.
  useEffect(() => {
    if (autoStart) {
      start(false);
    }
    return stop;
  }, [autoStart, start, stop]);

  const busy = isFramesBusy(phase);
  const hasStateLog = "state_log" in runRecord.artifacts;

  return (
    <section className="results-panel recorded-run" aria-label={`Recorded run of run record ${runRecordId}`}>
      <header className="results-panel-head">
        <h3>Recorded run</h3>
        <span className="meta">
          {runLabel(runRecord.run_index, runRecord.repeat_index)}, recorded {formatTime(runRecord.created_at)}
        </span>
        <span className="results-spacer" />
        {phase.phase === "done" ? (
          <button type="button" onClick={() => setPhase({ phase: "idle" })}>
            Hide
          </button>
        ) : (
          <button type="button" className="primary-btn accent" onClick={() => start(phase.phase !== "idle")} disabled={busy}>
            {busy ? "Working" : phase.phase === "idle" ? "Show the run" : "Try again"}
          </button>
        )}
        {busy && (
          <button
            type="button"
            onClick={() => {
              stop();
              setPhase({ phase: "idle" });
            }}
          >
            Stop waiting
          </button>
        )}
      </header>

      {phase.phase === "idle" && (
        <p className="meta">
          The control node replays the stored state log through the monitor and returns the frames
          {hasStateLog ? "." : ", but this run record lists no state log, so the control node may refuse."}
        </p>
      )}
      {busy && <PhaseProgress phase={phase} />}
      {phase.phase === "unavailable" && (
        <div className="results-notice results-notice--warn" role="alert">
          <strong>This run cannot be shown.</strong>
          <span>{phase.message}</span>
          <span className="meta">
            The state log of a run is kept only while the campaign&apos;s retention keeps it; without it the control node cannot compute frames. The monitor result summary and the
            rule outcomes stay available.
          </span>
        </div>
      )}
      {phase.phase === "failed" && (
        <div className="results-notice results-notice--bad" role="alert">
          <strong>The monitoring job did not finish.</strong>
          <span>{phase.message}</span>
          <span className="meta">The control node submits a new monitoring job when you run it again; if the cause is on the cluster, resolve it there first.</span>
          <button type="button" onClick={() => start(true)}>
            Run the job again
          </button>
        </div>
      )}
      {phase.phase === "error" && (
        <div className="results-notice results-notice--bad" role="alert">
          <strong>{phase.unreachable ? "The control node cannot be reached." : "The frames could not be loaded."}</strong>
          <span>{phase.message}</span>
        </div>
      )}
      {phase.phase === "done" && (
        <EncounterView
          frames={phase.frames}
          timeStep={phase.frames[0]?.timeStep ?? null}
          title={title}
          initialTimestamp={verdict?.first_failure_time_s ?? undefined}
        />
      )}
    </section>
  );
}
