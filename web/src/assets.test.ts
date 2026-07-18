import { access, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, describe, expect, test } from 'vitest';

// @ts-expect-error The production vendor is an ESM JavaScript command module.
import { RUNTIME_ASSET_NAMES, cleanVendoredPythonAssets, pyodidePackageDestination, resolvePackageClosure, safeAssetDestination, verifySha256 } from '../scripts/vendor-python-assets.mjs';

const temporaryDirectories: string[] = [];

function browserManifest(wheel = 'modelable.whl') {
  return {
    schemaVersion: 1,
    distribution: 'modelable-browser',
    version: '1.2.1',
    commit: 'a'.repeat(40),
    wheel,
    sha256: 'b'.repeat(64),
    pyodide: '314.0.2',
    python: '3.14.2',
    platform: 'pyemscripten_2026_0_wasm32',
  };
}

async function temporaryDirectory(): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), 'modelable-assets-'));
  temporaryDirectories.push(directory);
  return directory;
}

async function writeBrowserArtifacts(pythonRoot: string, wheel = 'modelable.whl'): Promise<void> {
  await mkdir(pythonRoot, { recursive: true });
  await Promise.all([
    writeFile(join(pythonRoot, 'browser-manifest.json'), JSON.stringify(browserManifest(wheel))),
    writeFile(join(pythonRoot, wheel), 'modelable'),
    writeFile(join(pythonRoot, 'runtime-manifest.json'), 'preserve until plan is valid'),
  ]);
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
      await writeBrowserArtifacts(pythonRoot);
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
    await writeBrowserArtifacts(pythonRoot);
    await Promise.all([
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

  test.each([
    ['malformed JSON', '{'],
    ['null', 'null'],
    ['an array', '[]'],
    ['the wrong schema version', JSON.stringify({ schemaVersion: 2, externalWheels: [] })],
    [
      'a non-string entry',
      JSON.stringify({ schemaVersion: 1, externalWheels: [42] }),
    ],
    [
      'a non-wheel basename',
      JSON.stringify({ schemaVersion: 1, externalWheels: ['dependency.zip'] }),
    ],
    [
      'the browser manifest',
      JSON.stringify({ schemaVersion: 1, externalWheels: ['browser-manifest.json'] }),
    ],
    [
      'the generated Modelable wheel',
      JSON.stringify({ schemaVersion: 1, externalWheels: ['modelable.whl'] }),
    ],
  ])('rejects prior vendor manifest containing %s before cleanup', async (_case, contents) => {
    const pythonRoot = await temporaryDirectory();
    await writeBrowserArtifacts(pythonRoot);
    await writeFile(join(pythonRoot, 'vendor-manifest.json'), contents);

    await expect(cleanVendoredPythonAssets(pythonRoot, [])).rejects.toThrow();
    await expect(readFile(join(pythonRoot, 'runtime-manifest.json'), 'utf8')).resolves.toBe(
      'preserve until plan is valid',
    );
    await expect(access(join(pythonRoot, 'modelable.whl'))).resolves.toBeUndefined();
  });

  test.each(['browser-manifest.json', 'modelable.whl'])(
    'rejects current external wheel targeting protected %s before cleanup',
    async (fileName) => {
      const pythonRoot = await temporaryDirectory();
      await writeBrowserArtifacts(pythonRoot);

      await expect(cleanVendoredPythonAssets(pythonRoot, [fileName])).rejects.toThrow();
      await expect(readFile(join(pythonRoot, 'runtime-manifest.json'), 'utf8')).resolves.toBe(
        'preserve until plan is valid',
      );
      await expect(access(join(pythonRoot, 'modelable.whl'))).resolves.toBeUndefined();
    },
  );

  test.each([
    ['a non-object value', 'null'],
    ['the wrong schema version', JSON.stringify({ ...browserManifest(), schemaVersion: 2 })],
    ['an unsafe wheel name', JSON.stringify(browserManifest('../modelable.whl'))],
  ])('rejects browser manifest with %s before cleanup', async (_case, contents) => {
    const pythonRoot = await temporaryDirectory();
    await writeBrowserArtifacts(pythonRoot);
    await writeFile(join(pythonRoot, 'browser-manifest.json'), contents);

    await expect(cleanVendoredPythonAssets(pythonRoot, [])).rejects.toThrow();
    await expect(readFile(join(pythonRoot, 'runtime-manifest.json'), 'utf8')).resolves.toBe(
      'preserve until plan is valid',
    );
  });

  test('rejects a missing generated Modelable wheel before cleanup', async () => {
    const pythonRoot = await temporaryDirectory();
    await writeBrowserArtifacts(pythonRoot);
    await rm(join(pythonRoot, 'modelable.whl'));

    await expect(cleanVendoredPythonAssets(pythonRoot, [])).rejects.toThrow(/missing/i);
    await expect(readFile(join(pythonRoot, 'runtime-manifest.json'), 'utf8')).resolves.toBe(
      'preserve until plan is valid',
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
