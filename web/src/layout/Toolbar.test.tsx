// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { Toolbar, type ToolbarProps } from './Toolbar';

afterEach(() => {
  cleanup();
});

function props(overrides: Partial<ToolbarProps> = {}): ToolbarProps {
  return {
    runtime: 'ready',
    compileTarget: 'jsonSchema',
    actionsDisabled: false,
    languageCanRetry: false,
    persistencePhase: 'saved',
    overlayFileName: null,
    overlayError: null,
    onExportSource: vi.fn(),
    onResetToDemo: vi.fn(),
    onValidate: vi.fn(),
    onFormat: vi.fn(),
    onGenerate: vi.fn(),
    onRetryCompiler: vi.fn(),
    onRetryLanguageServices: vi.fn(),
    onRetryStorage: vi.fn(),
    onCompileTargetChange: vi.fn(),
    onOverlayFileSelected: vi.fn(),
    onOverlayCleared: vi.fn(),
    ...overrides,
  };
}

describe('Toolbar overlay control', () => {
  test('hides the overlay control for targets without a real overlay schema', () => {
    render(<Toolbar {...props({ compileTarget: 'jsonSchema' })} />);

    expect(screen.queryByLabelText('Overlay file')).toBeNull();
  });

  test('shows the overlay control for sql-postgres and sql-clickhouse targets', () => {
    render(<Toolbar {...props({ compileTarget: 'sql-postgres' })} />);
    expect(screen.getByLabelText('Overlay file')).toBeTruthy();

    cleanup();

    render(<Toolbar {...props({ compileTarget: 'sql-clickhouse' })} />);
    expect(screen.getByLabelText('Overlay file')).toBeTruthy();
  });

  test('selecting a file calls onOverlayFileSelected', () => {
    const onOverlayFileSelected = vi.fn();
    render(<Toolbar {...props({ compileTarget: 'sql-postgres', onOverlayFileSelected })} />);

    const file = new File(['target = "sql-postgres"'], 'postgres.toml', { type: 'application/toml' });
    fireEvent.change(screen.getByLabelText('Overlay file'), { target: { files: [file] } });

    expect(onOverlayFileSelected).toHaveBeenCalledWith(file);
  });

  test('shows the selected overlay file name and a clear button', () => {
    const onOverlayCleared = vi.fn();
    render(
      <Toolbar
        {...props({ compileTarget: 'sql-postgres', overlayFileName: 'postgres.toml', onOverlayCleared })}
      />,
    );

    expect(screen.getByText('postgres.toml')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Clear overlay' }));
    expect(onOverlayCleared).toHaveBeenCalled();
  });

  test('shows an overlay error message when present', () => {
    render(
      <Toolbar {...props({ compileTarget: 'sql-postgres', overlayError: 'cannot parse overlay: boom' })} />,
    );

    expect(screen.getByRole('alert').textContent).toBe('cannot parse overlay: boom');
  });
});
