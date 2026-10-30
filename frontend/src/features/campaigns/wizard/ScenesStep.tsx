import { Field, FieldIssues, MonitorChoice, NumberField } from "./fields";
import { reasonsOfEntry, splitByField } from "./reasons";
import { CAMPAIGN_STEP_OUTPUTS } from "./stepPlan";
import type { StepProps } from "./stepTypes";

/**
 * Scene generation: the monitor after the step and the generation's own settings. The timeout and the low TCPA option
 * are fields of the config's domain section, written only while the campaign generates scenes.
 */
export function ScenesStep({ draft, update, reasons }: StepProps) {
  const { domain } = draft;
  const own = splitByField(reasonsOfEntry(reasons, null), ["monitor", "scene_generation_timeout_s", "enforce_low_tcpa"]);

  return (
    <div className="wiz-step">
      <p className="meta wiz-explain">Scene generation turns each FEC of the input into concrete scenes, one per case.</p>
      <MonitorChoice
        name="wiz-scene-monitor"
        legend="Monitor after scene generation"
        output={CAMPAIGN_STEP_OUTPUTS.scene_generation}
        value={draft.sceneMonitor}
        onChange={(value) => update((next) => void (next.sceneMonitor = value))}
      />
      <FieldIssues reasons={own.byField.get("monitor")} />
      <div className="wiz-row">
        <Field label="Scene generation timeout" htmlFor="wiz-scene-timeout" hint="The generation's own time limit for one scene." issues={own.byField.get("scene_generation_timeout_s")}>
          <NumberField
            id="wiz-scene-timeout"
            integer
            min={1}
            suffix="s"
            value={domain.sceneGenerationTimeoutS}
            invalid={own.byField.has("scene_generation_timeout_s")}
            onChange={(value) => update((next) => void (next.domain.sceneGenerationTimeoutS = value))}
          />
        </Field>
        <Field label="Enforce low TCPA" htmlFor="wiz-low-tcpa" hint="Scenes are generated with the low time to the closest point of approach enforced." issues={own.byField.get("enforce_low_tcpa")}>
          <label className="wiz-check">
            <input id="wiz-low-tcpa" type="checkbox" checked={domain.enforceLowTcpa} onChange={(event) => update((next) => void (next.domain.enforceLowTcpa = event.target.checked))} />
            enforce_low_tcpa
          </label>
        </Field>
      </div>
      <FieldIssues reasons={own.rest} showField />
    </div>
  );
}
