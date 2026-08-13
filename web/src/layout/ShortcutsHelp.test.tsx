// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { ShortcutsHelp, type ShortcutEntry } from './ShortcutsHelp';

afterEach(() => {
  cleanup();
});

const shortcuts: ShortcutEntry[] = [
  { keys: 'Ctrl/Cmd + K', description: 'Open the command palette' },
  { keys: '?', description: 'Show this keyboard shortcuts panel' },
];

describe('ShortcutsHelp', () => {
  test('renders nothing when closed', () => {
    render(
      <ShortcutsHelp open={false} shortcuts={shortcuts} onClose={vi.fn()} />,
    );
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  test('lists every shortcut and its description when open', () => {
    render(
      <ShortcutsHelp open shortcuts={shortcuts} onClose={vi.fn()} />,
    );

    expect(
      screen.getByRole('dialog', { name: 'Keyboard shortcuts' }),
    ).toBeTruthy();
    expect(screen.getByText('Ctrl/Cmd + K')).toBeTruthy();
    expect(screen.getByText('Open the command palette')).toBeTruthy();
    expect(screen.getByText('?')).toBeTruthy();
    expect(screen.getByText('Show this keyboard shortcuts panel')).toBeTruthy();
  });

  test('focuses the close button on open', () => {
    render(
      <ShortcutsHelp open shortcuts={shortcuts} onClose={vi.fn()} />,
    );
    expect(document.activeElement).toBe(
      screen.getByRole('button', { name: 'Close keyboard shortcuts' }),
    );
  });

  test('closes on Escape, close button click, and backdrop click', () => {
    const onCloseEscape = vi.fn();
    const { unmount } = render(
      <ShortcutsHelp open shortcuts={shortcuts} onClose={onCloseEscape} />,
    );
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onCloseEscape).toHaveBeenCalledTimes(1);
    unmount();

    const onCloseButton = vi.fn();
    const rendered = render(
      <ShortcutsHelp open shortcuts={shortcuts} onClose={onCloseButton} />,
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Close keyboard shortcuts' }),
    );
    expect(onCloseButton).toHaveBeenCalledTimes(1);
    rendered.unmount();

    const onCloseBackdrop = vi.fn();
    render(
      <ShortcutsHelp open shortcuts={shortcuts} onClose={onCloseBackdrop} />,
    );
    fireEvent.mouseDown(screen.getByRole('dialog').parentElement as Element);
    expect(onCloseBackdrop).toHaveBeenCalledTimes(1);
  });
});
