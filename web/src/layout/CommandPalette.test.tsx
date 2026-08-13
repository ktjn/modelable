// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { CommandPalette, type CommandPaletteCommand } from './CommandPalette';

afterEach(() => {
  cleanup();
});

function makeCommands(onRun: (id: string) => void): CommandPaletteCommand[] {
  return [
    { id: 'validate', group: 'Actions', label: 'Validate', onRun: () => onRun('validate') },
    { id: 'format', group: 'Actions', label: 'Format', onRun: () => onRun('format') },
    { id: 'panel-graph', group: 'Panels', label: 'Inspect: Graph', onRun: () => onRun('panel-graph') },
  ];
}

describe('CommandPalette', () => {
  test('renders nothing when closed', () => {
    const onRun = vi.fn();
    render(
      <CommandPalette
        open={false}
        commands={makeCommands(onRun)}
        onClose={vi.fn()}
      />,
    );
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  test('lists all commands and filters as the query narrows', () => {
    const onRun = vi.fn();
    render(
      <CommandPalette
        open
        commands={makeCommands(onRun)}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getAllByRole('option')).toHaveLength(3);

    fireEvent.change(screen.getByRole('combobox'), {
      target: { value: 'graph' },
    });

    const options = screen.getAllByRole('option');
    expect(options).toHaveLength(1);
    expect(options[0]?.textContent).toContain('Inspect: Graph');
  });

  test('shows an empty state when nothing matches', () => {
    render(
      <CommandPalette
        open
        commands={makeCommands(vi.fn())}
        onClose={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByRole('combobox'), {
      target: { value: 'nothing matches this' },
    });
    expect(screen.getByText('No matching commands')).toBeTruthy();
    expect(screen.queryAllByRole('option')).toHaveLength(0);
  });

  test('runs the highlighted command on Enter and closes the palette', () => {
    const onRun = vi.fn();
    const onClose = vi.fn();
    render(
      <CommandPalette
        open
        commands={makeCommands(onRun)}
        onClose={onClose}
      />,
    );

    const input = screen.getByRole('combobox');
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(onRun).toHaveBeenCalledWith('format');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test('runs a command on click and closes the palette', () => {
    const onRun = vi.fn();
    const onClose = vi.fn();
    render(
      <CommandPalette
        open
        commands={makeCommands(onRun)}
        onClose={onClose}
      />,
    );

    fireEvent.click(screen.getByText('Inspect: Graph'));

    expect(onRun).toHaveBeenCalledWith('panel-graph');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test('closes on Escape without running a command', () => {
    const onRun = vi.fn();
    const onClose = vi.fn();
    render(
      <CommandPalette
        open
        commands={makeCommands(onRun)}
        onClose={onClose}
      />,
    );

    fireEvent.keyDown(screen.getByRole('combobox'), { key: 'Escape' });

    expect(onRun).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test('closes when the backdrop is clicked', () => {
    const onClose = vi.fn();
    render(
      <CommandPalette
        open
        commands={makeCommands(vi.fn())}
        onClose={onClose}
      />,
    );

    fireEvent.mouseDown(screen.getByRole('dialog').parentElement as Element);

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
