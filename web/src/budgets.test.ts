import { mkdir, mkdtemp, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { gzipSync } from 'node:zlib';

import { afterEach, describe, expect, test } from 'vitest';

// @ts-expect-error The production budget checker is an ESM JavaScript command module.
import * as budgetChecker from '../scripts/check-budgets.mjs';

const {
  BUDGETS,
  REPORT_ONLY,
  categorizeAsset,
  compressedSize,
  findViolations,
  measureBudgets,
} = budgetChecker;

const temporaryDirectories: string[] = [];

async function temporaryDirectory(): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), 'modelable-budgets-'));
  temporaryDirectories.push(directory);
  return directory;
}

afterEach(async () => {
  await Promise.all(
    temporaryDirectories.splice(0).map((directory) =>
      rm(directory, { recursive: true, force: true }),
    ),
  );
});

describe('browser asset budgets', () => {
  test('reports named Monaco bundles outside the enforced application budget', () => {
    expect(REPORT_ONLY).toEqual([]);
    for (const path of [
      'assets/monaco-ABC.js',
      'assets/editor.worker-ABC.js',
      'assets/json.worker-ABC.js',
      'chunks/workers/editor.worker-ABC.js',
    ]) {
      expect(categorizeAsset(path)).toBe('monaco');
    }
    expect(categorizeAsset('assets/monaco-ABC.css')).toBe('application');
    expect(categorizeAsset('assets/ai.worker-ABC.js')).toBe('aiWorker');
  });

  test.each([
    ['python/modelable_browser-1.2.1-py3-none-any.whl', 'modelableWheel'],
    ['python/releases/modelable_browser-1.2.1-py3-none-any.whl', 'modelableWheel'],
    ['index.html', 'application'],
    ['assets/index-ABC.js', 'application'],
    ['assets/index-ABC.css', 'application'],
    ['pages/nested/index.html', 'application'],
    ['chunks/nested/worker-ABC.js', 'application'],
    ['styles/nested/index-ABC.css', 'application'],
    ['pyodide/pydantic-2.12.5-py3-none-any.whl', 'additionalPython'],
    ['pyodide/packages/nested/pydantic-2.12.5-py3-none-any.whl', 'additionalPython'],
    ['python/lark-1.3.1-py3-none-any.whl', 'additionalPython'],
    ['python/vendor/nested/lark-1.3.1-py3-none-any.whl', 'additionalPython'],
  ])('categorizes %s as %s', (path, category) => {
    expect(categorizeAsset(path)).toBe(category);
  });

  test.each([
    'pyodide/pyodide.asm.wasm',
    'pyodide/python_stdlib.zip',
    'pyodide/pyodide.mjs',
    'pyodide/pyodide.asm.mjs',
    'pyodide/pyodide-lock.json',
    'pyodide/runtime/nested-loader.js',
    'python/generated/runtime.js',
    'python/browser-manifest.json',
    'fixtures/single-valid.mdl',
    'fixtures/nested/example.html',
  ])('excludes %s from every budget category', (path) => {
    expect(categorizeAsset(path)).toBeUndefined();
  });

  test('computes compressed size from the file bytes with gzip', () => {
    const bytes = Buffer.from('compressible browser asset '.repeat(100));

    expect(compressedSize(bytes)).toBe(gzipSync(bytes).byteLength);
  });

  test('reports every category that exceeds its budget', () => {
    const measured = {
      modelableWheel: BUDGETS.modelableWheel + 1,
      application: BUDGETS.application,
      additionalPython: BUDGETS.additionalPython + 42,
      monaco: BUDGETS.monaco + 1,
      aiWorker: BUDGETS.aiWorker,
    };

    expect(findViolations(measured)).toEqual([
      'modelableWheel',
      'additionalPython',
      'monaco',
    ]);
  });

  test('Monaco within budget does not hide an application violation', () => {
    const measured = {
      modelableWheel: BUDGETS.modelableWheel,
      application: BUDGETS.application + 1,
      additionalPython: BUDGETS.additionalPython,
      monaco: BUDGETS.monaco,
      aiWorker: BUDGETS.aiWorker,
    };

    expect(findViolations(measured)).toEqual(['application']);
  });

  test('measures recursive application and Python assets with exact per-file gzip totals', async () => {
    const root = await temporaryDirectory();
    const assets = {
      'pages/nested/index.html': Buffer.from('<main>nested app</main>'),
      'chunks/nested/index-ABC.js': Buffer.from('export const nested = true;'),
      'chunks/nested/monaco-ABC.js': Buffer.from('export const monaco = true;'),
      'workers/editor.worker-ABC.js': Buffer.from(
        'self.onmessage = () => "editor";',
      ),
      'workers/json.worker-ABC.js': Buffer.from(
        'self.onmessage = () => "json";',
      ),
      'workers/compiler/nested-worker.js': Buffer.from('self.onmessage = () => {};'),
      'workers/ai.worker-ABC.js': Buffer.from('self.onmessage = () => "ai";'),
      'styles/themes/index-ABC.css': Buffer.from('main { color: rebeccapurple; }'),
      'python/releases/modelable_browser-1.2.1-py3-none-any.whl':
        Buffer.from('modelable wheel bytes'),
      'python/vendor/lark/lark-1.3.1-py3-none-any.whl': Buffer.from(
        'lark wheel bytes',
      ),
      'pyodide/packages/pydantic/pydantic-2.12.5-py3-none-any.whl':
        Buffer.from('pydantic wheel bytes'),
      'fixtures/nested/ignored.html': Buffer.from('ignored fixture'),
      'pyodide/runtime/ignored.js': Buffer.from('ignored base runtime loader'),
    };
    for (const [relativePath, bytes] of Object.entries(assets)) {
      const path = join(root, ...relativePath.split('/'));
      await mkdir(dirname(path), { recursive: true });
      await writeFile(path, bytes);
    }

    await expect(measureBudgets(root)).resolves.toEqual({
      modelableWheel: gzipSync(
        assets['python/releases/modelable_browser-1.2.1-py3-none-any.whl'],
      ).byteLength,
      application: [
        assets['pages/nested/index.html'],
        assets['chunks/nested/index-ABC.js'],
        assets['workers/compiler/nested-worker.js'],
        assets['styles/themes/index-ABC.css'],
      ].reduce((total, bytes) => total + gzipSync(bytes).byteLength, 0),
      additionalPython: [
        assets['python/vendor/lark/lark-1.3.1-py3-none-any.whl'],
        assets[
          'pyodide/packages/pydantic/pydantic-2.12.5-py3-none-any.whl'
        ],
      ].reduce((total, bytes) => total + gzipSync(bytes).byteLength, 0),
      monaco: [
        assets['chunks/nested/monaco-ABC.js'],
        assets['workers/editor.worker-ABC.js'],
        assets['workers/json.worker-ABC.js'],
      ].reduce((total, bytes) => total + gzipSync(bytes).byteLength, 0),
      aiWorker: gzipSync(
        assets['workers/ai.worker-ABC.js'],
      ).byteLength,
    });
  });

  test('does not follow directory links or count budget assets outside the root', async () => {
    const root = await temporaryDirectory();
    const outside = await temporaryDirectory();
    await mkdir(join(outside, 'nested'), { recursive: true });
    await Promise.all([
      writeFile(join(root, 'index.html'), 'inside'),
      writeFile(join(outside, 'nested', 'outside.js'), 'outside application'),
      writeFile(
        join(outside, 'nested', 'outside.whl'),
        'outside Python dependency',
      ),
    ]);
    await symlink(
      outside,
      join(root, 'linked-assets'),
      process.platform === 'win32' ? 'junction' : 'dir',
    );

    await expect(measureBudgets(root)).resolves.toEqual({
      modelableWheel: 0,
      application: gzipSync(Buffer.from('inside')).byteLength,
      additionalPython: 0,
      monaco: 0,
      aiWorker: 0,
    });
  });
});
