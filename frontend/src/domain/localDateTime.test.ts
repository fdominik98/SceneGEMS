import { describe, expect, it } from "vitest";
import { formatIsoDateTime, formatLocalDateTime } from "./localDateTime";

describe("formatLocalDateTime", () => {
  // Built from local parts, so the expectation holds in every time zone.
  const at = new Date(2026, 9, 26, 9, 0, 5);

  it("writes the browser's local time on a 24 hour clock, zero padded", () => {
    expect(formatLocalDateTime(at)).toBe("2026-10-26 09:00:05");
    expect(formatLocalDateTime(new Date(2026, 10, 12, 13, 8, 0))).toBe("2026-11-12 13:08:00");
  });

  it("leaves the seconds out at minute precision", () => {
    expect(formatLocalDateTime(at, "minute")).toBe("2026-10-26 09:00");
  });
});

describe("formatIsoDateTime", () => {
  it("reads an ISO time into the same format", () => {
    const at = new Date(2026, 9, 26, 9, 0, 5);
    expect(formatIsoDateTime(at.toISOString(), "none")).toBe("2026-10-26 09:00:05");
    expect(formatIsoDateTime(at.toISOString(), "none", "minute")).toBe("2026-10-26 09:00");
  });

  it("gives the caller's word when there is no time and the text itself when it is not one", () => {
    expect(formatIsoDateTime(null, "none")).toBe("none");
    expect(formatIsoDateTime(undefined, "-")).toBe("-");
    expect(formatIsoDateTime("", "-")).toBe("-");
    expect(formatIsoDateTime("soon", "none")).toBe("soon");
  });
});
