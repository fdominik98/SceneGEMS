import { afterEach, describe, expect, it, vi } from "vitest";
import { REVOKE_DELAY_MS, saveBlob } from "./saveBlob";

// jsdom has no object URLs: the test puts its own in and takes them out again
const original = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };

describe("saveBlob", () => {
  afterEach(() => {
    URL.createObjectURL = original.create;
    URL.revokeObjectURL = original.revoke;
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("clicks an attached link with the file name and revokes its URL only later", () => {
    vi.useFakeTimers();
    const revokeObjectURL = vi.fn();
    URL.createObjectURL = vi.fn(() => "blob:file-1");
    URL.revokeObjectURL = revokeObjectURL;
    const clicked: { download: string; href: string; attached: boolean }[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push({ download: this.download, href: this.href, attached: this.isConnected });
    });

    saveBlob(new Blob(["{}"], { type: "application/json" }), "state_log.json");

    expect(clicked).toEqual([{ download: "state_log.json", href: "blob:file-1", attached: true }]);
    expect(document.querySelector("a")).toBeNull();
    expect(revokeObjectURL).not.toHaveBeenCalled();
    vi.advanceTimersByTime(REVOKE_DELAY_MS);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:file-1");
  });
});
