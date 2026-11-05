import { describe, expect, it } from "vitest";
import { CANVAS_COLORS } from "./encounterPalette";
import { inlineCssVariables } from "./sceneExport";

describe("inlineCssVariables", () => {
  const values: Record<string, string> = {
    "--canvas-sea": " #dcebf5",
    "--canvas-label-bg": "rgba(255, 255, 255, 0.82)",
  };
  const valueOf = (token: string) => values[token] ?? "";

  it("writes the value of each token into the markup", () => {
    const markup = `<svg><rect fill="${CANVAS_COLORS.sea}"/><rect fill="${CANVAS_COLORS.labelBackground}"/></svg>`;
    expect(inlineCssVariables(markup, valueOf)).toBe('<svg><rect fill="#dcebf5"/><rect fill="rgba(255, 255, 255, 0.82)"/></svg>');
  });

  it("replaces every occurrence, also in a style attribute", () => {
    const markup = '<g fill="var(--canvas-sea)" style="stroke: var(--canvas-sea)"/>';
    expect(inlineCssVariables(markup, valueOf)).toBe('<g fill="#dcebf5" style="stroke: #dcebf5"/>');
  });

  it("leaves markup without tokens as it is", () => {
    const markup = '<circle fill="#06b6d4" r="4"/>';
    expect(inlineCssVariables(markup, valueOf)).toBe(markup);
  });
});
