import type { ReactNode } from "react";
import { IconButton } from "../../../components/IconButton";
import { FitViewIcon, HeadUpIcon, NorthUpIcon } from "../../../components/icons";
import type { CanvasSettings } from "./canvasSettings";
import type { Orientation } from "./encounterGeometry";
import { LayerMenu, type LayerColumn } from "./LayerMenu";

interface CanvasToolbarProps {
  onFit: () => void;
  /** Tooltip of the fit button. */
  fitTitle?: string;
  settings: CanvasSettings;
  onSettingsChange: (patch: Partial<CanvasSettings>) => void;
  /** The north up and head up switch; left out where the view is always north up (the map). */
  onOrientationChange?: (orientation: Orientation) => void;
  /** Head up turns around the own ship, so it needs one. */
  canHeadUp?: boolean;
  layerColumns: LayerColumn[];
  /** Buttons at the right end (map switch, export, the monitoring panel). */
  children?: ReactNode;
  className?: string;
}

/** The icon buttons laid over the top of the encounter canvas and the nautical map. */
export function CanvasToolbar({
  onFit,
  fitTitle,
  settings,
  onSettingsChange,
  onOrientationChange,
  canHeadUp = false,
  layerColumns,
  children,
  className,
}: CanvasToolbarProps) {
  const headUp = settings.orientation === "head-up" && canHeadUp;
  return (
    <div className={`enc-canvas-toolbar${className ? ` ${className}` : ""}`} role="toolbar" aria-label="View">
      <IconButton label="Fit view" title={fitTitle} icon={<FitViewIcon />} onClick={onFit} />
      {onOrientationChange ? (
        <IconButton
          label="Head up"
          pressed={headUp}
          disabled={!canHeadUp}
          title={
            !canHeadUp
              ? "North up (head up needs an own ship)"
              : headUp
                ? "Head up: the own ship's heading at the top. Click for north up"
                : "North up. Click for head up: the own ship's heading at the top"
          }
          icon={headUp ? <HeadUpIcon /> : <NorthUpIcon />}
          onClick={() => onOrientationChange(headUp ? "north-up" : "head-up")}
        />
      ) : null}
      <LayerMenu columns={layerColumns} settings={settings} onSettingsChange={onSettingsChange} />
      {children ? <div className="enc-canvas-actions">{children}</div> : null}
    </div>
  );
}
