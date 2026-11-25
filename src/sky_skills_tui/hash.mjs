// Reproduce npm skills' folder hashes. Accepts several folders and prints one line
// per folder, in argument order: "<legacy> <v2>". One Node startup hashes a whole source.
//
// legacy: skills <1.8.0 (src/local-lock.ts computeSkillFolderHash), localeCompare order.
// v2:     skills >=1.8.0 (hashSkillFiles), byte order, length-prefixed, CRLF-normalised.
import { readdir, readFile, realpath, stat } from 'node:fs/promises';
import { join, relative, sep } from 'node:path';
import { createHash } from 'node:crypto';

async function collectLegacy(root, dir, files) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory() && !['.git', 'node_modules'].includes(entry.name)) {
      await collectLegacy(root, path, files);
    } else if (entry.isFile()) {
      files.push({ path: relative(root, path).replaceAll('\\', '/'), content: await readFile(path) });
    }
  }
}

async function legacyHash(root) {
  const files = [];
  await collectLegacy(root, root, files);
  files.sort((a, b) => a.path.localeCompare(b.path));
  const hash = createHash('sha256');
  for (const file of files) { hash.update(file.path); hash.update(file.content); }
  return hash.digest('hex');
}

const EXCLUDE_FILES = new Set(['metadata.json']);
const EXCLUDE_DIRS = new Set(['.git', '__pycache__', '__pypackages__']);
const excluded = (name, isDirectory) =>
  EXCLUDE_FILES.has(name) || (isDirectory && EXCLUDE_DIRS.has(name));

async function collectV2(dir, prefix, root, ancestors, results) {
  const realDir = await realpath(dir);
  if (ancestors.has(realDir)) return;
  const branch = new Set(ancestors).add(realDir);
  const entries = await readdir(dir, { withFileTypes: true });
  await Promise.all(entries.map(async (entry) => {
    if (excluded(entry.name, entry.isDirectory())) return;
    const fullPath = join(dir, entry.name);
    const path = prefix + entry.name;
    let isDirectory = entry.isDirectory();
    if (entry.isSymbolicLink()) {
      // Symlinks are followed only when they stay inside the skill folder.
      const target = await realpath(fullPath).catch(() => null);
      if (!target || (target !== root && !target.startsWith(root + sep))) return;
      isDirectory = (await stat(target)).isDirectory();
      if (isDirectory && excluded(entry.name, true)) return;
    } else if (!isDirectory && !entry.isFile()) return;
    if (isDirectory) await collectV2(fullPath, `${path}/`, root, branch, results);
    else results.push({ path, content: await readFile(fullPath) });
  }));
}

function normalizeLineEndings(content) {
  if (content.includes(0) || !content.includes('\r\n')) return content;
  return Buffer.from(content.toString('latin1').replaceAll('\r\n', '\n'), 'latin1');
}

async function v2Hash(skillDir) {
  const files = [];
  await collectV2(skillDir, '', await realpath(skillDir), new Set(), files);
  const entries = files.map((file) => ({
    path: Buffer.from(file.path.split('\\').join('/'), 'utf-8'),
    content: normalizeLineEndings(file.content),
  }));
  entries.sort((a, b) => Buffer.compare(a.path, b.path));
  const hash = createHash('sha256');
  for (const { path, content } of entries) {
    hash.update(path);
    hash.update('\0');
    hash.update(String(content.length));
    hash.update('\0');
    hash.update(content);
  }
  return hash.digest('hex');
}

const lines = await Promise.all(
  process.argv.slice(2).map(async (dir) => `${await legacyHash(dir)} ${await v2Hash(dir)}`),
);
console.log(lines.join('\n'));
