import type { CSSProperties, ReactNode } from "react";
import type { OverlayVisibility } from "../../../app/uiStore";
import {
  CorridorIcon,
  EyeIcon,
  HullIcon,
  LayersIcon,
  SafetyDomainIcon,
  SafetyRadiusIcon,
  StaticDomainIcon,
  TrackIcon,
  VectorIcon,
} from "../../../components/icons";
import { PopoverMenu } from "../../../components/PopoverMenu";
import { CHART_TOGGLES, VECTOR_MINUTES, type CanvasSettings } from "./canvasSettings";

/** The layers of one drawn stream (the workbench overlays a preview and a simulation). */
export interface LayerColumn {
  key: string;
  label: string;
  layers: OverlayVisibility;
  onChange: (key: keyof OverlayVisibility, value: boolean) => void;
  /** Whether the stream is drawn at all; with `onShownChange` the menu can hide the whole stream. */
  shown?: boolean;
  onShownChange?: (shown: boolean) => void;
}

const LAYER_ROWS: { key: keyof OverlayVisibility; label: string; icon: ReactNode }[] = [
  { key: "dot", label: "Hulls and headings", icon: <HullIcon size={18} /> },
  { key: "velocity", label: "Course vectors", icon: <VectorIcon size={18} /> },
  { key: "trajectory", label: "Tracks", icon: <TrackIcon size={18} /> },
  { key: "safetyDomain", label: "Safety domains", icon: <SafetyDomainIcon size={18} /> },
  { key: "maneuveringDomain", label: "Maneuvering corridors", icon: <CorridorIcon size={18} /> },
  { key: "staticAvoidanceDomain", label: "Static avoidance domains", icon: <StaticDomainIcon size={18} /> },
  { key: "safetyRadius", label: "Safety radius rings", icon: <SafetyRadiusIcon size={18} /> },
];

interface LayerMenuProps {
  columns: LayerColumn[];
  settings: CanvasSettings;
  onSettingsChange: (patch: Partial<CanvasSettings>) => void;
}

/**
 * Every layer of the view behind one button over it: a row per vessel layer with a switch per
 * stream (so the preview and the simulation are set side by side), then the chart's own marks
 * and the vector length.
 */
export function LayerMenu({ columns, settings, onSettingsChange }: LayerMenuProps) {
  const multi = columns.length > 1;
  const hideable = columns.some((column) => column.onShownChange);

  const row = (key: string, label: string, icon: ReactNode, cell: (column: LayerColumn) => ReactNode) => {
    const title = (
      <span className="layer-menu-name">
        <span className="layer-menu-icon">{icon}</span>
        {label}
      </span>
    );
    if (!multi) {
      return (
        <label key={key} className="layer-menu-row">
          {title}
          {columns[0] ? cell(columns[0]) : null}
        </label>
      );
    }
    return (
      <div key={key} className="layer-menu-row">
        {title}
        {columns.map((column) => (
          <label key={column.key} className="layer-menu-cell">
            {cell(column)}
          </label>
        ))}
      </div>
    );
  };

  return (
    <PopoverMenu label={<LayersIcon />} iconLabel="Layers" className="layer-menu">
      {columns.length > 0 ? (
        <div className="layer-menu-grid" role="group" aria-label="Vessel layers" style={{ "--layer-columns": columns.length } as CSSProperties}>
          <div className="layer-menu-row layer-menu-head">
            <span className="layer-menu-title">Vessels</span>
            {multi
              ? columns.map((column) => (
                  <span key={column.key} className="layer-menu-col-label" aria-hidden>
                    {column.label}
                  </span>
                ))
              : null}
          </div>
          {hideable
            ? row("shown", "Visible", <EyeIcon size={18} />, (column) =>
                column.onShownChange ? (
                  <input
                    type="checkbox"
                    aria-label={multi ? `${column.label} visible` : undefined}
                    checked={column.shown ?? true}
                    onChange={(event) => column.onShownChange?.(event.target.checked)}
                  />
                ) : null
              )
            : null}
          {LAYER_ROWS.map(({ key, label, icon }) =>
            row(key, label, icon, (column) => (
              <input
                type="checkbox"
                className={column.shown === false ? "is-off" : undefined}
                aria-label={multi ? `${label}, ${column.label}` : undefined}
                checked={column.layers[key]}
                onChange={(event) => column.onChange(key, event.target.checked)}
              />
            ))
          )}
        </div>
      ) : null}
      <div className="layer-menu-chart" role="group" aria-label="Chart">
        <span className="layer-menu-title">Chart</span>
        <div className="layer-menu-chips">
          {CHART_TOGGLES.map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={`layer-chip${settings[key] ? " is-active" : ""}`}
              aria-pressed={settings[key]}
              onClick={() => onSettingsChange({ [key]: !settings[key] })}
            >
              {label}
            </button>
          ))}
        </div>
        <label className="layer-menu-select">
          <span>Vector length</span>
          <select value={settings.vectorMinutes} onChange={(event) => onSettingsChange({ vectorMinutes: Number(event.target.value) })}>
            {VECTOR_MINUTES.map((minutes) => (
              <option key={minutes} value={minutes}>
                {minutes} min
              </option>
            ))}
          </select>
        </label>
      </div>
    </PopoverMenu>
  );
}
