/**
 * @vitest-environment jsdom
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AiPreviewPanel, type AiPreviewState } from './AiPreviewPanel';

afterEach(cleanup);

function renderPanel(
  overrides: Partial<AiPreviewState> = {},
  handlers: { onAccept?: () => void; onDiscard?: () => void } = {},
) {
  const preview: AiPreviewState = {
    kind: 'generate',
    source: 'entity Order {}',
    diagnostics: [],
    providerInfo: { provider: 'heuristic', model: 'heuristic' },
    ...overrides,
  };
  const onAccept = handlers.onAccept ?? vi.fn();
  const onDiscard = handlers.onDiscard ?? vi.fn();
  render(
    <AiPreviewPanel
      preview={preview}
      onAccept={onAccept}
      onDiscard={onDiscard}
    />,
  );
  return { onAccept, onDiscard };
}

describe('AiPreviewPanel', () => {
  it('shows generated source with accept and discard buttons', () => {
    renderPanel({ source: 'entity Invoice {}' });
    expect(screen.getByText('AI generated source')).toBeTruthy();
    expect(screen.getByText('entity Invoice {}')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Accept' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Discard' })).toBeTruthy();
  });

  it('shows explanation with close button', () => {
    renderPanel({ kind: 'explain', explanation: 'This model defines…' });
    expect(screen.getByText('AI explanation')).toBeTruthy();
    expect(screen.getByText('This model defines…')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Accept' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Close' })).toBeTruthy();
  });

  it('displays diagnostics', () => {
    renderPanel({
      diagnostics: [
        {
          code: 'E001',
          severity: 'error',
          message: 'Syntax error',
          uri: '',
          line: null,
          column: null,
          end_line: null,
          end_column: null,
        },
      ],
    });
    expect(screen.getByText('Syntax error')).toBeTruthy();
  });

  it('calls onAccept when accept is clicked', () => {
    const onAccept = vi.fn();
    renderPanel({}, { onAccept });
    fireEvent.click(screen.getByRole('button', { name: 'Accept' }));
    expect(onAccept).toHaveBeenCalledOnce();
  });

  it('calls onDiscard when discard is clicked', () => {
    const onDiscard = vi.fn();
    renderPanel({}, { onDiscard });
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }));
    expect(onDiscard).toHaveBeenCalledOnce();
  });

  it('shows provider info', () => {
    renderPanel({
      providerInfo: { provider: 'webgpu', model: 'Qwen2.5-0.5B' },
    });
    expect(screen.getByText('webgpu / Qwen2.5-0.5B')).toBeTruthy();
  });
});
