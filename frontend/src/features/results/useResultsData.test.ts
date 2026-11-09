import { describe, expect, it } from "vitest";
import { pollUntilFinal } from "./useResultsData";

describe("pollUntilFinal", () => {
  it("polls while the entry is not final or its detail is not known", () => {
    expect(pollUntilFinal(undefined, 0, 10_000)).toBe(10_000);
    expect(pollUntilFinal({ data: undefined, dataUpdatedAt: 0 }, 5, 10_000)).toBe(10_000);
    expect(pollUntilFinal({ data: { actual_state: "running" }, dataUpdatedAt: 100 }, 200, 10_000)).toBe(10_000);
    expect(pollUntilFinal({ data: { actual_state: "draining" }, dataUpdatedAt: 100 }, 200, 10_000)).toBe(10_000);
  });

  it("stops once the entry is final and the query was read after the master said so", () => {
    expect(pollUntilFinal({ data: { actual_state: "completed" }, dataUpdatedAt: 100 }, 200, 10_000)).toBe(false);
    expect(pollUntilFinal({ data: { actual_state: "stopped" }, dataUpdatedAt: 100 }, 100, 10_000)).toBe(false);
    // read before the entry turned final: one more read picks up what the last cases recorded
    expect(pollUntilFinal({ data: { actual_state: "completed" }, dataUpdatedAt: 100 }, 50, 10_000)).toBe(10_000);
  });
});
