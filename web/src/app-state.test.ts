import { describe, expect, test } from 'vitest';

import { appReducer, initialAppState } from './app-state';

describe('appReducer', () => {
  test('allows only one operation at a time', () => {
    const working = appReducer(
      { ...initialAppState, runtime: 'ready' },
      {
        type: 'operationStarted',
        operation: 'validate',
        revision: 2,
      },
    );
    expect(working.runtime).toBe('working');
    expect(
      appReducer(working, {
        type: 'operationStarted',
        operation: 'generate',
        revision: 2,
      }),
    ).toEqual(working);
  });

  test('rejects diagnostics and artifacts from an older revision', () => {
    const edited = appReducer(
      { ...initialAppState, runtime: 'working', revision: 4 },
      {
        type: 'operationSucceeded',
        operation: 'generate',
        revision: 3,
        diagnostics: [],
        artifacts: [
          {
            path: 'customer.schema.json',
            media_type: 'application/schema+json',
            content: '{}',
            source_refs: [],
          },
        ],
        duration: 12,
      },
    );
    expect(edited.artifacts).toEqual([]);
    expect(edited.runtime).toBe('ready');
    expect(edited.lastOperationDuration).toBe(12);
  });

  test('marks retained artifacts stale after edits and failed generation', () => {
    const state = {
      ...initialAppState,
      runtime: 'ready' as const,
      revision: 2,
      artifactRevision: 1,
      artifacts: [
        {
          path: 'customer.schema.json',
          media_type: 'application/schema+json',
          content: '{}',
          source_refs: [],
        },
      ],
    };
    expect(state.artifactRevision).not.toBe(state.revision);
    const failed = appReducer(state, {
      type: 'operationFailed',
      operation: 'generate',
      revision: 2,
      message: 'Generation failed',
      duration: 5,
    });
    expect(failed.artifacts).toHaveLength(1);
    expect(failed.artifactRevision).toBe(1);
  });
});
