import { describe, expect, test } from 'vitest';

import {
  isBrowserCompilerRequest,
  isBrowserCompilerResponse,
} from './protocol';

describe('isBrowserCompilerRequest', () => {
  const valid = {
    protocolVersion: 1,
    id: 'request-1',
    method: 'workspace.open',
    payload: { sources: [] },
  };

  test.each([null, undefined, 1, 'request', []])(
    'rejects non-object value %j',
    (value) => {
      expect(isBrowserCompilerRequest(value)).toBe(false);
    },
  );

  test('rejects unsupported protocol versions', () => {
    expect(isBrowserCompilerRequest({ ...valid, protocolVersion: 2 })).toBe(
      false,
    );
  });

  test.each([undefined, '', 42])('rejects invalid request IDs %j', (id) => {
    expect(isBrowserCompilerRequest({ ...valid, id })).toBe(false);
  });

  test('rejects unknown methods', () => {
    expect(
      isBrowserCompilerRequest({ ...valid, method: 'compile.unknown' }),
    ).toBe(false);
  });

  test('accepts a valid request', () => {
    expect(isBrowserCompilerRequest(valid)).toBe(true);
  });
});

describe('isBrowserCompilerResponse', () => {
  const success = {
    protocolVersion: 1,
    id: 'request-1',
    ok: true,
    result: undefined,
  };

  test.each([null, undefined, 1, 'response', []])(
    'rejects non-object value %j',
    (value) => {
      expect(isBrowserCompilerResponse(value)).toBe(false);
    },
  );

  test('rejects unsupported protocol versions', () => {
    expect(
      isBrowserCompilerResponse({ ...success, protocolVersion: 2 }),
    ).toBe(false);
  });

  test.each([undefined, '', 42])('rejects invalid response IDs %j', (id) => {
    expect(isBrowserCompilerResponse({ ...success, id })).toBe(false);
  });

  test('rejects success envelopes without a result property', () => {
    const { result: _result, ...withoutResult } = success;
    expect(isBrowserCompilerResponse(withoutResult)).toBe(false);
  });

  test('rejects failures with unknown error codes', () => {
    expect(
      isBrowserCompilerResponse({
        protocolVersion: 1,
        id: 'request-1',
        ok: false,
        error: { code: 'SECRET_ERROR', message: 'nope' },
      }),
    ).toBe(false);
  });

  test('accepts valid success and failure responses', () => {
    expect(isBrowserCompilerResponse(success)).toBe(true);
    expect(
      isBrowserCompilerResponse({
        protocolVersion: 1,
        id: 'request-1',
        ok: false,
        error: { code: 'COMPILER_FAILED', message: 'Compiler failed' },
      }),
    ).toBe(true);
  });
});
