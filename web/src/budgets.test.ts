import { gzipSync } from 'node:zlib';

import { describe, expect, test } from 'vitest';

// @ts-expect-error The production budget checker is an ESM JavaScript command module.
import { BUDGETS, categorizeAsset, compressedSize, findViolations } from '../scripts/check-budgets.mjs';

describe('browser asset budgets', () => {
  test.each([
    ['python/modelable_browser-1.2.1-py3-none-any.whl', 'modelableWheel'],
    ['index.html', 'application'],
    ['assets/index-ABC.js', 'application'],
    ['assets/index-ABC.css', 'application'],
    ['pyodide/pydantic-2.12.5-py3-none-any.whl', 'additionalPython'],
    ['python/lark-1.3.1-py3-none-any.whl', 'additionalPython'],
  ])('categorizes %s as %s', (path, category) => {
    expect(categorizeAsset(path)).toBe(category);
  });

  test.each([
    'pyodide/pyodide.asm.wasm',
    'pyodide/python_stdlib.zip',
    'pyodide/pyodide.mjs',
    'pyodide/pyodide.asm.mjs',
    'pyodide/pyodide-lock.json',
    'python/browser-manifest.json',
    'fixtures/single-valid.mdl',
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
    };

    expect(findViolations(measured)).toEqual([
      'modelableWheel',
      'additionalPython',
    ]);
  });
});
