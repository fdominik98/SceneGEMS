import { readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(__dirname, "..");
const modelsRoot = path.join(root, "public", "generated_functional_models", "all");

const VESSEL_OBSTACLE_RE = /^(\d+)vessel_(\d+)obstacle_scenarios$/;

async function walk(dir, base = "") {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const rel = base ? `${base}/${entry.name}` : entry.name;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await walk(full, rel)));
    } else if (entry.name.endsWith(".problem")) {
      files.push(rel.replace(/\\/g, "/"));
    }
  }
  return files;
}

function parseFolderMeta(folderName) {
  const match = folderName.match(VESSEL_OBSTACLE_RE);
  if (!match) {
    return { vesselCount: null, obstacleCount: null };
  }
  return { vesselCount: Number(match[1]), obstacleCount: Number(match[2]) };
}

const relFiles = await walk(modelsRoot);
const presets = relFiles
  .map((rel) => {
    const webPath = `/generated_functional_models/all/${rel}`;
    const parts = rel.split("/");
    const folder = parts.length > 1 ? parts[0] : "";
    const fileName = parts[parts.length - 1] ?? rel;
    const meta = parseFolderMeta(folder);
    return {
      path: webPath,
      label: rel,
      fileName,
      folder,
      ...meta,
    };
  })
  .sort((a, b) => a.label.localeCompare(b.label, undefined, { numeric: true }));

const manifest = {
  generatedAt: new Date().toISOString(),
  count: presets.length,
  presets,
};

const outPath = path.join(root, "public", "generated_functional_models", "presets-manifest.json");
await writeFile(outPath, JSON.stringify(manifest, null, 2), "utf8");
console.log(`Wrote ${presets.length} presets to ${outPath}`);
