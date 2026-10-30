import type { StepMonitor } from "../../../domain/cluster/campaignApi";
import type { CampaignStep } from "../../../domain/cluster/schemas";
import { Field, FieldIssues } from "./fields";
import { reasonsOfEntry, splitByField } from "./reasons";
import { CAMPAIGN_STEP_LABELS, CAMPAIGN_STEP_OUTPUTS, CHAIN, firstStep, itemKindsFor, lastStep, runsStep, stepRange } from "./stepPlan";
import type { StepProps } from "./stepTypes";

const STEP_HINTS: Record<CampaignStep, string> = {
  scene_generation: "Generates scenes from FECs of the catalog or from functional scenario files.",
  trajectory_generation: "Plans the trajectories of scenes, generated here or taken from Campaign History or files.",
  simulation: "Simulates trajectories, generated here or taken from Campaign History or files, once per run you define.",
};

const MONITOR_CHOICES: { value: StepMonitor; label: string; hint: (output: string) => string }[] = [
  { value: "empty", label: "No monitor", hint: (output) => `The ${output} are kept without a verdict.` },
  { value: "post_hoc", label: "Post hoc monitor", hint: (output) => `The COLREGS monitor judges the ${output} after the step.` },
];

function MonitorChoice({ name, legend, output, value, onChange }: { name: string; legend: string; output: string; value: StepMonitor; onChange: (value: StepMonitor) => void }) {
  return (
    <fieldset className="wiz-choice">
      <legend>{legend}</legend>
      {MONITOR_CHOICES.map((choice) => (
        <label key={choice.value} className={`wiz-option${value === choice.value ? " wiz-option--on" : ""}`}>
          <input type="radio" name={name} checked={value === choice.value} onChange={() => onChange(choice.value)} />
          <span>
            <strong>{choice.label}</strong>
            <span className="wiz-hint">{choice.hint(output)}</span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

/** Steps: the campaign's name, the consecutive part of the chain it runs and the monitor after each generation step. */
export function StepsStep({ draft, update, reasons }: StepProps) {
  const first = firstStep(draft.steps);
  const last = lastStep(draft.steps);
  const own = splitByField(reasonsOfEntry(reasons, null), ["name", "description", "steps", "scene_generation.monitor", "trajectories.monitor"]);

  const choose = (nextFirst: CampaignStep, nextLast: CampaignStep) =>
    update((next) => {
      next.steps = stepRange(nextFirst, nextLast);
      // Items of the wrong kind for the new first step cannot be used: leave them out
      const kinds = itemKindsFor(next.steps);
      next.input.items = next.input.items.filter((item) => kinds.includes(item.ref.kind));
    });

  return (
    <div className="wiz-step">
      <div className="wiz-columns">
        <div className="wiz-column">
          <Field label="Name" htmlFor="wiz-name" hint="Shown in Campaign History." issues={own.byField.get("name")}>
            <input id="wiz-name" type="text" value={draft.name} maxLength={256} placeholder="head-on scenes, planned" onChange={(event) => update((next) => void (next.name = event.target.value))} />
          </Field>
          <Field label="Description" htmlFor="wiz-description" hint="Optional." issues={own.byField.get("description")}>
            <textarea id="wiz-description" rows={2} value={draft.description} onChange={(event) => update((next) => void (next.description = event.target.value))} />
          </Field>
        </div>
        <div className="wiz-column">
          <p className="wiz-notice" role="note">
            A campaign runs one, two or all three steps of the chain scene generation, trajectory generation, simulation, always next to each other. It starts with the first step you choose and stops after the last.
          </p>
        </div>
      </div>

      <div className="wiz-row">
        <fieldset className="wiz-choice">
          <legend>Start with</legend>
          {CHAIN.map((step) => (
            <label key={step} className={`wiz-option${first === step ? " wiz-option--on" : ""}`}>
              <input type="radio" name="wiz-first-step" checked={first === step} onChange={() => choose(step, CHAIN.indexOf(last) < CHAIN.indexOf(step) ? step : last)} />
              <span>
                <strong>{CAMPAIGN_STEP_LABELS[step]}</strong>
                <span className="wiz-hint">{STEP_HINTS[step]}</span>
              </span>
            </label>
          ))}
        </fieldset>
        <fieldset className="wiz-choice">
          <legend>Stop after</legend>
          {CHAIN.map((step) => {
            const before = CHAIN.indexOf(step) < CHAIN.indexOf(first);
            return (
              <label key={step} className={`wiz-option${last === step ? " wiz-option--on" : ""}${before ? " wiz-option--off" : ""}`}>
                <input type="radio" name="wiz-last-step" disabled={before} checked={last === step} onChange={() => choose(first, step)} />
                <span>
                  <strong>{CAMPAIGN_STEP_LABELS[step]}</strong>
                  <span className="wiz-hint">{before ? "Comes before the first step." : `Produces ${CAMPAIGN_STEP_OUTPUTS[step]}.`}</span>
                </span>
              </label>
            );
          })}
        </fieldset>
      </div>
      <FieldIssues reasons={own.byField.get("steps")} />

      <p className="wiz-plan" role="status" aria-label="The chosen steps">
        This campaign runs <strong>{draft.steps.map((step) => CAMPAIGN_STEP_LABELS[step].toLowerCase()).join(", then ")}</strong>.
        {first !== "scene_generation" && " Its input comes from earlier results or files (next page)."}
      </p>

      {runsStep(draft.steps, "scene_generation") && (
        <>
          <MonitorChoice name="wiz-scene-monitor" legend="Monitor after scene generation" output={CAMPAIGN_STEP_OUTPUTS.scene_generation} value={draft.sceneMonitor} onChange={(value) => update((next) => void (next.sceneMonitor = value))} />
          <FieldIssues reasons={own.byField.get("scene_generation.monitor")} />
        </>
      )}
      {runsStep(draft.steps, "trajectory_generation") && (
        <>
          <MonitorChoice name="wiz-trajectory-monitor" legend="Monitor after trajectory generation" output="trajectories as planned" value={draft.trajectoryMonitor} onChange={(value) => update((next) => void (next.trajectoryMonitor = value))} />
          <FieldIssues reasons={own.byField.get("trajectories.monitor")} />
        </>
      )}
      {runsStep(draft.steps, "simulation") && (
        <p className="meta">Simulated runs are monitored per run: the Runs page sets the monitor of each run (post hoc, live or none).</p>
      )}
      <FieldIssues reasons={own.rest} showField />
    </div>
  );
}
