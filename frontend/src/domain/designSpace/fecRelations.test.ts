import { describe, expect, it } from "vitest";
import { describeFecRelation, fecRelationSummary, parseFecRelations } from "./fecRelations";

/** The tail of a generated FEC as the catalog holds it (`2vessel_1obstacle_scenarios`). */
const FEC = `class TS extends Vessel.

error noOS() <->
    !OS(_).

declare os, ts1, o1.
!exists(OS::new).
OS(os).
vesselType(os, OSPassengerShip).

TS(ts1).
default !overtakingToPort(*, *).
headOn(os, ts1).
headOn(ts1, os).
default !overtakingToStarboard(*, *).
crossingFromPort(ts1, os).
overtakingToStarboard(os, ts1).
!overtakingToPort(ts1, os).
atDangerousHeadOnSectorOf(o1, os).
default !headOn(*, *).
`;

describe("the relations of an explored FEC", () => {
  it("reads the relation facts after the last declare line, headOn once", () => {
    expect(parseFecRelations(FEC)).toEqual([
      { relation: "headOn", from: "os", to: "ts1" },
      { relation: "crossingFromPort", from: "ts1", to: "os" },
      { relation: "overtakingToStarboard", from: "os", to: "ts1" },
      { relation: "atDangerousHeadOnSectorOf", from: "o1", to: "os" },
    ]);
  });

  it("ignores the facts before the declare line and texts without one", () => {
    expect(parseFecRelations("headOn(a, b).\ndeclare a, b.\novertakingToPort(a, b).\n")).toEqual([{ relation: "overtakingToPort", from: "a", to: "b" }]);
    expect(parseFecRelations("headOn(a, b).\n")).toEqual([]);
  });

  it("says each relation in words", () => {
    expect(describeFecRelation({ relation: "headOn", from: "os", to: "ts1" })).toBe("os and ts1 head-on");
    expect(describeFecRelation({ relation: "overtakingToPort", from: "ts1", to: "os" })).toBe("ts1 overtakes os to port");
    expect(describeFecRelation({ relation: "overtakingToStarboard", from: "ts1", to: "os" })).toBe("ts1 overtakes os to starboard");
    expect(describeFecRelation({ relation: "crossingFromPort", from: "ts1", to: "os" })).toBe("ts1 crosses os from port");
    expect(describeFecRelation({ relation: "atDangerousHeadOnSectorOf", from: "o1", to: "os" })).toBe("o1 in the dangerous head-on sector of os");
    expect(fecRelationSummary(FEC)).toBe("os and ts1 head-on; ts1 crosses os from port; os overtakes ts1 to starboard; o1 in the dangerous head-on sector of os");
    expect(fecRelationSummary("declare os.\nOS(os).\n")).toBe("no relations");
  });
});
