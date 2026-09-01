import { renderRelationId } from "./actorNameFormat";
import { asRecord, DynamicFieldGrid, DynamicValue } from "./frameDataDisplay";
import { MonitorSection } from "./monitorPrimitives";

/**
 * General fallback layout for a monitor field whose shape is not recognized.
 * Renders each entry with the generic recursive key/value grid so an unknown
 * monitor is still fully inspectable.
 */
export function GeneralMonitorList({
  title,
  items,
}: {
  title: string;
  items: unknown[];
}) {
  if (items.length === 0) {
    return null;
  }
  return (
    <MonitorSection title={title} badge={items.length}>
      <p className="meta mon-fallback-note">
        Unrecognized shape for this monitor field: showing the raw structure.
      </p>
      <div className="frame-list-stack">
        {items.map((item, i) => {
          const rec = asRecord(item);
          const relId =
            rec && typeof rec.relationId === "string" ? (rec.relationId as string) : null;
          return (
            <details key={i} className="frame-item-card" open={items.length <= 3}>
              <summary className="frame-item-summary">
                {relId ? renderRelationId(relId) : `Item ${i + 1}`}
              </summary>
              {rec ? <DynamicFieldGrid data={rec} /> : <DynamicValue value={item} depth={0} />}
            </details>
          );
        })}
      </div>
    </MonitorSection>
  );
}

/** Same, for a single object-shaped field (e.g. `metrics`). */
export function GeneralMonitorObject({ title, data }: { title: string; data: unknown }) {
  const rec = asRecord(data);
  if (!rec || Object.keys(rec).length === 0) {
    return null;
  }
  return (
    <MonitorSection title={title} badge={Object.keys(rec).length}>
      <p className="meta mon-fallback-note">
        Unrecognized shape for this monitor field: showing the raw structure.
      </p>
      <DynamicFieldGrid data={rec} />
    </MonitorSection>
  );
}
