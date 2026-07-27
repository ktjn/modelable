import { vi } from 'vitest';

if (typeof window !== 'undefined') {
  if (!window.CSS) {
    (window as any).CSS = {};
  }
  if (!window.CSS.escape) {
    window.CSS.escape = (v: string) =>
      v.replace(/[\!"#$%&'()*+,\.\/:;<=>?@\[\\\]^`{|}~]/g, '\\$&');
  }

  window.matchMedia ??= (query: string): MediaQueryList => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  } as unknown as MediaQueryList);
}
