// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { BottomPanel } from './BottomPanel';

afterEach(() => {
  cleanup();
});

describe('BottomPanel', () => {
  test('shows count badges on tabs when non-zero and hides them when zero or absent', () => {
    render(
      <BottomPanel
        diagnostics={<p>diagnostics body</p>}
        compatibility={<p>compatibility body</p>}
        governance={<p>governance body</p>}
        diagnosticsCount={3}
        compatibilityCount={0}
      />,
    );

    const problemsTab = screen.getByRole('tab', { name: /Problems/ });
    expect(problemsTab.textContent).toBe('Problems3');

    const compatibilityTab = screen.getByRole('tab', {
      name: /Compatibility/,
    });
    expect(compatibilityTab.textContent).toBe('Compatibility');

    const governanceTab = screen.getByRole('tab', { name: /Governance/ });
    expect(governanceTab.textContent).toBe('Governance');
  });

  test('switches between tab bodies on click', () => {
    render(
      <BottomPanel
        diagnostics={<p>diagnostics body</p>}
        compatibility={<p>compatibility body</p>}
        governance={<p>governance body</p>}
      />,
    );

    expect(screen.getByText('diagnostics body')).toBeTruthy();
    expect(screen.queryByText('governance body')).toBeNull();

    fireEvent.click(screen.getByRole('tab', { name: /Governance/ }));

    expect(screen.getByText('governance body')).toBeTruthy();
    expect(screen.queryByText('diagnostics body')).toBeNull();
  });
});
