import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PopoverMenu } from "./PopoverMenu";

describe("PopoverMenu", () => {
  it("starts closed: the button reports it and the panel is hidden", () => {
    const html = renderToStaticMarkup(
      <PopoverMenu label="Export">
        <button type="button">CSV</button>
      </PopoverMenu>
    );
    expect(html).toContain('aria-expanded="false"');
    expect(html).toMatch(/<div[^>]*class="popover-menu-panel"[^>]*hidden/);
    expect(html).toContain("CSV");
  });

  it("links the button to the panel and names the group", () => {
    const html = renderToStaticMarkup(
      <PopoverMenu label="View options" align="end" placement="top">
        x
      </PopoverMenu>
    );
    const controls = /aria-controls="([^"]+)"/.exec(html)?.[1];
    expect(controls).toBeDefined();
    expect(html).toContain(`id="${controls}"`);
    expect(html).toContain('aria-label="View options"');
    expect(html).toContain('data-align="end"');
    expect(html).toContain('data-placement="top"');
  });

  it("makes an icon-only button with iconLabel: its name, tooltip and the group's name, no chevron", () => {
    const html = renderToStaticMarkup(
      <PopoverMenu label={<svg aria-hidden />} iconLabel="Export">
        x
      </PopoverMenu>
    );
    expect(html).toMatch(/<button[^>]*class="popover-menu-button icon-btn"[^>]*aria-label="Export"[^>]*title="Export"/);
    expect(html).toMatch(/role="group" aria-label="Export"/);
    expect(html).not.toContain("popover-menu-chevron");
  });

  it("uses the ariaLabel when the label is not plain text", () => {
    const html = renderToStaticMarkup(
      <PopoverMenu label={<span>Layers</span>} ariaLabel="Layer options">
        x
      </PopoverMenu>
    );
    expect(html).toContain('aria-label="Layer options"');
  });
});
