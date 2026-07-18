import { readFile } from 'node:fs/promises';

import { describe, expect, test } from 'vitest';

// @ts-expect-error The production vendor is an ESM JavaScript command module.
import { RUNTIME_ASSET_NAMES, pyodidePackageDestination, resolvePackageClosure, verifySha256 } from '../scripts/vendor-python-assets.mjs';

describe('same-origin Python assets', () => {
  test('resolves and sorts the recursive package closure', () => {
    const lock = {
      packages: {
        'annotated-types': { depends: [] },
        pydantic: {
          depends: ['annotated-types', 'pydantic-core', 'typing-extensions', 'typing-inspection'],
        },
        'pydantic-core': { depends: ['typing-extensions'] },
        'typing-extensions': { depends: [] },
        'typing-inspection': { depends: ['typing-extensions'] },
      },
    };

    expect(resolvePackageClosure(lock, ['pydantic'])).toEqual([
      'annotated-types',
      'pydantic',
      'pydantic-core',
      'typing-extensions',
      'typing-inspection',
    ]);
  });

  test('normalizes Pyodide dependency names to package keys', () => {
    const lock = {
      packages: {
        pydantic: { depends: ['pydantic_core'] },
        'pydantic-core': { depends: [] },
      },
    };

    expect(resolvePackageClosure(lock, ['pydantic'])).toEqual(['pydantic', 'pydantic-core']);
  });

  test('rejects a checksum mismatch', () => {
    expect(() => verifySha256(new TextEncoder().encode('bytes'), '0'.repeat(64))).toThrow(
      /SHA-256 mismatch/,
    );
  });

  test('vendors exactly the required Pyodide runtime files', () => {
    expect(RUNTIME_ASSET_NAMES).toEqual([
      'pyodide-lock.json',
      'pyodide.asm.mjs',
      'pyodide.asm.wasm',
      'pyodide.mjs',
      'python_stdlib.zip',
    ]);
  });

  test('places locked packages beside the Pyodide lockfile', () => {
    expect(pyodidePackageDestination('pydantic.whl').replaceAll('\\', '/')).toMatch(
      /\/public\/pyodide\/pydantic\.whl$/,
    );
  });

  test('restricts the browser runtime with a same-origin CSP', async () => {
    const html = await readFile(new URL('../index.html', import.meta.url), 'utf8');

    expect(html).toContain("script-src 'self' 'wasm-unsafe-eval'");
    expect(html).toContain("worker-src 'self'");
    expect(html).toContain("connect-src 'self'");
    expect(html).toContain("object-src 'none'");
    expect(html).toContain("base-uri 'none'");
  });
});
