import { createHash } from 'node:crypto';
import {
  access,
  copyFile,
  mkdir,
  readdir,
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
const FIXTURE_SOURCE_ROOT = join(WEB_ROOT, '..', 'cli', 'tests', 'conformance', 'browser');
const FIXTURE_OUTPUT_ROOT = join(WEB_ROOT, 'public', 'fixtures');
const BROWSER_LOCK_PATH = join(WEB_ROOT, '..', 'cli', 'browser', 'browser-lock.json');
const BROWSER_MANIFEST_NAME = 'browser-manifest.json';
const RUNTIME_MANIFEST_NAME = 'runtime-manifest.json';
const VENDOR_MANIFEST_NAME = 'vendor-manifest.json';
const BROWSER_MANIFEST_FIELDS = [
  'commit',
  'distribution',
  'platform',
  'pyodide',
  'python',
  'schemaVersion',
  'sha256',
  'version',
  'wheel',
];
export const BROWSER_CONFORMANCE_SCENARIOS = {
  'invalid-parse': ['invalid-parse.mdl'],
  'invalid-reference': ['invalid-reference.mdl'],
  'invalid-semantic': ['invalid-semantic.mdl'],
  'multi-domain': ['multi-domain-customer.mdl', 'multi-domain-order.mdl'],
  'single-valid': ['single-valid.mdl'],
};

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

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function requireNonemptyString(object, field, manifestName) {
  if (typeof object[field] !== 'string' || object[field].length === 0) {
    throw new Error(`Invalid ${manifestName}: ${field} must be a nonempty string`);
  }
}

function validateBrowserManifest(manifest, pythonRoot) {
  if (!isPlainObject(manifest)) {
    throw new Error('Invalid browser manifest: expected an object');
  }
  const fields = Object.keys(manifest).sort();
  if (
    fields.length !== BROWSER_MANIFEST_FIELDS.length ||
    fields.some((field, index) => field !== BROWSER_MANIFEST_FIELDS[index])
  ) {
    throw new Error('Invalid browser manifest: unexpected fields');
  }
  if (manifest.schemaVersion !== 1) {
    throw new Error('Invalid browser manifest: unsupported schemaVersion');
  }
  if (manifest.distribution !== 'modelable-browser') {
    throw new Error('Invalid browser manifest: unexpected distribution');
  }
  for (const field of ['commit', 'platform', 'pyodide', 'python', 'version']) {
    requireNonemptyString(manifest, field, 'browser manifest');
  }
  if (typeof manifest.sha256 !== 'string' || !/^[0-9a-f]{64}$/i.test(manifest.sha256)) {
    throw new Error('Invalid browser manifest: sha256 must be a hexadecimal SHA-256');
  }
  const wheelDestination = safeAssetDestination(pythonRoot, manifest.wheel);
  if (!manifest.wheel.endsWith('.whl')) {
    throw new Error('Invalid browser manifest: wheel must be a .whl basename');
  }
  return { wheel: manifest.wheel, wheelDestination };
}

function validateExternalWheelName(pythonRoot, fileName, protectedNames, source) {
  const destination = safeAssetDestination(pythonRoot, fileName);
  if (!fileName.endsWith('.whl')) {
    throw new Error(`Invalid ${source}: external entry must be a .whl basename`);
  }
  if (protectedNames.has(fileName.toLowerCase())) {
    throw new Error(`Invalid ${source}: external entry targets protected asset ${fileName}`);
  }
  return destination;
}

function validatePriorVendorManifest(manifest) {
  if (manifest === undefined) {
    return [];
  }
  if (!isPlainObject(manifest)) {
    throw new Error('Invalid vendor manifest: expected an object');
  }
  if (manifest.schemaVersion !== 1) {
    throw new Error('Invalid vendor manifest: unsupported schemaVersion');
  }
  if (!Array.isArray(manifest.externalWheels)) {
    throw new Error('Invalid vendor manifest: externalWheels must be an array');
  }
  return manifest.externalWheels;
}

export async function preparePythonAssetPlan(pythonRoot, currentExternalFileNames) {
  const browserManifestPath = safeAssetDestination(pythonRoot, BROWSER_MANIFEST_NAME);
  const runtimeManifestPath = safeAssetDestination(pythonRoot, RUNTIME_MANIFEST_NAME);
  const vendorManifestPath = safeAssetDestination(pythonRoot, VENDOR_MANIFEST_NAME);
  const browserManifest = await readJson(browserManifestPath);
  const modelable = validateBrowserManifest(browserManifest, pythonRoot);
  try {
    await access(modelable.wheelDestination);
  } catch {
    throw new Error(`Generated Modelable wheel is missing: ${modelable.wheel}`);
  }
  verifySha256(await readFile(modelable.wheelDestination), browserManifest.sha256);

  const protectedNames = new Set(
    [
      BROWSER_MANIFEST_NAME,
      RUNTIME_MANIFEST_NAME,
      VENDOR_MANIFEST_NAME,
      modelable.wheel,
    ].map((name) => name.toLowerCase()),
  );
  const priorManifest = await readJsonIfPresent(vendorManifestPath);
  const priorExternalFileNames = validatePriorVendorManifest(priorManifest);
  const priorDestinations = priorExternalFileNames.map((fileName) =>
    validateExternalWheelName(pythonRoot, fileName, protectedNames, 'vendor manifest'),
  );
  const externalDestinations = currentExternalFileNames.map((fileName) =>
    validateExternalWheelName(pythonRoot, fileName, protectedNames, 'browser lock'),
  );

  return {
    browserManifestPath,
    runtimeManifestPath,
    vendorManifestPath,
    modelableWheel: modelable.wheel,
    cleanupDestinations: [...new Set([...priorDestinations, ...externalDestinations])],
    externalDestinations,
  };
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

function validatedDownload(url, destination, sha256, source) {
  let parsedUrl;
  try {
    parsedUrl = new URL(url);
  } catch {
    throw new Error(`Invalid ${source}: download URL is invalid`);
  }
  if (parsedUrl.protocol !== 'https:') {
    throw new Error(`Invalid ${source}: download URL must use HTTPS`);
  }
  if (typeof sha256 !== 'string' || !/^[0-9a-f]{64}$/i.test(sha256)) {
    throw new Error(`Invalid ${source}: sha256 must be a hexadecimal SHA-256`);
  }
  return { url: parsedUrl, destination, sha256 };
}

async function executePythonCleanup(plan) {
  await Promise.all([
    ...plan.cleanupDestinations.map((destination) => rm(destination, { force: true })),
    rm(plan.runtimeManifestPath, { force: true }),
  ]);
}

export async function cleanVendoredPythonAssets(pythonRoot, currentExternalFileNames) {
  const plan = await preparePythonAssetPlan(pythonRoot, currentExternalFileNames);
  await executePythonCleanup(plan);
}

export async function prepareBrowserConformanceAssetPlan(fixtureRoot, outputRoot) {
  const expectedFixtures = Object.values(BROWSER_CONFORMANCE_SCENARIOS).flat().sort();
  const expectedSnapshots = Object.keys(BROWSER_CONFORMANCE_SCENARIOS)
    .map((name) => `${name}.json`)
    .sort();
  const fixtureNames = (await readdir(fixtureRoot))
    .filter((name) => name.endsWith('.mdl'))
    .sort();
  const snapshotRoot = join(fixtureRoot, 'snapshots');
  const snapshotNames = (await readdir(snapshotRoot))
    .filter((name) => name.endsWith('.json'))
    .sort();

  if (
    JSON.stringify(fixtureNames) !== JSON.stringify(expectedFixtures) ||
    JSON.stringify(snapshotNames) !== JSON.stringify(expectedSnapshots)
  ) {
    throw new Error('Invalid browser conformance asset manifest');
  }

  const entries = [
    ...fixtureNames.map((name) => ({
      relativeName: name,
      source: safeAssetDestination(fixtureRoot, name),
      destination: safeAssetDestination(outputRoot, name),
      kind: 'fixture',
    })),
    ...snapshotNames.map((name) => ({
      relativeName: name,
      source: safeAssetDestination(snapshotRoot, name),
      destination: safeAssetDestination(outputRoot, name),
      kind: 'snapshot',
    })),
  ].sort((left, right) =>
    left.relativeName < right.relativeName ? -1 : left.relativeName > right.relativeName ? 1 : 0,
  );

  for (const entry of entries) {
    const contents = await readFile(entry.source, 'utf8');
    if (contents.length === 0) {
      throw new Error(`Invalid browser conformance asset manifest: ${entry.relativeName} is empty`);
    }
    if (entry.kind === 'snapshot') {
      const snapshot = JSON.parse(contents);
      if (!isPlainObject(snapshot) || !isPlainObject(snapshot.open)) {
        throw new Error(
          `Invalid browser conformance asset manifest: ${entry.relativeName} has no open result`,
        );
      }
    }
  }
  return entries;
}

async function executeBrowserConformanceCopy(plan, outputRoot) {
  await rm(outputRoot, { recursive: true, force: true });
  await mkdir(outputRoot, { recursive: true });
  await Promise.all(plan.map(({ source, destination }) => copyFile(source, destination)));
}

export async function copyBrowserConformanceAssets(fixtureRoot, outputRoot) {
  const plan = await prepareBrowserConformanceAssetPlan(fixtureRoot, outputRoot);
  await executeBrowserConformanceCopy(plan, outputRoot);
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
  const pythonPlan = await preparePythonAssetPlan(
    PYTHON_OUTPUT_ROOT,
    externalWheels.map((wheel) => wheel.fileName),
  );
  const fixturePlan = await prepareBrowserConformanceAssetPlan(
    FIXTURE_SOURCE_ROOT,
    FIXTURE_OUTPUT_ROOT,
  );
  const packageDownloads = packageEntries.map((entry, index) =>
    validatedDownload(
      new URL(entry.file_name, PYODIDE_CDN_ROOT),
      packageDestinations[index],
      entry.sha256,
      'Pyodide lock entry',
    ),
  );
  const externalDownloads = externalWheels.map((wheel, index) =>
    validatedDownload(
      wheel.url,
      pythonPlan.externalDestinations[index],
      wheel.sha256,
      'browser lock external wheel',
    ),
  );
  const runtimeCopies = RUNTIME_ASSET_NAMES.map((fileName) => ({
    source: safeAssetDestination(PYODIDE_PACKAGE_ROOT, fileName),
    destination: safeAssetDestination(PYODIDE_OUTPUT_ROOT, fileName),
  }));
  await Promise.all(runtimeCopies.map(({ source }) => access(source)));

  await executePythonCleanup(pythonPlan);
  await rm(PYODIDE_OUTPUT_ROOT, { recursive: true, force: true });
  await mkdir(PYODIDE_OUTPUT_ROOT, { recursive: true });

  await Promise.all(runtimeCopies.map(({ source, destination }) => copyFile(source, destination)));

  for (const download of packageDownloads) {
    await downloadVerified(download.url, download.destination, download.sha256);
  }
  for (const download of externalDownloads) {
    await downloadVerified(download.url, download.destination, download.sha256);
  }

  const wheelUrls = [
    ...externalWheels.map((wheel) => `/modelable/playground/python/${wheel.fileName}`),
    `/modelable/playground/python/${pythonPlan.modelableWheel}`,
  ].sort();
  await writeFile(
    pythonPlan.runtimeManifestPath,
    `${JSON.stringify({ wheelUrls }, null, 2)}\n`,
    'utf8',
  );
  await writeFile(
    pythonPlan.vendorManifestPath,
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
  await executeBrowserConformanceCopy(fixturePlan, FIXTURE_OUTPUT_ROOT);
}

const invokedPath = process.argv[1] ? pathToFileURL(process.argv[1]).href : undefined;
if (import.meta.url === invokedPath) {
  await vendorPythonAssets();
}
