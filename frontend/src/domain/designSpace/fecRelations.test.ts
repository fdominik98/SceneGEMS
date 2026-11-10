import { describe, expect, it } from "vitest";
import { fecRelationSummary } from "./fecRelations";

/** A shortened enum, then the tail of a generated FEC as the catalog holds it (`2vessel_1obstacle_scenarios`). Without the enum, `OSPassengerShip` would be an object. */
const FEC = `enum VesselType {CargoShip, OSPassengerShip}

class TS extends Vessel.

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
  it("says every link with the specification's relation names, a two-way pair once, without defaults and negated facts", () => {
    expect(fecRelationSummary(FEC)).toBe("os and ts1 head on; ts1 crossing from port os; os overtaking to starboard ts1; o1 at dangerous head on sector of os");
  });

  it("names relations of any specification, not only the ship ones", () => {
    expect(fecRelationSummary("class Folder { contains Folder[0..*] sub }\ndeclare a, b.\nsub(a, b).\n?linkedTo(b, a).\n")).toBe("a sub b; b linked to a (possibly)");
  });

  it("leaves values and unary facts out of the row", () => {
    expect(fecRelationSummary("enum Kind { Big }\ndeclare os.\nOS(os).\nkind(os, Big).\nsize(os): 3.\n")).toBe("no relations");
    expect(fecRelationSummary("")).toBe("no relations");
  });

  it("gives the same summary for the same text again", () => {
    expect(fecRelationSummary(FEC)).toBe(fecRelationSummary(FEC));
  });
});
