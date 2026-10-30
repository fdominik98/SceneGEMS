import { describe, expect, it } from "vitest";
import { encounterTypeLabel, ENCOUNTER_TYPE_LABELS } from "./encounterTypes";

describe("encounter type labels", () => {
  it("names every type the monitor reports as its situation label reads", () => {
    expect(Object.keys(ENCOUNTER_TYPE_LABELS)).toHaveLength(7);
    expect(encounterTypeLabel("HEAD_ON")).toBe("Head-On");
    expect(encounterTypeLabel("two_way_crossing_from_starboard")).toBe("Two Way Crossing from Starboard");
    expect(encounterTypeLabel("OTHER")).toBe("Other");
  });

  it("writes an unknown type in words", () => {
    expect(encounterTypeLabel("MEETING_AT_A_BEND")).toBe("Meeting at a bend");
  });
});
