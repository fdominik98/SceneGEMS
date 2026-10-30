import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { IconButton } from "./IconButton";
import { FitViewIcon } from "./icons";

describe("IconButton", () => {
  it("shows only the icon and carries its name as the accessible name and the tooltip", () => {
    const html = renderToStaticMarkup(<IconButton label="Fit view" icon={<FitViewIcon />} onClick={() => {}} />);
    expect(html).toContain('aria-label="Fit view"');
    expect(html).toContain('title="Fit view"');
    expect(html).toContain('class="icon-btn"');
    expect(html).toContain('aria-hidden="true"');
    expect(html).not.toMatch(/>Fit view</);
  });

  it("takes a longer tooltip than its name", () => {
    const html = renderToStaticMarkup(
      <IconButton label="Fit view" title="Fit view (double-click)" icon={<FitViewIcon />} onClick={() => {}} />
    );
    expect(html).toContain('aria-label="Fit view"');
    expect(html).toContain('title="Fit view (double-click)"');
  });

  it("reports a toggle's state and a disclosure's state", () => {
    const pressed = renderToStaticMarkup(<IconButton label="Head up" pressed icon={<FitViewIcon />} onClick={() => {}} />);
    expect(pressed).toContain('aria-pressed="true"');
    expect(pressed).toContain('class="icon-btn is-active"');
    const expanded = renderToStaticMarkup(<IconButton label="Rule timeline" expanded={false} icon={<FitViewIcon />} onClick={() => {}} />);
    expect(expanded).toContain('aria-expanded="false"');
    expect(expanded).not.toContain("aria-pressed");
  });

  it("can be disabled", () => {
    const html = renderToStaticMarkup(<IconButton label="Export" disabled icon={<FitViewIcon />} onClick={() => {}} />);
    expect(html).toMatch(/<button[^>]*disabled/);
  });
});
