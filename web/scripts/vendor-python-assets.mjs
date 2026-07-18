import { createHash } from 'node:crypto';
import {
  copyFile,
  mkdir,
  readFile,
  readdir,
  rm,
  writeFile,
} from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const RUNTIME_ASSET_NAMES = [
  'pyodide-lock.json',
  'pyodide.asm.mjs',
  'pyodide.asm.wasm',
  'pyodide.mjs',
  'python_stdlib.zip',
];

const PYODIDE_CDN_ROOT = 'https://cdn.jsdelivr.net/pyodide/v314.0.2/full/';
const SCRIPT_DIRECTORY = dirname(fileURLToPath(import.meta.url));
const WEB_ROOT = join(SCRIPT_DIRECTORY, '..');
const PYODIDE_PACKAGE_ROOT = join(WEB_ROOT, 'node_modules', 'pyodide');
const PYODIDE_OUTPUT_ROOT = join(WEB_ROOT, 'public', 'pyodide');
const PYTHON_OUTPUT_ROOT = join(WEB_ROOT, 'public', 'python');
const BROWSER_LOCK_PATH = join(WEB_ROOT, '..', 'cli', 'browser', 'browser-lock.json');

export function pyodidePackageDestination(fileName) {
  return join(PYODIDE_OUTPUT_ROOT, fileName);
}

export function resolvePackageClosure(lock, roots) {
  const selected = new Set();

  function visit(name) {
    const packageKey = name.toLowerCase().replace(/[-_.]+/g, '-');
    if (selected.has(packageKey)) {
      return;
    }
    const entry = lock.packages[packageKey];
    if (!entry) {
      throw new Error(`Pyodide lock does not contain package: ${name}`);
    }
    selected.add(packageKey);
    for (const dependency of entry.depends) {
      visit(dependency);
    }
  }

  for (const root of roots) {
    visit(root);
  }
  return [...selected].sort();
}

export function verifySha256(bytes, expected) {
  const actual = createHash('sha256').update(bytes).digest('hex');
  if (actual !== expected.toLowerCase()) {
    throw new Error(`SHA-256 mismatch: expected ${expected}, received ${actual}`);
  }
}

async function readJson(path) {
  return JSON.parse(await readFile(path, 'utf8'));
}

async function downloadVerified(url, destination, expectedSha256) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Download failed (${response.status}): ${url}`);
  }
  const bytes = new Uint8Array(await response.arrayBuffer());
  verifySha256(bytes, expectedSha256);
  await writeFile(destination, bytes);
}

async function cleanVendoredPythonAssets(fileNames) {
  await mkdir(PYTHON_OUTPUT_ROOT, { recursive: true });
  await Promise.all([
    ...fileNames.map((fileName) => rm(join(PYTHON_OUTPUT_ROOT, fileName), { force: true })),
    rm(join(PYTHON_OUTPUT_ROOT, 'runtime-manifest.json'), { force: true }),
  ]);
}

export async function vendorPythonAssets() {
  const browserLock = await readJson(BROWSER_LOCK_PATH);
  const pyodideLock = await readJson(join(PYODIDE_PACKAGE_ROOT, 'pyodide-lock.json'));
  const selectedPackages = resolvePackageClosure(pyodideLock, browserLock.roots);
  const packageEntries = selectedPackages.map((name) => pyodideLock.packages[name]);
  const externalWheels = browserLock.externalWheels;

  await rm(PYODIDE_OUTPUT_ROOT, { recursive: true, force: true });
  await mkdir(PYODIDE_OUTPUT_ROOT, { recursive: true });
  await cleanVendoredPythonAssets([
    ...packageEntries.map((entry) => entry.file_name),
    ...externalWheels.map((wheel) => wheel.fileName),
  ]);

  await Promise.all(
    RUNTIME_ASSET_NAMES.map((fileName) =>
      copyFile(join(PYODIDE_PACKAGE_ROOT, fileName), join(PYODIDE_OUTPUT_ROOT, fileName)),
    ),
  );

  for (const entry of packageEntries) {
    await downloadVerified(
      new URL(entry.file_name, PYODIDE_CDN_ROOT),
      pyodidePackageDestination(entry.file_name),
      entry.sha256,
    );
  }
  for (const wheel of externalWheels) {
    await downloadVerified(
      wheel.url,
      join(PYTHON_OUTPUT_ROOT, wheel.fileName),
      wheel.sha256,
    );
  }

  const browserManifest = await readJson(join(PYTHON_OUTPUT_ROOT, 'browser-manifest.json'));
  const modelableWheel = browserManifest.wheel;
  const outputNames = await readdir(PYTHON_OUTPUT_ROOT);
  if (!outputNames.includes(modelableWheel)) {
    throw new Error(`Generated Modelable wheel is missing: ${modelableWheel}`);
  }

  const wheelUrls = [
    ...externalWheels.map((wheel) => `/modelable/playground/python/${wheel.fileName}`),
    `/modelable/playground/python/${modelableWheel}`,
  ].sort();
  await writeFile(
    join(PYTHON_OUTPUT_ROOT, 'runtime-manifest.json'),
    `${JSON.stringify({ wheelUrls }, null, 2)}\n`,
    'utf8',
  );
}

const invokedPath = process.argv[1] ? pathToFileURL(process.argv[1]).href : undefined;
if (import.meta.url === invokedPath) {
  await vendorPythonAssets();
}
