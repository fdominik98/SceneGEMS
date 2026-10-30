import { describe, expect, it } from "vitest";
import { CHART_TOGGLES, DEFAULT_CANVAS_SETTINGS, VECTOR_MINUTES, withCanvasDefaults } from "./canvasSettings";

describe("canvas settings", () => {
  it("fills what an older stored value lacks with the defaults", () => {
    expect(withCanvasDefaults({ rings: false })).toEqual({ ...DEFAULT_CANVAS_SETTINGS, rings: false });
    expect(withCanvasDefaults(null)).toEqual(DEFAULT_CANVAS_SETTINGS);
  });

  it("offers the default vector length and a chart toggle per mark", () => {
    expect(VECTOR_MINUTES).toContain(DEFAULT_CANVAS_SETTINGS.vectorMinutes);
    expect(CHART_TOGGLES.map(([key]) => key)).toEqual(["rings", "cpa", "labels", "legend"]);
  });
});
