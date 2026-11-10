import type { TextOrGraph } from "./textOrGraph";
import "./problemGraphs.css";

interface Props {
  /** The accessible name of the group. */
  label: string;
  value: TextOrGraph;
  onChange: (view: TextOrGraph) => void;
  /** The order of the two buttons. */
  order?: readonly TextOrGraph[];
}

const NAMES: Record<TextOrGraph, string> = { text: "Text", graph: "Graph" };

/** A two way switch between a text and its graph: segmented buttons with `aria-pressed`. */
export function ViewSwitch({ label, value, onChange, order = ["text", "graph"] }: Props) {
  return (
    <div className="pg-switch" role="group" aria-label={label}>
      {order.map((view) => (
        <button key={view} type="button" aria-pressed={view === value} onClick={() => onChange(view)}>
          {NAMES[view]}
        </button>
      ))}
    </div>
  );
}
