import { useMemo, useState } from "react";
import { describeOperatorError } from "../../../domain/cluster/operatorApi";
import { plural, splitClassId } from "../campaignFormat";
import { FailureBudgetField, Field, FieldIssues, NumberField } from "./fields";
import { reasonsOfEntry, splitByField, type Reason } from "./reasons";
import { expandPattern, planScope, summarizeFolders, type ScopeEntryPlan } from "./scopePlan";
import type { CatalogState, StepProps } from "./stepTypes";
import { emptyScopeEntry, type ScopeEntryDraft } from "./wizardState";

const ENTRY_FIELDS = ["quota", "failure_budget"] as const;
const CLASS_ROWS_SHOWN = 200;
const NO_CLASSES: readonly never[] = [];

function EntryCard({
  entry,
  index,
  plan,
  reasons,
  active,
  canRemove,
  onActivate,
  onChange,
  onRemove,
}: {
  entry: ScopeEntryDraft;
  index: number;
  plan: ScopeEntryPlan | undefined;
  reasons: readonly Reason[];
  active: boolean;
  canRemove: boolean;
  onActivate: () => void;
  onChange: (change: (entry: ScopeEntryDraft) => void) => void;
  onRemove: () => void;
}) {
  const { byField, rest } = splitByField(reasons, ENTRY_FIELDS);
  const empty = entry.classes.length === 0 && entry.patterns.length === 0;
  return (
    <section className={`wiz-card${active ? " wiz-card--active" : ""}${reasons.length > 0 ? " wiz-card--invalid" : ""}`} onClick={onActivate} aria-label={`Scope entry ${index + 1}`}>
      <header className="wiz-card-head">
        <h4>Scope entry {index + 1}</h4>
        {active ? <span className="camp-badge camp-badge--info">receives what you pick in the catalog</span> : <button type="button" onClick={onActivate}>Pick into this entry</button>}
        {canRemove && (
          <button type="button" className="wiz-remove" onClick={onRemove}>
            Remove entry
          </button>
        )}
      </header>
      {empty ? (
        <p className="meta">Nothing chosen yet. Pick folders or FECs in the catalog, or type a pattern.</p>
      ) : (
        <ul className="wiz-chips">
          {entry.patterns.map((pattern) => (
            <li key={`p-${pattern}`} className="wiz-chip wiz-chip--pattern" title="A pattern: it selects every FEC it matches">
              <code>{pattern}</code>
              <span className="wiz-chip-note">{plan && plan.emptyPatterns.includes(pattern) ? "matches nothing" : "pattern"}</span>
              <button type="button" aria-label={`Remove pattern ${pattern}`} onClick={() => onChange((item) => void (item.patterns = item.patterns.filter((value) => value !== pattern)))}>
                x
              </button>
            </li>
          ))}
          {entry.classes.map((classId) => (
            <li key={`c-${classId}`} className="wiz-chip" title={classId}>
              <code>{classId}</code>
              <button type="button" aria-label={`Remove FEC ${classId}`} onClick={() => onChange((item) => void (item.classes = item.classes.filter((value) => value !== classId)))}>
                x
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="wiz-row">
        <Field label="Quota" htmlFor={`quota-${entry.id}`} hint="Complete cases each FEC needs." issues={byField.get("quota")}>
          <NumberField id={`quota-${entry.id}`} integer min={1} value={entry.quota} invalid={byField.has("quota")} onChange={(value) => onChange((item) => void (item.quota = value))} />
        </Field>
        <Field label="Failure budget" htmlFor={`budget-${entry.id}`} hint="Dropped or failed cases a FEC may use up before it is abandoned." issues={byField.get("failure_budget")}>
          <FailureBudgetField id={`budget-${entry.id}`} value={entry.failureBudget} invalid={byField.has("failure_budget")} onChange={(value) => onChange((item) => void (item.failureBudget = value))} />
        </Field>
      </div>
      {plan && !empty && (
        <p className="wiz-plan">
          <strong>{plural(plan.classes.length, "FEC")}</strong> bring{plan.classes.length === 1 ? "s" : ""} <strong>{plural(plan.casesPlanned, "case")}</strong> to complete
          {plan.duplicates.length > 0 && <span className="wiz-plan-warning"> {plural(plan.duplicates.length, "FEC")} already in an earlier entry.</span>}
          {plan.unknownClasses.length > 0 && <span className="wiz-plan-warning"> Not in the catalog: {plan.unknownClasses.join(", ")}.</span>}
          {plan.emptyPatterns.length > 0 && <span className="wiz-plan-warning"> No FEC matches {plan.emptyPatterns.join(", ")}.</span>}
        </p>
      )}
      <FieldIssues reasons={rest} showField />
    </section>
  );
}

function CatalogBrowser({ catalog, onPickPattern, onPickClasses, picked }: { catalog: CatalogState; onPickPattern: (pattern: string) => void; onPickClasses: (classIds: string[]) => void; picked: ReadonlySet<string> }) {
  const [folder, setFolder] = useState("");
  const [search, setSearch] = useState("");
  const [pattern, setPattern] = useState("");
  const classes = catalog.classes ?? NO_CLASSES;
  const folders = useMemo(() => summarizeFolders(classes), [classes]);
  const inFolder = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return classes.filter((entry) => (folder === "" || entry.folder === folder) && (needle === "" || entry.fec_id.toLowerCase().includes(needle)));
  }, [classes, folder, search]);
  const matches = useMemo(() => (pattern.trim() ? expandPattern(pattern.trim(), classes) : []), [pattern, classes]);
  const shown = inFolder.slice(0, CLASS_ROWS_SHOWN);

  if (catalog.classesLoading) {
    return <p className="meta" role="status">Loading the FEC catalog...</p>;
  }
  if (catalog.classesError || !catalog.classes) {
    return (
      <div className="wiz-error" role="alert">
        <p>The FEC catalog did not load: {describeOperatorError(catalog.classesError)}</p>
        <button type="button" onClick={catalog.retry}>
          Try again
        </button>
      </div>
    );
  }

  return (
    <div className="wiz-catalog">
      <p className="meta">
        {plural(classes.length, "FEC")} in {plural(folders.length, "folder")}.
        <span className="wiz-explain"> A folder pattern selects every FEC of the folders it matches, so FECs added to the catalog later are not included: the campaign pins the FECs found when it is created.</span>
      </p>
      <Field label="Pattern" htmlFor="wiz-pattern" hint="Without a slash it matches folders, with a slash FEC ids. Wildcards: * ? [abc].">
        <span className="wiz-pattern-row">
          <input id="wiz-pattern" type="text" value={pattern} placeholder="2vessel_*_scenarios" onChange={(event) => setPattern(event.target.value)} />
          <button type="button" disabled={pattern.trim() === "" || matches.length === 0} onClick={() => { onPickPattern(pattern.trim()); setPattern(""); }}>
            Add pattern
          </button>
        </span>
        {pattern.trim() !== "" && (
          <p className={`wiz-hint${matches.length === 0 ? " wiz-hint--warn" : ""}`}>
            {matches.length === 0 ? "No FEC matches this pattern." : `Matches ${plural(matches.length, "FEC")}.`}
          </p>
        )}
      </Field>
      <div className="wiz-folders" role="list" aria-label="Folders">
        {folders.map((summary) => (
          <div key={summary.folder} role="listitem" className={`wiz-folder${folder === summary.folder ? " wiz-folder--on" : ""}`}>
            <button type="button" className="wiz-folder-name" aria-pressed={folder === summary.folder} onClick={() => setFolder(folder === summary.folder ? "" : summary.folder)}>
              {summary.folder}
            </button>
            <span className="wiz-folder-counts">
              {plural(summary.classes, "FEC")}; {summary.vessels.join(" or ")} vessels; {summary.obstacles.join(" or ")} obstacles
            </span>
            <button type="button" onClick={() => onPickPattern(summary.folder)} title="Select the folder as a pattern">
              Add folder
            </button>
          </div>
        ))}
      </div>
      <div className="wiz-class-bar">
        <input type="search" placeholder="Find a FEC" aria-label="Find a FEC" value={search} onChange={(event) => setSearch(event.target.value)} />
        <span className="meta">
          {folder === "" ? "All folders" : folder}: {plural(inFolder.length, "FEC")}
        </span>
        <button type="button" disabled={inFolder.length === 0} onClick={() => onPickClasses(inFolder.map((entry) => entry.fec_id))}>
          Add these {inFolder.length} as FECs
        </button>
      </div>
      <div className="camp-table-wrap wiz-class-scroll">
        <table className="camp-table camp-table--dense">
          <thead>
            <tr>
              <th>FEC</th>
              <th>Vessels</th>
              <th>Obstacles</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {shown.map((entry) => (
              <tr key={entry.fec_id}>
                <td title={entry.fec_id}>
                  <span className="camp-class-name">{splitClassId(entry.fec_id).name}</span>
                  {folder === "" && <span className="camp-class-folder">{entry.folder}</span>}
                </td>
                <td className="camp-num">{entry.vessel_count}</td>
                <td className="camp-num">{entry.obstacle_count}</td>
                <td>
                  <button type="button" disabled={picked.has(entry.fec_id)} onClick={() => onPickClasses([entry.fec_id])}>
                    {picked.has(entry.fec_id) ? "Added" : "Add"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {inFolder.length > shown.length && <p className="meta">Showing the first {shown.length}; narrow the list to see the rest.</p>}
    </div>
  );
}

/** Scope: the catalog classes a campaign that starts with scene generation covers (picked from the catalog or by pattern) with a quota and failure budget per entry. */
export function ScopeStep({ draft, update, reasons, catalog }: StepProps & { catalog: CatalogState }) {
  const [activeId, setActiveId] = useState(draft.scope[0]?.id ?? "");
  const active = draft.scope.find((entry) => entry.id === activeId) ?? draft.scope[draft.scope.length - 1];
  const plan = useMemo(() => (catalog.classes ? planScope(draft.scope, catalog.classes) : null), [draft.scope, catalog.classes]);
  const own = splitByField(reasonsOfEntry(reasons, null), ["scope"]);
  const picked = useMemo(() => new Set(draft.scope.flatMap((entry) => entry.classes)), [draft.scope]);

  const change = (id: string, edit: (entry: ScopeEntryDraft) => void) =>
    update((next) => {
      const found = next.scope.find((entry) => entry.id === id);
      if (found) {
        edit(found);
      }
    });

  return (
    <div className="wiz-step">
      <div className="wiz-columns">
        <div className="wiz-column">
          <h4 className="wiz-subhead">Catalog FECs</h4>
          {draft.input.scenarios.length > 0 && <p className="meta wiz-explain">Scope entries without FECs are left out while scenario files give the campaign something to run.</p>}
          <FieldIssues reasons={[...(own.byField.get("scope") ?? []), ...own.rest]} showField />
          {draft.scope.map((entry, index) => (
            <EntryCard
              key={entry.id}
              entry={entry}
              index={index}
              plan={plan?.entries[index]}
              reasons={reasonsOfEntry(reasons, index)}
              active={active?.id === entry.id}
              canRemove={draft.scope.length > 1}
              onActivate={() => setActiveId(entry.id)}
              onChange={(edit) => change(entry.id, edit)}
              onRemove={() => update((next) => void (next.scope = next.scope.filter((item) => item.id !== entry.id)))}
            />
          ))}
          <div>
            <button
              type="button"
              className="wiz-add"
              onClick={() => {
                const created = emptyScopeEntry();
                update((next) => void next.scope.push(created));
                setActiveId(created.id);
              }}
            >
              Add a scope entry
            </button>
          </div>
          {plan && (
            <p className="wiz-total" role="status">
              <strong>{plural(plan.classes, "FEC")}</strong> selected, <strong>{plural(plan.casesPlanned, "case")}</strong> planned to complete (the quotas added up).
              <span className="wiz-hint wiz-explain"> Spares and dropped cases come on top.</span>
            </p>
          )}
        </div>
        <div className="wiz-column">
          <h4 className="wiz-subhead">Catalog</h4>
          <CatalogBrowser
            catalog={catalog}
            picked={picked}
            onPickPattern={(pattern) =>
              change(active?.id ?? "", (entry) => {
                if (!entry.patterns.includes(pattern)) {
                  entry.patterns.push(pattern);
                }
              })
            }
            onPickClasses={(classIds) =>
              change(active?.id ?? "", (entry) => {
                for (const classId of classIds) {
                  if (!entry.classes.includes(classId)) {
                    entry.classes.push(classId);
                  }
                }
              })
            }
          />
        </div>
      </div>
    </div>
  );
}
