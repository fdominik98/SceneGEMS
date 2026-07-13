import { cpSync, rmSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';

const source = resolve('website/build');
const target = resolve('public/docs');

if (!existsSync(source)) {
  throw new Error('Missing website/build. Run npm run docs:build first.');
}

if (existsSync(target)) {
  rmSync(target, { recursive: true, force: true });
}

cpSync(source, target, { recursive: true });
