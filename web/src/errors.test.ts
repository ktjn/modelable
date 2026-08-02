import { describe, expect, it } from 'vitest';

import { toErrorMessage } from './errors';

describe('toErrorMessage', () => {
  it('returns the message from an Error instance', () => {
    expect(toErrorMessage(new Error('boom'), 'fallback')).toBe('boom');
  });

  it('returns the fallback for a non-Error value', () => {
    expect(toErrorMessage('a string was thrown', 'fallback')).toBe('fallback');
  });

  it('returns the fallback for undefined', () => {
    expect(toErrorMessage(undefined, 'fallback')).toBe('fallback');
  });

  it('returns the fallback for a plain object', () => {
    expect(toErrorMessage({ reason: 'nope' }, 'fallback')).toBe('fallback');
  });

  it('returns an Error subclass message unchanged', () => {
    class CustomError extends Error {}
    expect(toErrorMessage(new CustomError('custom failure'), 'fallback')).toBe(
      'custom failure',
    );
  });
});
