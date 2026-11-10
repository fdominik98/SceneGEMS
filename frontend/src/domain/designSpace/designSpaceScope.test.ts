import { describe, expect, it } from "vitest";
import { formatDesignSpaceScope, parseDesignSpaceScope, scopeProblem } from "./designSpaceScope";

describe("the scope of a design space exploration", () => {
  it("reads entries of a count or a range, in their order", () => {
    expect(parseDesignSpaceScope("TS = 2, StaticObstacle = 0")).toEqual({
      ok: true,
      entries: [
        { type: "TS", min: 2, max: 2 },
        { type: "StaticObstacle", min: 0, max: 0 },
      ],
    });
    expect(parseDesignSpaceScope("  TS=1..3 ,Obstacle_2 = 0 .. 1")).toEqual({
      ok: true,
      entries: [
        { type: "TS", min: 1, max: 3 },
        { type: "Obstacle_2", min: 0, max: 1 },
      ],
    });
  });

  it("asks for a scope when there is none", () => {
    expect(scopeProblem("")).toBe("Enter a scope, for example TS = 2, StaticObstacle = 0.");
    expect(scopeProblem("   ")).not.toBeNull();
  });

  it("names the entry that is wrong and the form it should have", () => {
    expect(scopeProblem("TS = 2, ")).toBe("The entry 2 is empty. Write Type = n or Type = a..b, separated by commas.");
    expect(scopeProblem("TS 2")).toBe('The scope ("TS 2") has no "=". Write Type = n or Type = a..b, separated by commas.');
    expect(scopeProblem("TS = 2, 3x = 1")).toBe('The entry 2 ("3x = 1") does not start with a class name: "3x" is not one. Write Type = n or Type = a..b, separated by commas.');
    expect(scopeProblem("= 1")).toContain("it is missing");
    expect(scopeProblem("TS = two")).toBe('The scope ("TS = two") needs a whole number n or a range a..b after "=", for example TS = 2 or TS = 0..2.');
    expect(scopeProblem("TS = -1")).not.toBeNull();
    expect(scopeProblem("TS = 1.5")).not.toBeNull();
    expect(scopeProblem("TS = 3..1")).toBe('The scope ("TS = 3..1") is a range from 3 down to 1. The lower bound comes first: TS = 1..3.');
    expect(scopeProblem("TS = 1, TS = 2")).toBe("The entry 2 gives TS a second time. Give each class one entry.");
  });

  it("writes entries back in the config's form", () => {
    const check = parseDesignSpaceScope("TS = 2, StaticObstacle = 0..1");
    expect(check.ok && formatDesignSpaceScope(check.entries)).toBe("TS = 2, StaticObstacle = 0..1");
  });
});
