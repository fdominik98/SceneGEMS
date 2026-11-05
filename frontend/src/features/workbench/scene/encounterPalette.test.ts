import { describe, expect, it } from "vitest";
import { CANVAS_COLORS, encounterColor, RESULT_COLORS } from "./encounterPalette";

describe("encounterColor", () => {
  it("names a token per kind of encounter", () => {
    expect(encounterColor("HEAD_ON")).toBe("var(--encounter-head-on)");
    expect(encounterColor("two_way_crossing_from_port")).toBe("var(--encounter-two-way)");
    expect(encounterColor("CROSSING_FROM_PORT")).toBe("var(--encounter-crossing)");
    expect(encounterColor("OVERTAKING_TO_PORT")).toBe("var(--encounter-overtaking)");
  });

  it("falls back to the token for no encounter", () => {
    expect(encounterColor("OTHER")).toBe("var(--encounter-none)");
  });
});

describe("the palette", () => {
  it("follows the theme through tokens, for the canvas and for the rule results", () => {
    for (const color of [...Object.values(CANVAS_COLORS), ...Object.values(RESULT_COLORS)]) {
      expect(color).toMatch(/^var\(--[\w-]+\)$/);
    }
  });
});
