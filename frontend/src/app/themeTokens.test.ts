import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = resolve(__dirname, "..");
const THEME_FILE = join(SRC, "theme.css");

function filesUnder(dir: string, extensions: string[]): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      return filesUnder(path, extensions);
    }
    return extensions.some((extension) => name.endsWith(extension)) ? [path] : [];
  });
}

function tokensOf(block: string): Map<string, string> {
  return new Map([...block.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map((match) => [match[1]!, match[2]!.trim()]));
}

const theme = readFileSync(THEME_FILE, "utf8");
const lightStart = theme.indexOf(':root[data-theme="light"]');
const DARK = tokensOf(theme.slice(0, lightStart));
const LIGHT = tokensOf(theme.slice(lightStart));

const stylesheets = filesUnder(SRC, [".css"]).filter((path) => path !== THEME_FILE);
const sources = filesUnder(SRC, [".ts", ".tsx"]).filter((path) => !/\.test\.tsx?$/.test(path));

/** Variables that are not colors: sizes declared in the stylesheets, values a component sets in its inline style. */
function otherVariables(): Set<string> {
  const declared = stylesheets.flatMap((path) => [...tokensOf(readFileSync(path, "utf8")).keys()]);
  const setInline = sources.flatMap((path) => [...readFileSync(path, "utf8").matchAll(/["'](--[\w-]+)["']\s*:/g)].map((match) => match[1]!));
  return new Set([...declared, ...setInline]);
}

function channels(value: string): [number, number, number] {
  const short = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/i.exec(value);
  if (short) {
    return [parseInt(short[1]! + short[1]!, 16), parseInt(short[2]! + short[2]!, 16), parseInt(short[3]! + short[3]!, 16)];
  }
  const long = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(value);
  if (!long) {
    throw new Error(`not an opaque hex color: ${value}`);
  }
  return [parseInt(long[1]!, 16), parseInt(long[2]!, 16), parseInt(long[3]!, 16)];
}

function luminance(value: string): number {
  const [r, g, b] = channels(value).map((channel) => {
    const unit = channel / 255;
    return unit <= 0.03928 ? unit / 12.92 : ((unit + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** What each text token is drawn on. 4.5:1 is the WCAG AA minimum for body text. */
const READABLE_PAIRS: [string, string][] = [
  ["--text", "--bg"],
  ["--text", "--bg-pane"],
  ["--text", "--bg-panel"],
  ["--text", "--bg-control"],
  ["--text", "--bg-control-hover"],
  ["--text", "--accent-solid"],
  ["--text", "--accent-solid-hover"],
  ["--text", "--accent-bg"],
  ["--text-soft", "--bg-panel"],
  ["--text-soft", "--bg-chip"],
  ["--text-muted", "--bg-panel"],
  ["--text-muted", "--bg-pane"],
  ["--danger-text", "--bg-panel"],
  ["--danger-text", "--danger-tint"],
  ["--danger-text-soft", "--danger-bg"],
  ["--danger-on-bg", "--danger-bg"],
  ["--danger-vivid-text", "--bg-panel"],
  ["--on-solid", "--danger-pill"],
  ["--on-solid", "--danger-solid"],
  ["--warn-text", "--bg-panel"],
  ["--warn-text", "--warn-bg"],
  ["--warn-text-soft", "--warn-bg"],
  ["--warn-vivid-text", "--bg-panel"],
  ["--on-warn-solid", "--warn-solid"],
  ["--ok-text", "--bg-panel"],
  ["--ok-text-soft", "--ok-bg"],
  ["--ok-on-bg", "--ok-solid"],
  ["--ok-on-solid", "--ok-solid"],
  ["--ok-vivid-text", "--bg-panel"],
  ["--info-text", "--bg-panel"],
  ["--info-text", "--info-bg"],
  ["--info-text-alt", "--accent-bg"],
  ["--syntax-keyword", "--bg-inset"],
  ["--syntax-string", "--bg-inset"],
  ["--syntax-number", "--bg-inset"],
  ["--syntax-comment", "--bg-inset"],
];

describe("theme tokens", () => {
  it("gives light mode a value for every token and no other", () => {
    expect([...LIGHT.keys()].sort()).toEqual([...DARK.keys()].sort());
  });

  it("leaves no literal color in a stylesheet", () => {
    const literal = /#[0-9a-fA-F]{3,8}\b|\brgba?\(\s*\d|\bhsla?\(\s*\d/;
    const offenders = stylesheets.flatMap((path) =>
      readFileSync(path, "utf8")
        .split("\n")
        .filter((line) => literal.test(line) && !/^\s*(\/\*|\*)/.test(line))
        .map((line) => `${relative(SRC, path)}: ${line.trim()}`)
    );
    expect(offenders).toEqual([]);
  });

  it("uses only tokens that exist, in stylesheets and in components", () => {
    const known = new Set([...DARK.keys(), ...otherVariables()]);
    const unknown = [...stylesheets, ...sources].flatMap((path) =>
      [...readFileSync(path, "utf8").matchAll(/var\((--[\w-]+)/g)]
        .map((match) => match[1]!)
        // React Flow defines its own.
        .filter((token) => !known.has(token) && !token.startsWith("--xy-"))
        .map((token) => `${relative(SRC, path)}: ${token}`)
    );
    expect(unknown).toEqual([]);
  });

  it.each(READABLE_PAIRS)("keeps %s readable on %s in light mode", (text, surface) => {
    expect(contrast(LIGHT.get(text)!, LIGHT.get(surface)!)).toBeGreaterThanOrEqual(4.5);
  });
});
