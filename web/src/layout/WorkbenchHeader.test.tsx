// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { WorkbenchHeader } from './WorkbenchHeader';

afterEach(() => {
  cleanup();
});

describe('WorkbenchHeader', () => {
  test('cycles theme preference when the theme button is clicked', () => {
    const onChange = vi.fn();
    render(
      <WorkbenchHeader
        status="Ready"
        diagnosticLabel="0 diagnostics"
        statusIsError={false}
        persistencePhase="saved"
        languageStatus="Language services ready"
        themePreference="system"
        resolvedTheme="light"
        onThemePreferenceChange={onChange}
      />,
    );

    const button = screen.getByRole('button', { name: /theme/i });
    expect(button.textContent).toBe('Light');

    fireEvent.click(button);
    expect(onChange).toHaveBeenCalledWith('light');

    cleanup();
    render(
      <WorkbenchHeader
        status="Ready"
        diagnosticLabel="0 diagnostics"
        statusIsError={false}
        persistencePhase="saved"
        languageStatus="Language services ready"
        themePreference="light"
        resolvedTheme="light"
        onThemePreferenceChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /theme/i }));
    expect(onChange).toHaveBeenCalledWith('dark');

    cleanup();
    render(
      <WorkbenchHeader
        status="Ready"
        diagnosticLabel="0 diagnostics"
        statusIsError={false}
        persistencePhase="saved"
        languageStatus="Language services ready"
        themePreference="dark"
        resolvedTheme="dark"
        onThemePreferenceChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /theme/i }));
    expect(onChange).toHaveBeenCalledWith('system');
  });

  test('shows a working indicator only while an operation is in progress', () => {
    const { rerender } = render(
      <WorkbenchHeader
        status="Validation in progress…"
        diagnosticLabel="0 diagnostics"
        statusIsError={false}
        isWorking
        persistencePhase="saved"
        languageStatus="Language services ready"
        themePreference="system"
        resolvedTheme="light"
        onThemePreferenceChange={vi.fn()}
      />,
    );

    expect(
      screen.getByRole('status').querySelector('.workbench-header__pulse'),
    ).toBeTruthy();

    rerender(
      <WorkbenchHeader
        status="Compiler ready"
        diagnosticLabel="0 diagnostics"
        statusIsError={false}
        isWorking={false}
        persistencePhase="saved"
        languageStatus="Language services ready"
        themePreference="system"
        resolvedTheme="light"
        onThemePreferenceChange={vi.fn()}
      />,
    );

    expect(
      screen.getByRole('status').querySelector('.workbench-header__pulse'),
    ).toBeNull();
  });

  test('flags memory-only and recovery-required persistence as a warning', () => {
    const { rerender } = render(
      <WorkbenchHeader
        status="Compiler ready"
        diagnosticLabel="0 diagnostics"
        statusIsError={false}
        persistencePhase="saved"
        languageStatus="Language services ready"
        themePreference="system"
        resolvedTheme="light"
        onThemePreferenceChange={vi.fn()}
      />,
    );
    expect(screen.getByText('Saved locally').className).not.toMatch(
      /badge--warning/,
    );

    rerender(
      <WorkbenchHeader
        status="Compiler ready"
        diagnosticLabel="0 diagnostics"
        statusIsError={false}
        persistencePhase="memory-only"
        languageStatus="Language services ready"
        themePreference="system"
        resolvedTheme="light"
        onThemePreferenceChange={vi.fn()}
      />,
    );
    expect(screen.getByText('Memory-only').className).toMatch(
      /badge--warning/,
    );

    rerender(
      <WorkbenchHeader
        status="Compiler ready"
        diagnosticLabel="0 diagnostics"
        statusIsError={false}
        persistencePhase="recovery-required"
        languageStatus="Language services ready"
        themePreference="system"
        resolvedTheme="light"
        onThemePreferenceChange={vi.fn()}
      />,
    );
    expect(screen.getByText('Recovery needed').className).toMatch(
      /badge--warning/,
    );
  });
});
