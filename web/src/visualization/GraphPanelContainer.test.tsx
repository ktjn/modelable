// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { createRef } from 'react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { BrowserCompilerError } from '../client';
import type { BrowserCompilerClientLike } from '../client';
import type { BrowserGraphMode, BrowserGraphResult } from '../protocol';
import { GraphPanelContainer } from './GraphPanelContainer';

vi.mock('./GraphPanel', () => ({
  GraphPanel: ({
    graphResult,
    error,
  }: {
    graphResult: BrowserGraphResult | null;
    error: string | null;
  }) => (
    <div>
      <span data-testid="rendered-revision">
        {graphResult === null ? 'none' : String(graphResult.workspace_revision)}
      </span>
      <span data-testid="rendered-error">{error ?? 'none'}</span>
    </div>
  ),
}));

// The container defers its first request to idle time; jsdom has no idle
// callback, so run the callback as soon as it is scheduled.
beforeEach(() => {
  globalThis.requestIdleCallback = (callback: IdleRequestCallback) => {
    callback({ didTimeout: true, timeRemaining: () => 0 });
    return 0;
  };
  globalThis.cancelIdleCallback = () => undefined;
});

afterEach(cleanup);

const settle = { timeout: 3000 };

function graphResult(
  workspace_revision: number,
  mode: BrowserGraphMode = 'domain',
): BrowserGraphResult {
  return {
    workspace_revision,
    mode,
    graph: { schema_version: 1, nodes: [], edges: [] },
  };
}

function clientRefWith(graph: BrowserCompilerClientLike['graph']) {
  const ref = createRef<BrowserCompilerClientLike | null>();
  ref.current = { graph } as unknown as BrowserCompilerClientLike;
  return ref as React.RefObject<BrowserCompilerClientLike | null>;
}

describe('GraphPanelContainer', () => {
  test('requests the graph for the synchronized revision', async () => {
    const graph = vi.fn(async (revision: number) => graphResult(revision));
    render(
      <GraphPanelContainer
        clientRef={clientRefWith(graph)}
        runtimeReady
        languageRevision={4}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId('rendered-revision').textContent).toBe('4');
    }, settle);
    expect(graph).toHaveBeenCalledWith(4, 'domain');
  });

  test('refetches when a newer revision is synchronized', async () => {
    const graph = vi.fn(async (revision: number) => graphResult(revision));
    const clientRef = clientRefWith(graph);
    const { rerender } = render(
      <GraphPanelContainer
        clientRef={clientRef}
        runtimeReady
        languageRevision={1}
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId('rendered-revision').textContent).toBe('1');
    }, settle);

    rerender(
      <GraphPanelContainer
        clientRef={clientRef}
        runtimeReady
        languageRevision={2}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId('rendered-revision').textContent).toBe('2');
    }, settle);
    expect(graph).toHaveBeenLastCalledWith(2, 'domain');
  });

  test('does not request a graph before the first synchronization', async () => {
    const graph = vi.fn(async (revision: number) => graphResult(revision));
    render(
      <GraphPanelContainer
        clientRef={clientRefWith(graph)}
        runtimeReady
        languageRevision={null}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId('rendered-revision').textContent).toBe('none');
    }, settle);
    expect(graph).not.toHaveBeenCalled();
  });

  test('reports a failed request instead of rendering nothing', async () => {
    const graph = vi.fn(() => Promise.reject(new Error('worker died')));
    render(
      <GraphPanelContainer
        clientRef={clientRefWith(
          graph as unknown as BrowserCompilerClientLike['graph'],
        )}
        runtimeReady
        languageRevision={1}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId('rendered-error').textContent).toBe(
        'Graph unavailable: worker died',
      );
    }, settle);
  });

  test('stays quiet when the request loses a race with a newer revision', async () => {
    const graph = vi.fn(() =>
      Promise.reject(
        new BrowserCompilerError('STALE_WORKSPACE', 'not current'),
      ),
    );
    render(
      <GraphPanelContainer
        clientRef={clientRefWith(
          graph as unknown as BrowserCompilerClientLike['graph'],
        )}
        runtimeReady
        languageRevision={1}
      />,
    );

    await waitFor(() => {
      expect(graph).toHaveBeenCalled();
    }, settle);
    expect(screen.getByTestId('rendered-error').textContent).toBe('none');
  });
});
