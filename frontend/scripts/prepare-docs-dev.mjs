import { rmSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const docsDir = resolve('public/docs');
if (existsSync(docsDir)) {
  rmSync(docsDir, { recursive: true, force: true });
}

const pdfPath = resolve('website/static/scenegems-ui-documentation.pdf');
if (!existsSync(pdfPath)) {
  console.log('Documentation PDF missing — generating (first run only)…');
  const result = spawnSync('node', ['scripts/generate-docs-pdf.mjs'], {
    stdio: 'inherit',
    cwd: resolve('.'),
  });
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}
