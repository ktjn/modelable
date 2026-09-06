// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createRef, type RefObject } from 'react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import type { BrowserCompilerClientLike } from '../client';
import type { BrowserQueryResult } from '../protocol';
import { QueryPanel } from './QueryPanel';

afterEach(() => {
  cleanup();
});

function renderPanel(query: BrowserCompilerClientLike['query']) {
  const clientRef = createRef<BrowserCompilerClientLike | null>();
  (clientRef as { current: BrowserCompilerClientLike }).current = { query } as BrowserCompilerClientLike;
  const workspaceRevisionRef: RefObject<number> = { current: 7 };

  render(
    <QueryPanel clientRef={clientRef} runtimeReady={true} workspaceRevisionRef={workspaceRevisionRef} />,
  );
  return { clientRef, workspaceRevisionRef };
}

describe('QueryPanel', () => {
  test('sends an id-based request for a reference query family and renders the result', async () => {
    const result: BrowserQueryResult = {
      $schema: 'modelable.query/v1',
      kind: 'query_result',
      query: 'declaration',
      data: { identity: 'customer.Customer@1' },
    };
    const query = vi.fn().mockResolvedValue(result);

    renderPanel(query);

    fireEvent.change(screen.getByLabelText('Id'), {
      target: { value: 'customer.Customer@1' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Run query/ }));

    await waitFor(() => {
      expect(query).toHaveBeenCalledWith(7, {
        $schema: 'modelable.query/v1',
        kind: 'query',
        query: 'declaration',
        id: 'customer.Customer@1',
      });
    });
    const resultElement = await screen.findByTestId('query-panel-result');
    expect(resultElement.textContent).toContain('"identity": "customer.Customer@1"');
  });

  test('switches to from/to inputs for a comparison query family', () => {
    const query = vi.fn();
    renderPanel(query);

    fireEvent.change(screen.getByLabelText('Query'), { target: { value: 'changes' } });

    expect(screen.getByLabelText('From')).toBeTruthy();
    expect(screen.getByLabelText('To')).toBeTruthy();
    expect(screen.queryByLabelText('Id')).toBeNull();

    fireEvent.change(screen.getByLabelText('From'), { target: { value: 'a.A@1' } });
    fireEvent.change(screen.getByLabelText('To'), { target: { value: 'a.A@2' } });
    fireEvent.click(screen.getByRole('button', { name: /Run query/ }));

    expect(query).toHaveBeenCalledWith(7, {
      $schema: 'modelable.query/v1',
      kind: 'query',
      query: 'changes',
      from: 'a.A@1',
      to: 'a.A@2',
    });
  });

  test('shows an error message when the query rejects', async () => {
    const query = vi.fn().mockRejectedValue(new Error('boom'));
    renderPanel(query);

    fireEvent.change(screen.getByLabelText('Id'), { target: { value: 'a.A@1' } });
    fireEvent.click(screen.getByRole('button', { name: /Run query/ }));

    expect((await screen.findByRole('alert')).textContent).toMatch(/boom/);
  });

  test('disables the run button until an id is entered', () => {
    const query = vi.fn();
    renderPanel(query);

    expect((screen.getByRole('button', { name: /Run query/ }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(screen.getByLabelText('Id'), { target: { value: 'a.A@1' } });

    expect((screen.getByRole('button', { name: /Run query/ }) as HTMLButtonElement).disabled).toBe(false);
  });
});
