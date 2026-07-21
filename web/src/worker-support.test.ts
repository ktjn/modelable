import { describe, expect, test, vi } from 'vitest';

import type { BrowserCompilerRequest } from './protocol';
import {
  dispatchPythonRequest,
  validatePythonRuntime,
  validateRuntimeManifest,
} from './worker-support';

const manifestUrl = new URL(
  'https://example.test/modelable/playground/python/runtime-manifest.json',
);
const larkUrl =
  'https://example.test/modelable/playground/python/lark-1.3.1-py3-none-any.whl';
const modelableUrl =
  'https://example.test/modelable/playground/python/modelable_browser-1.2.1-py3-none-any.whl';

function request(payload: unknown): BrowserCompilerRequest {
  return {
    protocolVersion: 2,
    id: 'request-1',
    method: 'source.format',
    payload,
  };
}

describe('validateRuntimeManifest', () => {
  test('accepts exactly the locked Lark and generated Modelable wheels', () => {
    expect(
      validateRuntimeManifest(
        { wheelUrls: [larkUrl, modelableUrl] },
        manifestUrl,
      ),
    ).toEqual([larkUrl, modelableUrl]);
  });

  test('rejects extra wheels', () => {
    expect(() =>
      validateRuntimeManifest(
        {
          wheelUrls: [
            larkUrl,
            modelableUrl,
            'https://example.test/modelable/playground/python/extra-1.0-py3-none-any.whl',
          ],
        },
        manifestUrl,
      ),
    ).toThrow('exactly two wheel URLs');
  });

  test('rejects duplicate wheels', () => {
    expect(() =>
      validateRuntimeManifest(
        { wheelUrls: [larkUrl, larkUrl] },
        manifestUrl,
      ),
    ).toThrow('distinct');
  });

  test('rejects manifests missing a required wheel identity', () => {
    expect(() =>
      validateRuntimeManifest(
        {
          wheelUrls: [
            larkUrl,
            'https://example.test/modelable/playground/python/unrelated-1.0-py3-none-any.whl',
          ],
        },
        manifestUrl,
      ),
    ).toThrow('Modelable');
  });

  test('rejects off-origin wheels', () => {
    expect(() =>
      validateRuntimeManifest(
        {
          wheelUrls: [
            'https://cdn.example/lark-1.3.1-py3-none-any.whl',
            modelableUrl,
          ],
        },
        manifestUrl,
      ),
    ).toThrow('same-origin');
  });

  test('rejects sibling paths that merely share the python prefix', () => {
    expect(() =>
      validateRuntimeManifest(
        {
          wheelUrls: [
            'https://example.test/modelable/playground/python-evil/lark-1.3.1-py3-none-any.whl',
            modelableUrl,
          ],
        },
        manifestUrl,
      ),
    ).toThrow('python directory');
  });
});

describe('validatePythonRuntime', () => {
  test('accepts only the locked CPython and Emscripten platform', () => {
    expect(() =>
      validatePythonRuntime('3.14.2', 'emscripten'),
    ).not.toThrow();
    expect(() => validatePythonRuntime('3.14.1', 'emscripten')).toThrow(
      'CPython 3.14.2',
    );
    expect(() => validatePythonRuntime('3.14.2', 'linux')).toThrow(
      'Emscripten',
    );
  });
});

describe('dispatchPythonRequest', () => {
  test.each([
    ['cyclic', () => {
      const payload: Record<string, unknown> = {
        source: { text: 'TOP SECRET SOURCE' },
      };
      payload.self = payload;
      return payload;
    }],
    [
      'BigInt',
      () => ({ source: { text: 'TOP SECRET SOURCE', version: 1n } }),
    ],
  ])(
    'classifies structured-clone-compatible non-JSON %s payloads as invalid requests',
    (_name, payload) => {
      const dispatcher = vi.fn();

      const response = dispatchPythonRequest(request(payload()), dispatcher);

      expect(response).toEqual({
        protocolVersion: 2,
        id: 'request-1',
        ok: false,
        error: {
          code: 'INVALID_REQUEST',
          message: 'Browser compiler request is invalid',
        },
      });
      expect(JSON.stringify(response)).not.toContain('TOP SECRET SOURCE');
      expect(dispatcher).not.toHaveBeenCalled();
    },
  );

  test('classifies dispatcher exceptions as compiler failures', () => {
    const response = dispatchPythonRequest(request({ source: {} }), () => {
      throw new Error('checkout path and source text');
    });

    expect(response).toMatchObject({
      ok: false,
      error: {
        code: 'COMPILER_FAILED',
        message: 'Compiler request failed',
      },
    });
    expect(JSON.stringify(response)).not.toContain('checkout path');
  });

  test('preserves sanitized typed language failures from Python', () => {
    const response = dispatchPythonRequest(
      request({
        workspaceRevision: 1,
        uri: 'file:///main.mdl',
        line: 0,
        character: 0,
      }),
      () =>
        JSON.stringify({
          ok: false,
          error: {
            code: 'STALE_WORKSPACE',
            message: 'Requested workspace revision is not current',
          },
        }),
    );

    expect(response).toEqual({
      protocolVersion: 2,
      id: 'request-1',
      ok: false,
      error: {
        code: 'STALE_WORKSPACE',
        message: 'Requested workspace revision is not current',
      },
    });
  });
});
