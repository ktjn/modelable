// @vitest-environment jsdom

import { beforeEach, describe, expect, test, vi } from 'vitest';

import {
  getResolvedTheme,
  getThemePreference,
  initTheme,
  setThemePreference,
  subscribeTheme,
} from './theme';

const query = '(prefers-color-scheme: dark)';

function mockMatchMedia(matches: boolean): void {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((media: string) => ({
      matches,
      media,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

beforeEach(() => {
  localStorage.clear();
  mockMatchMedia(false);
  setThemePreference('system');
});

describe('theme module', () => {
  test('defaults to system and resolves to light when OS is light', () => {
    initTheme();
    expect(getThemePreference()).toBe('system');
    expect(getResolvedTheme()).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
  });

  test('defaults to system and resolves to dark when OS is dark', () => {
    mockMatchMedia(true);
    initTheme();
    expect(getThemePreference()).toBe('system');
    expect(getResolvedTheme()).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  test('setThemePreference persists explicit choices and removes system', () => {
    initTheme();
    setThemePreference('dark');
    expect(getThemePreference()).toBe('dark');
    expect(getResolvedTheme()).toBe('dark');
    expect(localStorage.getItem('modelable:theme')).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');

    setThemePreference('system');
    expect(getThemePreference()).toBe('system');
    expect(localStorage.getItem('modelable:theme')).toBeNull();
  });

  test('subscribers are notified when the resolved theme changes', () => {
    initTheme();
    const listener = vi.fn();
    const unsubscribe = subscribeTheme(listener);

    setThemePreference('dark');
    expect(listener).toHaveBeenCalledTimes(1);

    setThemePreference('dark');
    expect(listener).toHaveBeenCalledTimes(1);

    setThemePreference('light');
    expect(listener).toHaveBeenCalledTimes(2);

    unsubscribe();
    setThemePreference('dark');
    expect(listener).toHaveBeenCalledTimes(2);
  });

  test('ignores corrupt localStorage entries and falls back to system', () => {
    localStorage.setItem('modelable:theme', 'purple');
    initTheme();
    expect(getThemePreference()).toBe('system');
  });

  test('system mode reacts to OS color scheme changes', () => {
    let currentMatches = false;
    const changeHandlers: Array<(event: MediaQueryListEvent) => void> = [];

    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn((media: string) => ({
        get matches() {
          return currentMatches;
        },
        media,
        onchange: null,
        addEventListener: (
          _type: string,
          handler: (event: MediaQueryListEvent) => void,
        ) => {
          changeHandlers.push(handler);
        },
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });

    initTheme();
    expect(changeHandlers.length).toBeGreaterThan(0);
    expect(getResolvedTheme()).toBe('light');

    currentMatches = true;
    for (const handler of changeHandlers) {
      handler({ matches: true, media: query } as unknown as MediaQueryListEvent);
    }
    expect(getResolvedTheme()).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');

    setThemePreference('light');
    currentMatches = false;
    for (const handler of changeHandlers) {
      handler(
        { matches: false, media: query } as unknown as MediaQueryListEvent,
      );
    }
    expect(getResolvedTheme()).toBe('light');
  });
});
