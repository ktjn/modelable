import { useCallback, useEffect, useState } from 'react';

export type ThemePreference = 'system' | 'light' | 'dark';
export type ResolvedTheme = 'light' | 'dark';

const STORAGE_KEY = 'modelable:theme';

let preference: ThemePreference = 'system';
let resolved: ResolvedTheme = 'light';
const listeners = new Set<() => void>();

let mediaQueryRef: MediaQueryList | null = null;
let mediaHandlerRef: ((event: MediaQueryListEvent) => void) | null = null;

function readPreference(): ThemePreference {
  if (typeof localStorage === 'undefined') {
    return 'system';
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === 'light' || raw === 'dark') {
      return raw;
    }
  } catch {
    // Storage may be disabled or throw in some contexts (e.g. sandboxed iframes).
  }
  return 'system';
}

function resolvePreference(pref: ThemePreference): ResolvedTheme {
  if (pref !== 'system') {
    return pref;
  }
  if (
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches
  ) {
    return 'dark';
  }
  return 'light';
}

function applyResolvedTheme(theme: ResolvedTheme): void {
  if (typeof document === 'undefined') {
    return;
  }
  document.documentElement.dataset.theme = theme;
}

function notifyListeners(): void {
  for (const listener of listeners) {
    listener();
  }
}

export function getThemePreference(): ThemePreference {
  return preference;
}

export function getResolvedTheme(): ResolvedTheme {
  return resolved;
}

export function setThemePreference(pref: ThemePreference): void {
  if (pref === preference) {
    return;
  }
  preference = pref;
  if (typeof localStorage !== 'undefined') {
    try {
      if (pref === 'system') {
        localStorage.removeItem(STORAGE_KEY);
      } else {
        localStorage.setItem(STORAGE_KEY, pref);
      }
    } catch {
      // Ignore storage failures.
    }
  }
  const next = resolvePreference(pref);
  if (next !== resolved) {
    resolved = next;
    applyResolvedTheme(resolved);
  }
  notifyListeners();
}

export function subscribeTheme(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function initTheme(): ThemePreference {
  preference = readPreference();
  resolved = resolvePreference(preference);
  applyResolvedTheme(resolved);

  if (typeof window !== 'undefined') {
    if (mediaQueryRef !== null && mediaHandlerRef !== null) {
      if (mediaQueryRef.removeEventListener) {
        mediaQueryRef.removeEventListener('change', mediaHandlerRef);
      } else {
        mediaQueryRef.removeListener(mediaHandlerRef);
      }
    }

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handleChange = (event: MediaQueryListEvent): void => {
      if (preference !== 'system') {
        return;
      }
      const next = event.matches ? 'dark' : 'light';
      if (next !== resolved) {
        resolved = next;
        applyResolvedTheme(resolved);
        notifyListeners();
      }
    };

    if (mediaQuery.addEventListener) {
      mediaQuery.addEventListener('change', handleChange);
    } else {
      // Older Safari fallback.
      mediaQuery.addListener(handleChange);
    }

    mediaQueryRef = mediaQuery;
    mediaHandlerRef = handleChange;
  }

  return preference;
}

export interface UseThemeResult {
  preference: ThemePreference;
  resolvedTheme: ResolvedTheme;
  setPreference: (pref: ThemePreference) => void;
}

function readThemeState(): Omit<UseThemeResult, 'setPreference'> {
  return {
    preference: getThemePreference(),
    resolvedTheme: getResolvedTheme(),
  };
}

export function useTheme(): UseThemeResult {
  const [state, setState] = useState(readThemeState);

  useEffect(() => {
    setState(readThemeState());
    return subscribeTheme(() => {
      setState(readThemeState());
    });
  }, []);

  const setPreference = useCallback((pref: ThemePreference): void => {
    setThemePreference(pref);
  }, []);

  return { ...state, setPreference };
}
