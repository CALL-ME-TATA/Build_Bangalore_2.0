// Entry point so that `node --test web/tests` works on Node 24, which no longer expands a directory argument.
// It loads every *.test.mjs file in this folder.
import { readdirSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { join, dirname } from 'node:path';

const dir = dirname(fileURLToPath(import.meta.url));
for (const f of readdirSync(dir).filter((n) => n.endsWith('.test.mjs')).sort()) {
  await import(pathToFileURL(join(dir, f)).href);
}
