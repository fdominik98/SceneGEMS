import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { mdToPdf } from 'md-to-pdf';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, '..');
const docsDir = resolve(root, 'website/docs');
const pdfCss = resolve(__dirname, 'docs-pdf.css');
const outputPath = resolve(root, 'website/static/scenegems-ui-documentation.pdf');

/** Sidebar order — keep in sync with website/sidebars.ts */
const DOC_IDS = [
  'intro',
  'layout',
  'navigation',
  'domain-configuration',
  'scene-generation',
  'simulation',
  'waraps',
  'scene-canvas',
  'control-panel',
  'monitoring',
  'metrics',
  'recording',
  'resizing',
  'persistence',
  'status',
  'workflow',
];

function stripFrontmatter(text) {
  return text.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '');
}

function resolveDocFile(id) {
  for (const ext of ['.mdx', '.md']) {
    const path = resolve(docsDir, `${id}${ext}`);
    if (existsSync(path)) {
      return path;
    }
  }
  throw new Error(`Missing documentation file for "${id}"`);
}

function buildCombinedMarkdown() {
  const sections = DOC_IDS.map((id, index) => {
    const raw = readFileSync(resolveDocFile(id), 'utf8');
    const body = stripFrontmatter(raw).trim();
    if (index === DOC_IDS.length - 1) {
      return body;
    }
    return `${body}\n\n<div class="page-break"></div>\n`;
  });

  return sections.join('\n');
}

async function main() {
  const combined = buildCombinedMarkdown();
  mkdirSync(dirname(outputPath), { recursive: true });

  const pdf = await mdToPdf(
    { content: combined },
    {
      dest: outputPath,
      css: pdfCss,
      pdf_options: {
        format: 'A4',
        margin: { top: '18mm', right: '16mm', bottom: '18mm', left: '16mm' },
        printBackground: true,
      },
    }
  );

  if (!pdf?.filename) {
    throw new Error('PDF generation failed.');
  }

  console.log(`Wrote documentation PDF to ${outputPath}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
