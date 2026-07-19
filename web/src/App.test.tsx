// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { App } from './App';

afterEach(cleanup);

describe('App', () => {
  test('renders an editor workbench before the compiler is ready', () => {
    render(<App />);

    expect(
      screen.getByRole('heading', { name: 'Modelable playground' }),
    ).toBeTruthy();
    expect(
      (screen.getByRole('button', { name: 'Validate' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      (screen.getByRole('button', { name: 'Format' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      (screen.getByRole('button', { name: 'Generate' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(screen.getByRole('status').textContent).toMatch(
      /initializing compiler/i,
    );
  });
});
