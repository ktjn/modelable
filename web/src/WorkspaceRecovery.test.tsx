// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { WorkspaceRecovery } from './WorkspaceRecovery';

afterEach(cleanup);

test('explains recovery without exposing raw source and offers every action', () => {
  const handlers = {
    onExport: vi.fn(),
    onReset: vi.fn(),
    onRetry: vi.fn(),
  };
  render(<WorkspaceRecovery reason="incompatible" {...handlers} />);

  expect(screen.getByText('Stored workspace needs recovery')).toBeTruthy();
  expect(document.body.textContent).not.toContain('<script>');
  fireEvent.click(
    screen.getByRole('button', { name: 'Export recovery data' }),
  );
  fireEvent.click(
    screen.getByRole('button', { name: 'Reset local workspace' }),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Retry storage' }));
  expect(handlers.onExport).toHaveBeenCalledOnce();
  expect(handlers.onReset).toHaveBeenCalledOnce();
  expect(handlers.onRetry).toHaveBeenCalledOnce();
});
