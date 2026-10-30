// Match skills/src/local-lock.ts, including JavaScript's localeCompare ordering.
// Accepts several folders and prints one hash per line, in argument order, so a
// whole source can be hashed with a single Node startup.
import { readdir, readFile } from 'node:fs/promises';
import { join, relative } from 'node:path';
import { createHash } from 'node:crypto';
async function collect(root, dir, files) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory() && !['.git', 'node_modules'].includes(entry.name)) {
      await collect(root, path, files);
    } else if (entry.isFile()) {
      files.push({ path: relative(root, path).replaceAll('\\', '/'), content: await readFile(path) });
    }
  }
}
async function folderHash(root) {
  const files = [];
  await collect(root, root, files);
  files.sort((a, b) => a.path.localeCompare(b.path));
  const hash = createHash('sha256');
  for (const file of files) { hash.update(file.path); hash.update(file.content); }
  return hash.digest('hex');
}
const hashes = await Promise.all(process.argv.slice(2).map(folderHash));
console.log(hashes.join('\n'));
