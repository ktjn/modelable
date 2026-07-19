import { describe, expect, test } from 'vitest';

import { appReducer, initialAppState } from './app-state';

const customerArtifact = {
  path: 'customer.schema.json',
  media_type: 'application/schema+json',
  content: '{"title":"Customer"}',
  source_refs: ['file:///main.mdl'],
};

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
    expect(failed.artifactRevision).toBeNull();
  });

  test('invalidates retained current artifacts after generation failure and restores them after success', () => {
    const current = {
      ...initialAppState,
      runtime: 'working' as const,
      operation: 'generate' as const,
      revision: 2,
      artifactRevision: 2,
      artifacts: [customerArtifact],
      selectedArtifactPath: customerArtifact.path,
    };
    const failed = appReducer(current, {
      type: 'operationFailed',
      operation: 'generate',
      revision: 2,
      message: 'Generation failed',
      duration: 5,
    });
    expect(failed.artifacts).toEqual([customerArtifact]);
    expect(failed.selectedArtifactPath).toBe(customerArtifact.path);
    expect(failed.artifactRevision).toBeNull();

    const regenerated = appReducer(
      { ...failed, runtime: 'working', operation: 'generate' },
      {
        type: 'operationSucceeded',
        operation: 'generate',
        revision: 2,
        diagnostics: [],
        artifacts: [customerArtifact],
        duration: 6,
      },
    );
    expect(regenerated.artifactRevision).toBe(2);
  });

  test('invalidates retained current artifacts when the runtime fails during generation', () => {
    const failed = appReducer(
      {
        ...initialAppState,
        runtime: 'working',
        operation: 'generate',
        revision: 2,
        artifactRevision: 2,
        artifacts: [customerArtifact],
        selectedArtifactPath: customerArtifact.path,
      },
      {
        type: 'runtimeFailed',
        operation: 'generate',
        revision: 2,
        message: 'Compiler worker failed',
        duration: 5,
      },
    );
    expect(failed.artifacts).toEqual([customerArtifact]);
    expect(failed.selectedArtifactPath).toBe(customerArtifact.path);
    expect(failed.artifactRevision).toBeNull();
  });

  test('does not invalidate newer artifacts after an older generation fails', () => {
    const current = {
      ...initialAppState,
      runtime: 'working' as const,
      operation: 'generate' as const,
      revision: 3,
      artifactRevision: 3,
      artifacts: [customerArtifact],
      selectedArtifactPath: customerArtifact.path,
    };
    const recoverableFailure = appReducer(current, {
      type: 'operationFailed',
      operation: 'generate',
      revision: 2,
      message: 'Older generation failed',
      duration: 5,
    });
    expect(recoverableFailure.artifactRevision).toBe(3);

    const runtimeFailure = appReducer(current, {
      type: 'runtimeFailed',
      operation: 'generate',
      revision: 2,
      message: 'Older compiler request failed',
      duration: 6,
    });
    expect(runtimeFailure.artifactRevision).toBe(3);
  });
});
