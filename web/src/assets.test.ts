import { access, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, describe, expect, test } from 'vitest';

// @ts-expect-error The production vendor is an ESM JavaScript command module.
import { RUNTIME_ASSET_NAMES, cleanVendoredPythonAssets, pyodidePackageDestination, resolvePackageClosure, safeAssetDestination, verifySha256 } from '../scripts/vendor-python-assets.mjs';

const temporaryDirectories: string[] = [];

async function temporaryDirectory(): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), 'modelable-assets-'));
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

  test.each([
    '',
    '.',
    '..',
    '../escape.whl',
    'nested/package.whl',
    'nested\\package.whl',
    '/absolute/package.whl',
    'C:\\absolute\\package.whl',
  ])('rejects unsafe lock-controlled destination %j', (fileName) => {
    expect(() => safeAssetDestination('public/python', fileName)).toThrow(/unsafe asset filename/i);
  });

  test.each(['../outside.whl', '/absolute/outside.whl', 'C:\\absolute\\outside.whl'])(
    'rejects unsafe prior vendor filename %j before deleting files',
    async (unsafePriorName) => {
      const parent = await temporaryDirectory();
      const pythonRoot = join(parent, 'python');
      const outsideWheel = join(parent, 'outside.whl');
      await mkdir(pythonRoot);
      await writeFile(outsideWheel, 'preserve');
      await writeFile(
        join(pythonRoot, 'vendor-manifest.json'),
        JSON.stringify({ schemaVersion: 1, externalWheels: [unsafePriorName] }),
      );

      await expect(cleanVendoredPythonAssets(pythonRoot, [])).rejects.toThrow(
        /unsafe asset filename/i,
      );
      await expect(access(outsideWheel)).resolves.toBeUndefined();
    },
  );

  test('removes prior external wheels while preserving generated Modelable artifacts', async () => {
    const pythonRoot = await temporaryDirectory();
    await Promise.all([
      writeFile(join(pythonRoot, 'browser-manifest.json'), '{"wheel":"modelable.whl"}'),
      writeFile(join(pythonRoot, 'modelable.whl'), 'modelable'),
      writeFile(join(pythonRoot, 'lark-old.whl'), 'old'),
      writeFile(join(pythonRoot, 'lark-new.whl'), 'partial'),
      writeFile(
        join(pythonRoot, 'vendor-manifest.json'),
        JSON.stringify({ schemaVersion: 1, externalWheels: ['lark-old.whl'] }),
      ),
    ]);

    await cleanVendoredPythonAssets(pythonRoot, ['lark-new.whl']);

    await expect(access(join(pythonRoot, 'lark-old.whl'))).rejects.toThrow();
    await expect(access(join(pythonRoot, 'lark-new.whl'))).rejects.toThrow();
    await expect(access(join(pythonRoot, 'modelable.whl'))).resolves.toBeUndefined();
    await expect(access(join(pythonRoot, 'browser-manifest.json'))).resolves.toBeUndefined();
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
