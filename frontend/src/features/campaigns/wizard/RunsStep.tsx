import { Disclosure } from "../../../components/Disclosure";
import { describeOperatorError } from "../../../domain/cluster/operatorApi";
import type { CatalogStack, CatalogStacks } from "../../../domain/cluster/campaignApi";
import { findStack, supportsEnvironment } from "./configBuilder";
import { Field, FieldIssues, NumberField, ParameterInput } from "./fields";
import { reasonsOfEntry, splitByField, type Reason } from "./reasons";
import { StackPicker } from "./StackPicker";
import type { CatalogState, StepProps } from "./stepTypes";
import { emptyRun, newEntryId, type RunDraft } from "./wizardState";

const RUN_FIELDS = ["stack", "name", "seed", "repeats", "monitor", "early_stop"] as const;

function UnavailableStacks({ catalog }: { catalog: CatalogStacks }) {
  const unavailableOffered = catalog.stacks.filter((stack) => !stack.available);
  const others = catalog.unavailable_stacks;
  const count = unavailableOffered.length + others.length;
  if (count === 0) {
    return null;
  }
  return (
    <details className="wiz-unavailable">
      <summary>
        {count} stacks the control node cannot run in a campaign <span className="meta">(why, collapsed)</span>
      </summary>
      <p className="meta">{catalog.note}</p>
      <ul className="wiz-unavailable-list">
        {unavailableOffered.map((stack) => (
          <li key={stack.id}>
            <strong>{stack.label}</strong>
            <span className="wiz-unavailable-reasons">{stack.reasons.join("; ") || "no reason given"}</span>
          </li>
        ))}
        {others.map((stack) => {
          const name = `${stack.asv_system} on ${stack.simulation_layer}${stack.control_layer !== "none" ? ` with ${stack.control_layer}` : ""}`;
          return (
            <li key={`${stack.asv_system}-${stack.control_layer}-${stack.simulation_layer}`}>
              <strong>{name}</strong>
              <span className="wiz-unavailable-status">{stack.status}</span>
              <span className="wiz-unavailable-reasons">{stack.reasons.join("; ") || "no reason given"}</span>
            </li>
          );
        })}
      </ul>
    </details>
  );
}

function RunCard({
  run,
  index,
  catalog,
  stacks,
  reasons,
  canRemove,
  onChange,
  onRemove,
  onDuplicate,
}: {
  run: RunDraft;
  index: number;
  catalog: CatalogStacks;
  stacks: readonly CatalogStack[];
  reasons: readonly Reason[];
  canRemove: boolean;
  onChange: (change: (run: RunDraft) => void) => void;
  onRemove: () => void;
  onDuplicate: () => void;
}) {
  const stack = findStack({ stacks, generators: [] }, run.stackId);
  const monitor = catalog.monitors.find((entry) => entry.id === run.monitor);
  const support = supportsEnvironment(stack);
  const shown = [
    ...RUN_FIELDS,
    ...(support.wind ? ["environment.wind_vector"] : []),
    ...(support.waves ? ["environment.waves"] : []),
    ...(stack?.parameters.map((parameter) => `stack.${parameter.key}`) ?? []),
    ...(stack?.groups.map((group) => `stack.${group.key}`) ?? []),
  ];
  const { byField, rest } = splitByField(reasons, shown);
  const underGroup = (key: string) => byField.get(`stack.${key}`) ?? [];
  const runParameter = (key: string) => catalog.run_parameters.find((parameter) => parameter.key === key);
  const seedParameter = runParameter("seed");
  const repeatsParameter = runParameter("repeats");

  const setStackParameter = (key: string, value: unknown) =>
    onChange((item) => {
      if (value === undefined) {
        delete item.stackParameters[key];
      } else {
        item.stackParameters[key] = value;
      }
    });

  return (
    <section id={`wiz-run-${run.id}`} className={`wiz-card wiz-run${reasons.length > 0 ? " wiz-card--invalid" : ""}`} aria-label={`Run ${index + 1}`}>
      <header className="wiz-card-head">
        <h4>Run {index + 1}{run.name.trim() ? `: ${run.name.trim()}` : ""}</h4>
        <button type="button" onClick={onDuplicate}>
          Duplicate
        </button>
        {canRemove && (
          <button type="button" className="wiz-remove" onClick={onRemove}>
            Remove run
          </button>
        )}
      </header>
      <div className="wiz-row">
        <Field label="Name" htmlFor={`run-name-${run.id}`} hint="Labels the run in the results. Optional." issues={byField.get("name")}>
          <input id={`run-name-${run.id}`} type="text" value={run.name} onChange={(event) => onChange((item) => void (item.name = event.target.value))} />
        </Field>
        <Field label="Stack" htmlFor={`run-stack-${run.id}`} hint={stack ? <>{stack.description} Repeatability: {stack.repeatability_tier ?? "unknown"}.</> : "Browse the stacks the control node offers, by layer, software and what they support."} issues={byField.get("stack")}>
          <StackPicker
            id={`run-stack-${run.id}`}
            stacks={stacks}
            stackId={run.stackId}
            onPick={(stackId) =>
              onChange((item) => {
                item.stackId = stackId;
                if (catalog.stacks.find((entry) => entry.id === item.stackId)?.supports_early_stop === false) {
                  item.earlyStop = false;
                }
                item.stackParameters = {};
                item.groups = {};
                item.windVector = null;
                item.waves = null;
              })
            }
          />
        </Field>
      </div>
      <div className="wiz-row">
        <Field label="Monitor" htmlFor={`run-monitor-${run.id}`} hint={monitor?.description} issues={byField.get("monitor")}>
          <select
            id={`run-monitor-${run.id}`}
            value={run.monitor}
            onChange={(event) =>
              onChange((item) => {
                item.monitor = event.target.value;
                if (!catalog.monitors.find((entry) => entry.id === item.monitor)?.supports_early_stop) {
                  item.earlyStop = false;
                }
              })
            }
          >
            {catalog.monitors.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.label}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label="Early stop"
          htmlFor={`run-early-${run.id}`}
          hint={!stack?.supports_early_stop && stack ? "This stack runs to the end: a run on it does not stop early." : monitor?.supports_early_stop ? "Stop the run once every rule is decided." : "Needs the live monitor."}
          issues={byField.get("early_stop")}
        >
          <label className="wiz-check">
            <input
              id={`run-early-${run.id}`}
              type="checkbox"
              checked={run.earlyStop}
              disabled={!monitor?.supports_early_stop || stack?.supports_early_stop === false}
              onChange={(event) => onChange((item) => void (item.earlyStop = event.target.checked))}
            />
            Stop the run early
          </label>
        </Field>
      </div>
      <div className="wiz-row">
        <Field label="Seed" htmlFor={`run-seed-${run.id}`} hint="One seed for this run in every case. Leave it empty and the run takes the case seed, like the other steps." issues={byField.get("seed")}>
          <NumberField id={`run-seed-${run.id}`} integer min={0} max={seedParameter?.maximum ?? undefined} placeholder="the case seed" value={run.seed} invalid={byField.has("seed")} onChange={(value) => onChange((item) => void (item.seed = value))} />
        </Field>
        <Field label="Repeats" htmlFor={`run-repeats-${run.id}`} hint={repeatsParameter?.description} issues={byField.get("repeats")}>
          <NumberField id={`run-repeats-${run.id}`} integer min={1} value={run.repeats} invalid={byField.has("repeats")} onChange={(value) => onChange((item) => void (item.repeats = value))} />
        </Field>
      </div>

      {stack && stack.parameters.length > 0 && (
        <Disclosure
          id={`wizard:run:${run.id}:stack-parameters`}
          title="Stack parameters"
          hint={`${stack.parameters.length} values`}
          defaultOpen={stack.parameters.some((parameter) => parameter.required)}
          forceOpen={stack.parameters.some((parameter) => (byField.get(`stack.${parameter.key}`)?.length ?? 0) > 0)}
          variant="plain"
          headingLevel={5}
        >
          {stack.parameters.map((parameter) => (
            <ParameterInput key={parameter.key} parameter={parameter} value={run.stackParameters[parameter.key]} issues={byField.get(`stack.${parameter.key}`)} onChange={(value) => setStackParameter(parameter.key, value)} />
          ))}
        </Disclosure>
      )}

      {stack?.groups.map((group) => {
        const values = run.groups[group.key];
        const set = values !== undefined;
        return (
          <Disclosure
            key={group.key}
            id={`wizard:run:${run.id}:group:${group.key}`}
            title={group.label}
            hint={group.optional ? (set ? "set" : "optional") : "required"}
            defaultOpen={!group.optional}
            forceOpen={underGroup(group.key).length > 0}
            variant="plain"
            headingLevel={5}
          >
            {group.optional && (
              <label className="wiz-check">
                <input
                  type="checkbox"
                  checked={set}
                  onChange={(event) =>
                    onChange((item) => {
                      if (event.target.checked) {
                        item.groups[group.key] = {};
                      } else {
                        delete item.groups[group.key];
                      }
                    })
                  }
                />
                Set these values (the same for every case)
              </label>
            )}
            {!set && group.derived_when_absent && <p className="wiz-hint">{group.derived_when_absent}</p>}
            {(set || !group.optional) &&
              group.parameters.map((parameter) => (
                <ParameterInput
                  key={parameter.key}
                  parameter={parameter}
                  value={values?.[parameter.key]}
                  issues={underGroup(group.key).filter((reason) => reason.field === `stack.${group.key}.${parameter.key}`)}
                  onChange={(value) =>
                    onChange((item) => {
                      const target = (item.groups[group.key] ??= {});
                      if (value === undefined) {
                        delete target[parameter.key];
                      } else {
                        target[parameter.key] = value;
                      }
                    })
                  }
                />
              ))}
            <FieldIssues reasons={underGroup(group.key).filter((reason) => !group.parameters.some((parameter) => reason.field === `stack.${group.key}.${parameter.key}`))} />
          </Disclosure>
        );
      })}

      {(support.wind || support.waves) && (
        <Disclosure
          id={`wizard:run:${run.id}:environment`}
          title="Environment"
          hint="wind and waves"
          forceOpen={byField.has("environment.wind_vector") || (byField.get("environment.waves")?.length ?? 0) > 0}
          variant="plain"
          headingLevel={5}
        >
          {support.wind && (
            <ParameterInput
              parameter={{ key: "environment.wind_vector", type: "number_triple", default: null, required: false, description: "Wind [east, north, up].", unit: "m/s" }}
              value={run.windVector ?? undefined}
              issues={byField.get("environment.wind_vector")}
              onChange={(value) => onChange((item) => void (item.windVector = Array.isArray(value) ? (value as number[]) : null))}
            />
          )}
          {support.waves && (
            <WavesInput
              waves={run.waves}
              issues={byField.get("environment.waves") ?? []}
              onChange={(waves) => onChange((item) => void (item.waves = waves))}
            />
          )}
        </Disclosure>
      )}
      <FieldIssues reasons={rest} showField />
    </section>
  );
}

function WavesInput({ waves, onChange, issues }: { waves: Record<string, unknown> | null; onChange: (waves: Record<string, unknown> | null) => void; issues: readonly Reason[] }) {
  const set = waves !== null;
  const number = (key: string) => (typeof waves?.[key] === "number" ? (waves[key] as number) : null);
  const direction = Array.isArray(waves?.direction) ? (waves.direction as number[]) : [];
  return (
    <div className="wiz-waves">
      <label className="wiz-check">
        <input type="checkbox" checked={set} onChange={(event) => onChange(event.target.checked ? {} : null)} />
        Set waves
      </label>
      {set && (
        <div className="wiz-row">
          {(["amplitude", "period", "steepness"] as const).map((key) => (
            <Field key={key} label={key} issues={issues.filter((reason) => reason.field?.endsWith(`.${key}`))}>
              <NumberField value={number(key)} min={0} ariaLabel={key} onChange={(value) => onChange({ ...waves, [key]: value ?? undefined })} />
            </Field>
          ))}
          <Field label="direction" hint="Propagation vector [east, north]; its length is the wave speed." issues={issues.filter((reason) => reason.field?.endsWith(".direction"))}>
            <span className="wiz-tuple">
              {["east", "north"].map((axis, at) => (
                <span key={axis} className="wiz-tuple-part">
                  <span className="wiz-axis">{axis}</span>
                  <NumberField value={typeof direction[at] === "number" ? direction[at] : null} ariaLabel={`direction ${axis}`} onChange={(value) => onChange({ ...waves, direction: [at === 0 ? (value ?? 0) : (direction[0] ?? 0), at === 1 ? (value ?? 0) : (direction[1] ?? 0)] })} />
                </span>
              ))}
            </span>
          </Field>
        </div>
      )}
    </div>
  );
}

/** Runs: one or more, each with a stack, a monitor, a seed, repeats and the stack's own parameters. */
export function RunsStep({ draft, update, reasons, catalog }: StepProps & { catalog: CatalogState }) {
  if (catalog.stacksLoading) {
    return <p className="meta" role="status">Loading the stacks the control node offers...</p>;
  }
  if (catalog.stacksError || !catalog.stacks) {
    return (
      <div className="wiz-error" role="alert">
        <p>The control node's stacks did not load: {describeOperatorError(catalog.stacksError)}</p>
        <button type="button" onClick={catalog.retry}>
          Try again
        </button>
      </div>
    );
  }
  const stacks = catalog.stacks;
  const firstAvailable = stacks.stacks.find((entry) => entry.available);
  const own = reasonsOfEntry(reasons, null);
  const changeRun = (id: string, edit: (run: RunDraft) => void) =>
    update((next) => {
      const found = next.runs.find((run) => run.id === id);
      if (found) {
        edit(found);
      }
    });

  return (
    <div className="wiz-step">
      <p className="meta wiz-explain">
        Every case is simulated once per run (and per repeat). Add more runs to compare stacks, monitors or seeds on the same scenes.
      </p>
      {draft.runs.map((run, index) => (
        <RunCard
          key={run.id}
          run={run}
          index={index}
          catalog={stacks}
          stacks={stacks.stacks}
          reasons={reasonsOfEntry(reasons, index)}
          canRemove={draft.runs.length > 1}
          onChange={(edit) => changeRun(run.id, edit)}
          onRemove={() => update((next) => void (next.runs = next.runs.filter((item) => item.id !== run.id)))}
          onDuplicate={() =>
            update((next) => {
              const at = next.runs.findIndex((item) => item.id === run.id);
              next.runs.splice(at + 1, 0, { ...structuredClone(run), id: newEntryId("run") });
            })
          }
        />
      ))}
      <div>
        <button type="button" className="wiz-add" onClick={() => update((next) => void next.runs.push(emptyRun(firstAvailable?.id ?? "", "post_hoc")))}>
          Add a run
        </button>
      </div>
      <FieldIssues reasons={own} />
      <UnavailableStacks catalog={stacks} />
    </div>
  );
}
