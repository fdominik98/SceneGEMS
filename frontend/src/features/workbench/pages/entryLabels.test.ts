import { describe, expect, it } from "vitest";
import { caseLabel, shortEntryId } from "./entryLabels";

describe("entry labels", () => {
  it("names a case by its 1-based index and the entry by its first block", () => {
    expect(shortEntryId("512039de-f185-444c-9a62-c2006c74c4ec")).toBe("512039de");
    expect(caseLabel(0, "512039de-f185-444c-9a62-c2006c74c4ec")).toBe("case 1 of entry 512039de");
  });
});
