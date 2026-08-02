// @vitest-environment jsdom

import { act, cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ToastProvider, useToasts } from './Toast';

afterEach(cleanup);

function PushButton({ variant, message }: { variant: 'error' | 'warning' | 'info'; message: string }) {
  const { push } = useToasts();
  return (
    <button type="button" onClick={() => push(variant, message)}>
      push
    </button>
  );
}

describe('ToastProvider / useToasts', () => {
  it('renders a pushed toast with its variant and message', async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <PushButton variant="error" message="download failed" />
      </ToastProvider>,
    );

    await user.click(screen.getByRole('button', { name: 'push' }));

    const toast = await screen.findByText('download failed');
    expect(toast.closest('.toast')?.className).toContain('toast--error');
  });

  it('dismisses a toast when its close button is clicked', async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <PushButton variant="info" message="fetching models" />
      </ToastProvider>,
    );

    await user.click(screen.getByRole('button', { name: 'push' }));
    await screen.findByText('fetching models');

    await user.click(screen.getByRole('button', { name: /dismiss/i }));

    expect(screen.queryByText('fetching models')).toBeNull();
  });

  it('auto-dismisses a toast after the timeout', async () => {
    vi.useFakeTimers();
    render(
      <ToastProvider>
        <PushButton variant="info" message="auto dismiss me" />
      </ToastProvider>,
    );

    const button = screen.getByRole('button', { name: 'push' });
    await act(async () => {
      button.click();
    });
    expect(screen.getByText('auto dismiss me')).toBeTruthy();

    await act(async () => {
      vi.advanceTimersByTime(6000);
    });
    expect(screen.queryByText('auto dismiss me')).toBeNull();
    vi.useRealTimers();
  });

  it('stacks multiple simultaneous toasts', async () => {
    const user = userEvent.setup();
    function TwoPushButtons() {
      const { push } = useToasts();
      return (
        <>
          <button type="button" onClick={() => push('error', 'first')}>
            push1
          </button>
          <button type="button" onClick={() => push('warning', 'second')}>
            push2
          </button>
        </>
      );
    }
    render(
      <ToastProvider>
        <TwoPushButtons />
      </ToastProvider>,
    );
    await user.click(screen.getByRole('button', { name: 'push1' }));
    await user.click(screen.getByRole('button', { name: 'push2' }));

    expect(screen.getByText('first')).toBeTruthy();
    expect(screen.getByText('second')).toBeTruthy();
  });

  it('throws when useToasts is used outside a ToastProvider', () => {
    function Broken() {
      useToasts();
      return null;
    }
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<Broken />)).toThrow('useToasts must be used within a ToastProvider');
    consoleError.mockRestore();
  });
});
