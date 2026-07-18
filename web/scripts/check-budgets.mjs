import { readdir, readFile } from 'node:fs/promises';
import { relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

export const BUDGETS = {
  modelableWheel: 2 * 1024 * 1024,
  application: 750 * 1024,
  additionalPython: 15 * 1024 * 1024,
};

const CATEGORY_NAMES = Object.keys(BUDGETS);

export function categorizeAsset(path) {
  const normalized = path.replaceAll('\\', '/');
  if (/^python\/modelable_browser-[^/]+\.whl$/.test(normalized)) {
    return 'modelableWheel';
  }
  if (
    normalized === 'index.html' ||
    /^assets\/[^/]+\.css$/.test(normalized) ||
    /^assets\/[^/]+\.js$/.test(normalized)
  ) {
    return 'application';
  }
  if (
    /^pyodide\/[^/]+\.whl$/.test(normalized) ||
    /^python\/lark-[^/]+\.whl$/.test(normalized)
  ) {
    return 'additionalPython';
  }
  return undefined;
}

export function compressedSize(bytes) {
  return gzipSync(bytes).byteLength;
}

export function findViolations(measured) {
  return CATEGORY_NAMES.filter((category) => measured[category] > BUDGETS[category]);
}

async function walkFiles(root, directory = root) {
  const entries = await readdir(directory, { withFileTypes: true });
  const paths = [];
  for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) {
      paths.push(...(await walkFiles(root, path)));
    } else if (entry.isFile()) {
      paths.push(path);
    }
  }
  return paths;
}

export async function measureBudgets(distRoot) {
  const measured = Object.fromEntries(CATEGORY_NAMES.map((category) => [category, 0]));
  for (const path of await walkFiles(distRoot)) {
    const category = categorizeAsset(relative(distRoot, path));
    if (category !== undefined) {
      measured[category] += compressedSize(await readFile(path));
    }
  }
  return measured;
}

export async function main() {
  const distRoot = resolve(fileURLToPath(new URL('../dist', import.meta.url)));
  const measured = await measureBudgets(distRoot);
  const result = Object.fromEntries(
    CATEGORY_NAMES.map((category) => [
      category,
      { measured: measured[category], budget: BUDGETS[category] },
    ]),
  );
  console.log(JSON.stringify(result, null, 2));
  const violations = findViolations(measured);
  if (violations.length > 0) {
    for (const category of violations) {
      console.error(
        `${category} exceeds budget: ${measured[category]} > ${BUDGETS[category]} gzip bytes`,
      );
    }
    return 1;
  }
  return 0;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = await main();
}
