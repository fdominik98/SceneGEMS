import { describeOperatorError } from "../../../domain/cluster/operatorApi";
import { Disclosure } from "../../../components/Disclosure";
import { Field, FieldIssues, MonitorChoice, ParameterInput } from "./fields";
import { reasonsOfEntry, splitByField } from "./reasons";
import type { CatalogState, StepProps } from "./stepTypes";

/** Trajectory generation: the generator and its parameters, built from the generators the master offers, and the monitor after the step. */
export function TrajectoriesStep({ draft, update, reasons, catalog }: StepProps & { catalog: CatalogState }) {
  const generators = catalog.stacks?.trajectory_generators ?? [];
  const generator = generators.find((entry) => entry.id === draft.trajectories.generator);
  const own = reasonsOfEntry(reasons, null);
  const paramKeys = generator?.parameters.map((parameter) => parameter.key) ?? [];
  const { byField, rest } = splitByField(own, ["generator", "timeout_s", "monitor", "params", ...paramKeys]);

  const issuesOfParameter = (key: string) => [...(byField.get(key) ?? []), ...(byField.get("params")?.filter((reason) => reason.field === `params.${key}`) ?? [])];

  if (catalog.stacksLoading) {
    return <p className="meta" role="status">Loading the generators the master offers...</p>;
  }
  if (catalog.stacksError || !catalog.stacks) {
    return (
      <div className="wiz-error" role="alert">
        <p>The master's generators did not load: {describeOperatorError(catalog.stacksError)}</p>
        <button type="button" onClick={catalog.retry}>
          Try again
        </button>
      </div>
    );
  }

  return (
    <div className="wiz-step">
      <fieldset className="wiz-choice">
        <legend>Trajectory generator</legend>
        {generators.map((entry) => (
          <label key={entry.id} className={`wiz-option${draft.trajectories.generator === entry.id ? " wiz-option--on" : ""}`}>
            <input
              type="radio"
              name="wiz-generator"
              checked={draft.trajectories.generator === entry.id}
              onChange={() =>
                update((next) => {
                  if (next.trajectories.generator !== entry.id) {
                    next.trajectories.generator = entry.id;
                    next.trajectories.parameters = {};
                  }
                })
              }
            />
            <span>
              <strong>{entry.label}</strong>
              <span className="wiz-hint">{entry.description}</span>
            </span>
          </label>
        ))}
        {!generator && <p className="error">The master offers no generator {draft.trajectories.generator}. Choose one of the above.</p>}
        <FieldIssues reasons={byField.get("generator")} />
      </fieldset>

      {generator && (
        <Disclosure
          id="wizard:trajectories:parameters"
          title={`${generator.label} parameters`}
          hint={`${Object.keys(draft.trajectories.parameters).length} changed from the defaults`}
          forceOpen={generator.parameters.some((parameter) => (issuesOfParameter(parameter.key)?.length ?? 0) > 0)}
          headingLevel={4}
        >
          <p className="meta wiz-explain">
            {generator.params_field
              ? "Only the values you enter are written to the config; the others keep the search's own defaults."
              : "These values go into the trajectories section of the config."}
          </p>
          <div className="wiz-params">
            {generator.parameters.map((parameter) => (
              <ParameterInput
                key={parameter.key}
                parameter={parameter}
                value={draft.trajectories.parameters[parameter.key]}
                issues={issuesOfParameter(parameter.key)}
                onChange={(value) =>
                  update((next) => {
                    if (value === undefined) {
                      delete next.trajectories.parameters[parameter.key];
                    } else {
                      next.trajectories.parameters[parameter.key] = value;
                    }
                  })
                }
              />
            ))}
          </div>
        </Disclosure>
      )}

      {generator?.common_parameters.map((parameter) => (
        <ParameterInput
          key={parameter.key}
          parameter={parameter}
          value={draft.trajectories.timeoutS}
          issues={byField.get(parameter.key)}
          onChange={(value) => update((next) => void (next.trajectories.timeoutS = typeof value === "number" ? value : null))}
        />
      ))}
      {!generator && (
        <Field label="timeout_s" hint="How long a trajectory generation job may take.">
          <span className="meta">Choose a generator first.</span>
        </Field>
      )}
      <MonitorChoice
        name="wiz-trajectory-monitor"
        legend="Monitor after trajectory generation"
        output="trajectories as planned"
        value={draft.trajectoryMonitor}
        onChange={(value) => update((next) => void (next.trajectoryMonitor = value))}
      />
      <FieldIssues reasons={byField.get("monitor")} />
      <FieldIssues reasons={rest} showField />
    </div>
  );
}
