import { createHash } from 'node:crypto';
import {
  access,
  copyFile,
  mkdir,
  readFile,
  rm,
  writeFile,
} from 'node:fs/promises';
import { basename, dirname, isAbsolute, join, relative, resolve } from 'node:path';
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
const VENDOR_MANIFEST_NAME = 'vendor-manifest.json';

export function pyodidePackageDestination(fileName) {
  return safeAssetDestination(PYODIDE_OUTPUT_ROOT, fileName);
}

export function safeAssetDestination(root, fileName) {
  if (
    typeof fileName !== 'string' ||
    fileName.length === 0 ||
    fileName === '.' ||
    fileName === '..' ||
    isAbsolute(fileName) ||
    fileName.includes('/') ||
    fileName.includes('\\') ||
    basename(fileName) !== fileName
  ) {
    throw new Error(`Unsafe asset filename: ${String(fileName)}`);
  }

  const resolvedRoot = resolve(root);
  const destination = resolve(resolvedRoot, fileName);
  const relativeDestination = relative(resolvedRoot, destination);
  if (
    relativeDestination.length === 0 ||
    relativeDestination.startsWith(`..${process.platform === 'win32' ? '\\' : '/'}`) ||
    relativeDestination === '..' ||
    isAbsolute(relativeDestination)
  ) {
    throw new Error(`Unsafe asset filename: ${fileName}`);
  }
  return destination;
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

async function readJsonIfPresent(path) {
  try {
    return await readJson(path);
  } catch (error) {
    if (error?.code === 'ENOENT') {
      return undefined;
    }
    throw error;
  }
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

export async function cleanVendoredPythonAssets(pythonRoot, currentExternalFileNames) {
  const vendorManifestPath = safeAssetDestination(pythonRoot, VENDOR_MANIFEST_NAME);
  const priorManifest = await readJsonIfPresent(vendorManifestPath);
  const priorExternalFileNames = priorManifest?.externalWheels ?? [];
  if (!Array.isArray(priorExternalFileNames)) {
    throw new Error('Invalid vendor manifest: externalWheels must be an array');
  }
  const destinations = [...new Set([...priorExternalFileNames, ...currentExternalFileNames])].map(
    (fileName) => safeAssetDestination(pythonRoot, fileName),
  );
  const runtimeManifestPath = safeAssetDestination(pythonRoot, 'runtime-manifest.json');

  await mkdir(pythonRoot, { recursive: true });
  await Promise.all([
    ...destinations.map((destination) => rm(destination, { force: true })),
    rm(runtimeManifestPath, { force: true }),
  ]);
}

export async function vendorPythonAssets() {
  const browserLock = await readJson(BROWSER_LOCK_PATH);
  const pyodideLock = await readJson(join(PYODIDE_PACKAGE_ROOT, 'pyodide-lock.json'));
  const selectedPackages = resolvePackageClosure(pyodideLock, browserLock.roots);
  const packageEntries = selectedPackages.map((name) => pyodideLock.packages[name]);
  const externalWheels = browserLock.externalWheels;
  const packageDestinations = packageEntries.map((entry) =>
    pyodidePackageDestination(entry.file_name),
  );
  const externalDestinations = externalWheels.map((wheel) =>
    safeAssetDestination(PYTHON_OUTPUT_ROOT, wheel.fileName),
  );

  await cleanVendoredPythonAssets(
    PYTHON_OUTPUT_ROOT,
    externalWheels.map((wheel) => wheel.fileName),
  );
  await rm(PYODIDE_OUTPUT_ROOT, { recursive: true, force: true });
  await mkdir(PYODIDE_OUTPUT_ROOT, { recursive: true });

  await Promise.all(
    RUNTIME_ASSET_NAMES.map((fileName) =>
      copyFile(join(PYODIDE_PACKAGE_ROOT, fileName), join(PYODIDE_OUTPUT_ROOT, fileName)),
    ),
  );

  for (const [index, entry] of packageEntries.entries()) {
    await downloadVerified(
      new URL(entry.file_name, PYODIDE_CDN_ROOT),
      packageDestinations[index],
      entry.sha256,
    );
  }
  for (const [index, wheel] of externalWheels.entries()) {
    await downloadVerified(wheel.url, externalDestinations[index], wheel.sha256);
  }

  const browserManifest = await readJson(join(PYTHON_OUTPUT_ROOT, 'browser-manifest.json'));
  const modelableWheel = browserManifest.wheel;
  const modelableDestination = safeAssetDestination(PYTHON_OUTPUT_ROOT, modelableWheel);
  try {
    await access(modelableDestination);
  } catch {
    throw new Error(`Generated Modelable wheel is missing: ${modelableWheel}`);
  }

  const wheelUrls = [
    ...externalWheels.map((wheel) => `/modelable/playground/python/${wheel.fileName}`),
    `/modelable/playground/python/${modelableWheel}`,
  ].sort();
  await writeFile(
    safeAssetDestination(PYTHON_OUTPUT_ROOT, 'runtime-manifest.json'),
    `${JSON.stringify({ wheelUrls }, null, 2)}\n`,
    'utf8',
  );
  await writeFile(
    safeAssetDestination(PYTHON_OUTPUT_ROOT, VENDOR_MANIFEST_NAME),
    `${JSON.stringify(
      {
        schemaVersion: 1,
        externalWheels: externalWheels.map((wheel) => wheel.fileName).sort(),
      },
      null,
      2,
    )}\n`,
    'utf8',
  );
}

const invokedPath = process.argv[1] ? pathToFileURL(process.argv[1]).href : undefined;
if (import.meta.url === invokedPath) {
  await vendorPythonAssets();
}
