// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import indexHtml from '../index.html?raw';
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

  test('provides a focusable target for the skip link', () => {
    const template = document.createElement('template');
    template.innerHTML = indexHtml;
    const skipLink =
      template.content.querySelector<HTMLAnchorElement>('.skip-link');

    render(<App />);

    const href = skipLink?.getAttribute('href');
    expect(href).toBe('#source-editor');
    const target = document.querySelector<HTMLElement>(href ?? '');
    expect(target).toBeTruthy();
    expect(target?.tabIndex).toBe(-1);

    target?.focus();
    expect(document.activeElement).toBe(target);
  });
});
