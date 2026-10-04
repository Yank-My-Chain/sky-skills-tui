// Match skills/src/local-lock.ts, including JavaScript's localeCompare ordering.
import { readdir, readFile } from 'node:fs/promises';
import { join, relative } from 'node:path';
import { createHash } from 'node:crypto';
const root = process.argv[2];
const files = [];
async function collect(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory() && !['.git', 'node_modules'].includes(entry.name)) {
      await collect(path);
    } else if (entry.isFile()) {
      files.push({ path: relative(root, path).replaceAll('\\', '/'), content: await readFile(path) });
    }
  }
}
await collect(root);
files.sort((a, b) => a.path.localeCompare(b.path));
const hash = createHash('sha256');
for (const file of files) { hash.update(file.path); hash.update(file.content); }
console.log(hash.digest('hex'));
