import { Disclosure } from "../../../components/Disclosure";
import { Field, FieldIssues, NumberField } from "./fields";
import { reasonsOfEntry, splitByField } from "./reasons";
import type { StepProps } from "./stepTypes";
import type { RetentionPolicy } from "./wizardState";

const RETENTION: { value: RetentionPolicy; label: string; description: string }[] = [
  { value: "all", label: "Keep everything", description: "Every artifact of every case is kept." },
  { value: "failures", label: "Keep failures", description: "Trajectories and state logs are kept only for failed monitor result summaries and failed cases." },
  { value: "verdicts_only", label: "Monitor result summaries only", description: "No artifacts once a case has its monitor result summaries. A recorded run cannot be replayed afterwards." },
];

/** Policy: what is kept, the campaign seed and the conditions that end the campaign early. */
export function PolicyStep({ draft, update, reasons }: StepProps) {
  const { policy } = draft;
  const own = splitByField(reasonsOfEntry(reasons, null), ["retention", "keep_frames", "seed", "stop"]);
  const stopIssues = (key: string) => own.byField.get("stop")?.filter((reason) => reason.field === `stop.${key}`);

  return (
    <div className="wiz-step">
      <fieldset className="wiz-choice">
        <legend>Retention</legend>
        {RETENTION.map((option) => (
          <label key={option.value} className={`wiz-option${policy.retention === option.value ? " wiz-option--on" : ""}`}>
            <input type="radio" name="wiz-retention" checked={policy.retention === option.value} onChange={() => update((next) => void (next.policy.retention = option.value))} />
            <span>
              <strong>{option.label}</strong>
              <span className="wiz-hint">{option.description}</span>
            </span>
          </label>
        ))}
        <FieldIssues reasons={own.byField.get("retention")} />
      </fieldset>

      <div className="wiz-row">
        <Field label="Monitor frames" htmlFor="wiz-frames" hint="Store the monitor's frames of each case as artifacts. They are large; without them a recorded run's frames are computed on demand." issues={own.byField.get("keep_frames")}>
          <label className="wiz-check">
            <input id="wiz-frames" type="checkbox" checked={policy.keepFrames} onChange={(event) => update((next) => void (next.policy.keepFrames = event.target.checked))} />
            keep_frames
          </label>
        </Field>
        <Field
          label="Base seed"
          htmlFor="wiz-seed"
          hint="Case k of every FEC runs with this seed + k in every step: scene generation, trajectory generation and each run (unless the run sets its own seed). The same seed gives the same cases."
          issues={own.byField.get("seed")}
        >
          <NumberField id="wiz-seed" integer min={0} max={2147483647} value={policy.seed} invalid={own.byField.has("seed")} onChange={(value) => update((next) => void (next.policy.seed = value))} />
        </Field>
      </div>

      <Disclosure
        id="wizard:policy:stop"
        title="Stop conditions"
        hint="optional, none set by default"
        forceOpen={own.byField.has("stop")}
        headingLevel={4}
      >
        <p className="meta wiz-explain">Optional. The first one reached ends the campaign: no new cases after the case limit, a drain after the failed monitor result summary limit or the duration.</p>
        <div className="wiz-row">
          <Field label="Most cases" htmlFor="wiz-max-cases" hint="No new cases after this many, over all FECs." issues={stopIssues("max_cases")}>
            <NumberField id="wiz-max-cases" integer min={1} value={policy.maxCases} placeholder="no limit" onChange={(value) => update((next) => void (next.policy.maxCases = value))} />
          </Field>
          <Field label="Most failed monitor result summaries" htmlFor="wiz-max-failed" hint="Drain once this many monitor result summaries failed." issues={stopIssues("max_failed_verdicts")}>
            <NumberField id="wiz-max-failed" integer min={1} value={policy.maxFailedVerdicts} placeholder="no limit" onChange={(value) => update((next) => void (next.policy.maxFailedVerdicts = value))} />
          </Field>
          <Field label="Longest run" htmlFor="wiz-max-duration" hint="Drain after the campaign has run this long." issues={stopIssues("max_duration_s")}>
            <NumberField id="wiz-max-duration" min={1} suffix="s" value={policy.maxDurationS} placeholder="no limit" onChange={(value) => update((next) => void (next.policy.maxDurationS = value))} />
          </Field>
        </div>
      </Disclosure>
      <FieldIssues reasons={own.rest} showField />
    </div>
  );
}
