import { describe, expect, test } from 'vitest';

import { isLayoutError } from './graph-types';
import type {
  LayoutError,
  LayoutResponse,
  LayoutWorkerResponse,
} from './graph-types';

describe('isLayoutError', () => {
  test('returns true for error responses', () => {
    const error: LayoutError = { id: '1', error: 'Layout failed' };
    expect(isLayoutError(error)).toBe(true);
  });

  test('returns false for success responses', () => {
    const success: LayoutResponse = { id: '1', nodes: [], edges: [] };
    expect(isLayoutError(success)).toBe(false);
  });

  test('discriminates union correctly', () => {
    const response: LayoutWorkerResponse = { id: '1', error: 'fail' };
    if (isLayoutError(response)) {
      expect(response.error).toBe('fail');
    } else {
      expect.unreachable('Should be an error response');
    }
  });
});
