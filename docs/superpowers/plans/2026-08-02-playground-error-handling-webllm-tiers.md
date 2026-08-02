# Playground Error Handling & WebLLM Tiered Recommendations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tighten error handling in the web playground (`web/src`) with a shared error-normalization helper, a typed `AiProviderError`, a toast notification system, and a React error boundary; replace WebLLM's single "best fit" model suggestion with fast/balanced/quality tier recommendations while keeping every fetched model in the selector.

**Architecture:** Two small app-wide UI primitives (`errors.ts` helper, `Toast.tsx`, `ErrorBoundary.tsx`) live at `web/src/` top level; the AI-specific typed error and tiering logic live in `web/src/ai/`. `App.tsx` wires the toast provider and applies the helper/typed-error at existing catch sites without changing the reducer/status-chip behavior that's already there.

**Tech Stack:** React 19, TypeScript, Vitest, @testing-library/react, existing `web/src/ai` WebGPU/WebLLM provider code.

## Global Constraints

- Scope is `web/src` only; do not touch `cli/` (Python).
- `AiProviderError` codes: `'WEBGPU_UNSUPPORTED' | 'MODEL_LIST_FAILED' | 'INITIALIZATION_FAILED' | 'COMPLETION_FAILED' | 'FETCH_MODELS_FAILED' | 'PROVIDER_DISPOSED'`.
- Toasts are additive to the existing status chip / inline diagnostics — do not remove or replace those.
- `suggestModels` picks tiers purely from VRAM-fit position within the dynamically fetched model list; no model IDs are hardcoded.
- `ModelOption.recommended?: boolean` is renamed to `recommendedTier?: 'fast' | 'balanced' | 'quality'` everywhere it's referenced (`webgpu-provider.ts`, `App.tsx`, `ChatPanel.tsx`) — no leftover references to the old field.
- Run `npm run check` (tsc) and `npm test` (vitest run) from `web/` after each task that touches TypeScript.
- Tasks are ordered so each task's dependencies are fully satisfied by the tasks before it — do not skip ahead or reorder.

---

### Task 1: Shared error-normalization helper

**Files:**
- Create: `web/src/errors.ts`
- Test: `web/src/errors.test.ts`

**Interfaces:**
- Produces: `toErrorMessage(error: unknown, fallback: string): string`

- [ ] **Step 1: Write the failing test**

```typescript
// web/src/errors.test.ts
import { describe, expect, it } from 'vitest';

import { toErrorMessage } from './errors';

describe('toErrorMessage', () => {
  it('returns the message from an Error instance', () => {
    expect(toErrorMessage(new Error('boom'), 'fallback')).toBe('boom');
  });

  it('returns the fallback for a non-Error value', () => {
    expect(toErrorMessage('a string was thrown', 'fallback')).toBe('fallback');
  });

  it('returns the fallback for undefined', () => {
    expect(toErrorMessage(undefined, 'fallback')).toBe('fallback');
  });

  it('returns the fallback for a plain object', () => {
    expect(toErrorMessage({ reason: 'nope' }, 'fallback')).toBe('fallback');
  });

  it('returns an Error subclass message unchanged', () => {
    class CustomError extends Error {}
    expect(toErrorMessage(new CustomError('custom failure'), 'fallback')).toBe(
      'custom failure',
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `web/`): `npx vitest run src/errors.test.ts`
Expected: FAIL with "Cannot find module './errors'" or similar.

- [ ] **Step 3: Write minimal implementation**

```typescript
// web/src/errors.ts
export function toErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/errors.test.ts`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add web/src/errors.ts web/src/errors.test.ts
git commit -m "feat(web): add shared error-normalization helper"
```

---

### Task 2: Typed `AiProviderError` and worker error codes

**Files:**
- Modify: `web/src/ai/webgpu-provider.ts` (add `AiProviderError` class near the top, after `ModelOption`)
- Modify: `web/src/ai/ai.worker.ts:9-14` (`AiWorkerResponse` error variant gains optional `code`), and each `catch` block that posts `{type:'error', ...}` (lines ~58-64 `handleInitialize`, ~93-99 `handleComplete`, ~144-150 `handleListModels`)
- Modify: `web/src/ai/webgpu-provider.ts` (`getWebLlmModels`, `initialize`, `complete` — wrap rejections in `AiProviderError`)
- Test: `web/src/ai/webgpu-provider.test.ts` (extend existing `describe('WebGpuProvider', ...)`)

**Interfaces:**
- Consumes: `toErrorMessage` from `../errors` (Task 1).
- Produces: `export class AiProviderError extends Error { constructor(readonly code: AiProviderErrorCode, message: string) }`, `export type AiProviderErrorCode = 'WEBGPU_UNSUPPORTED' | 'MODEL_LIST_FAILED' | 'INITIALIZATION_FAILED' | 'COMPLETION_FAILED' | 'FETCH_MODELS_FAILED' | 'PROVIDER_DISPOSED'`. `AiWorkerResponse`'s error variant becomes `{ type: 'error'; id?: string; message: string; code?: AiProviderErrorCode }`.

- [ ] **Step 1: Write the failing tests**

Add to `web/src/ai/webgpu-provider.test.ts` (inside the existing `describe('WebGpuProvider', ...)` block, after the `'initialize rejects on error'` test):

```typescript
  it('initialize rejects with AiProviderError using worker code when provided', async () => {
    const provider = new WebGpuProvider();
    const initPromise = provider.initialize();

    firstHandler(mockWorker, 'message')({
      data: { type: 'error', message: 'Model too large', code: 'INITIALIZATION_FAILED' },
    });

    await expect(initPromise).rejects.toMatchObject({
      name: 'AiProviderError',
      code: 'INITIALIZATION_FAILED',
      message: 'Model too large',
    });
  });

  it('initialize rejects with AiProviderError defaulting to INITIALIZATION_FAILED when worker omits code', async () => {
    const provider = new WebGpuProvider();
    const initPromise = provider.initialize();

    firstHandler(mockWorker, 'message')({
      data: { type: 'error', message: 'WebGPU not supported' },
    });

    await expect(initPromise).rejects.toMatchObject({
      name: 'AiProviderError',
      code: 'INITIALIZATION_FAILED',
    });
  });

  it('initialize throws AiProviderError with WEBGPU_UNSUPPORTED when WebGPU is not available', async () => {
    Object.defineProperty(globalThis, 'navigator', {
      value: {},
      configurable: true,
    });
    const provider = new WebGpuProvider();
    await expect(provider.initialize()).rejects.toMatchObject({
      name: 'AiProviderError',
      code: 'WEBGPU_UNSUPPORTED',
    });
  });

  it('getWebLlmModels rejects with AiProviderError coded MODEL_LIST_FAILED', async () => {
    const promise = WebGpuProvider.getWebLlmModels();
    firstHandler(mockWorker, 'message')({
      data: { type: 'error', message: 'fetch failed' },
    });
    await expect(promise).rejects.toMatchObject({
      name: 'AiProviderError',
      code: 'MODEL_LIST_FAILED',
      message: 'fetch failed',
    });
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/ai/webgpu-provider.test.ts`
Expected: FAIL — `AiProviderError` doesn't exist / rejections are plain `Error`, not matching `code`.

- [ ] **Step 3: Implement `AiProviderError` and wire it through**

In `web/src/ai/webgpu-provider.ts`, add after the `ModelOption` interface (before `DEFAULT_MODELS`):

```typescript
export type AiProviderErrorCode =
  | 'WEBGPU_UNSUPPORTED'
  | 'MODEL_LIST_FAILED'
  | 'INITIALIZATION_FAILED'
  | 'COMPLETION_FAILED'
  | 'FETCH_MODELS_FAILED'
  | 'PROVIDER_DISPOSED';

export class AiProviderError extends Error {
  constructor(
    readonly code: AiProviderErrorCode,
    message: string,
  ) {
    super(message);
    this.name = 'AiProviderError';
  }
}
```

Update `getWebLlmModels` (replace the `reject(new Error(msg.message))` line):

```typescript
        } else if (msg.type === 'error') {
          worker.removeEventListener('message', handler);
          worker.terminate();
          reject(new AiProviderError(msg.code ?? 'MODEL_LIST_FAILED', msg.message));
        }
```

Update `initialize`'s `detectWebGpu()` guard:

```typescript
    if (!detectWebGpu()) {
      throw new AiProviderError(
        'WEBGPU_UNSUPPORTED',
        'WebGPU is not available in this browser',
      );
    }
```

Update `initialize`'s promise error branch:

```typescript
        } else if (msg.type === 'error') {
          worker.removeEventListener('message', handler);
          reject(new AiProviderError(msg.code ?? 'INITIALIZATION_FAILED', msg.message));
        }
```

Update `handleWorkerMessage`'s `complete` error branch:

```typescript
    } else if (msg.type === 'error' && msg.id !== undefined) {
      const pending = this.pendingCompletions.get(msg.id);
      if (pending !== undefined) {
        this.pendingCompletions.delete(msg.id);
        pending.reject(new AiProviderError(msg.code ?? 'COMPLETION_FAILED', msg.message));
      }
    }
```

Update `dispose()`'s pending-completion rejection loop, so it uses the declared `PROVIDER_DISPOSED` code too:

```typescript
    for (const [, pending] of this.pendingCompletions) {
      pending.reject(new AiProviderError('PROVIDER_DISPOSED', 'Provider disposed'));
    }
```

This does not change the `dispose terminates worker and rejects pending completions` test, since it only asserts `.rejects.toThrow('Provider disposed')`, which matches on message regardless of error class.

In `web/src/ai/ai.worker.ts`, change the `AiWorkerResponse` error variant type (line 14):

```typescript
  | { type: 'error'; id?: string; message: string; code?: import('./webgpu-provider').AiProviderErrorCode };
```

Update the three catch blocks to pass a code and use `toErrorMessage`. In `handleInitialize`:

```typescript
  } catch (error: unknown) {
    const response: AiWorkerResponse = {
      type: 'error',
      message: toErrorMessage(error, 'Failed to initialize model'),
      code: 'INITIALIZATION_FAILED',
    };
    ctx.postMessage(response);
  }
```

In `handleComplete`:

```typescript
  } catch (error: unknown) {
    const response: AiWorkerResponse = {
      type: 'error',
      id,
      message: toErrorMessage(error, 'Completion failed'),
      code: 'COMPLETION_FAILED',
    };
    ctx.postMessage(response);
  }
```

In `handleListModels`:

```typescript
  } catch (error: unknown) {
    const response: AiWorkerResponse = {
      type: 'error',
      message: toErrorMessage(error, 'Failed to list models'),
      code: 'MODEL_LIST_FAILED',
    };
    ctx.postMessage(response);
  }
```

Add the import at the top of `ai.worker.ts`:

```typescript
import { toErrorMessage } from '../errors';
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/ai/webgpu-provider.test.ts`
Expected: PASS (all prior tests plus the 4 new ones)

Run: `npx tsc --noEmit` (from `web/`)
Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add web/src/ai/webgpu-provider.ts web/src/ai/ai.worker.ts web/src/ai/webgpu-provider.test.ts
git commit -m "feat(web): add typed AiProviderError with worker error codes"
```

---

### Task 3: Toast notification system

**Files:**
- Create: `web/src/Toast.tsx`
- Test: `web/src/Toast.test.tsx`
- Modify: `web/src/style.css` (append toast styles near the end of the file)

**Interfaces:**
- Produces: `export function ToastProvider({ children }: { children: React.ReactNode }): JSX.Element`, `export function useToasts(): { push(variant: 'error' | 'warning' | 'info', message: string): void }`, `export type ToastVariant = 'error' | 'warning' | 'info'`.

- [ ] **Step 1: Write the failing test**

```typescript
// web/src/Toast.test.tsx
// @vitest-environment jsdom

import { act, cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ToastProvider, useToasts } from './Toast';

afterEach(cleanup);

function PushButton({ variant, message }: { variant: 'error' | 'warning' | 'info'; message: string }) {
  const { push } = useToasts();
  return (
    <button type="button" onClick={() => push(variant, message)}>
      push
    </button>
  );
}

describe('ToastProvider / useToasts', () => {
  it('renders a pushed toast with its variant and message', async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <PushButton variant="error" message="download failed" />
      </ToastProvider>,
    );

    await user.click(screen.getByRole('button', { name: 'push' }));

    const toast = await screen.findByText('download failed');
    expect(toast.closest('.toast')?.className).toContain('toast--error');
  });

  it('dismisses a toast when its close button is clicked', async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <PushButton variant="info" message="fetching models" />
      </ToastProvider>,
    );

    await user.click(screen.getByRole('button', { name: 'push' }));
    await screen.findByText('fetching models');

    await user.click(screen.getByRole('button', { name: /dismiss/i }));

    expect(screen.queryByText('fetching models')).toBeNull();
  });

  it('auto-dismisses a toast after the timeout', async () => {
    vi.useFakeTimers();
    render(
      <ToastProvider>
        <PushButton variant="info" message="auto dismiss me" />
      </ToastProvider>,
    );

    const button = screen.getByRole('button', { name: 'push' });
    await act(async () => {
      button.click();
    });
    expect(screen.getByText('auto dismiss me')).toBeTruthy();

    await act(async () => {
      vi.advanceTimersByTime(6000);
    });
    expect(screen.queryByText('auto dismiss me')).toBeNull();
    vi.useRealTimers();
  });

  it('stacks multiple simultaneous toasts', async () => {
    const user = userEvent.setup();
    function TwoPushButtons() {
      const { push } = useToasts();
      return (
        <>
          <button type="button" onClick={() => push('error', 'first')}>
            push1
          </button>
          <button type="button" onClick={() => push('warning', 'second')}>
            push2
          </button>
        </>
      );
    }
    render(
      <ToastProvider>
        <TwoPushButtons />
      </ToastProvider>,
    );
    await user.click(screen.getByRole('button', { name: 'push1' }));
    await user.click(screen.getByRole('button', { name: 'push2' }));

    expect(screen.getByText('first')).toBeTruthy();
    expect(screen.getByText('second')).toBeTruthy();
  });

  it('throws when useToasts is used outside a ToastProvider', () => {
    function Broken() {
      useToasts();
      return null;
    }
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<Broken />)).toThrow('useToasts must be used within a ToastProvider');
    consoleError.mockRestore();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/Toast.test.tsx`
Expected: FAIL with "Cannot find module './Toast'"

- [ ] **Step 3: Write the implementation**

```tsx
// web/src/Toast.tsx
import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from 'react';

export type ToastVariant = 'error' | 'warning' | 'info';

interface ToastEntry {
  id: number;
  variant: ToastVariant;
  message: string;
}

interface ToastContextValue {
  push(variant: ToastVariant, message: string): void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const AUTO_DISMISS_MS = 5000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastEntry[]>([]);
  const nextId = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback(
    (variant: ToastVariant, message: string) => {
      const id = nextId.current++;
      setToasts((current) => [...current, { id, variant, message }]);
      setTimeout(() => dismiss(id), AUTO_DISMISS_MS);
    },
    [dismiss],
  );

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="toast-container" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast toast--${toast.variant}`} role="status">
            <span className="toast__message">{toast.message}</span>
            <button
              type="button"
              className="toast__dismiss"
              aria-label="Dismiss notification"
              onClick={() => dismiss(toast.id)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToasts(): ToastContextValue {
  const value = useContext(ToastContext);
  if (value === null) {
    throw new Error('useToasts must be used within a ToastProvider');
  }
  return value;
}
```

Append to `web/src/style.css`:

```css
.toast-container {
  position: fixed;
  bottom: 1rem;
  right: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  z-index: 1000;
  max-width: 24rem;
}

.toast {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.55rem 0.7rem;
  border-radius: 0.4rem;
  border: 1px solid var(--border);
  background: var(--panel);
  box-shadow: 0 2px 8px rgb(0 0 0 / 0.2);
  font-size: 0.82rem;
}

.toast--error {
  color: var(--text-error);
  background: var(--danger-bg);
  border-color: var(--text-error);
}

.toast--warning {
  color: var(--accent);
}

.toast--info {
  color: var(--text-muted);
}

.toast__message {
  flex: 1;
}

.toast__dismiss {
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
  font-size: 1rem;
  line-height: 1;
  padding: 0 0.2rem;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/Toast.test.tsx`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add web/src/Toast.tsx web/src/Toast.test.tsx web/src/style.css
git commit -m "feat(web): add toast notification system"
```

---

### Task 4: React error boundary, wired into `main.tsx`

**Files:**
- Create: `web/src/ErrorBoundary.tsx`
- Test: `web/src/ErrorBoundary.test.tsx`
- Modify: `web/src/main.tsx`
- Modify: `web/src/style.css` (append error-boundary styles)

**Interfaces:**
- Produces: `export class ErrorBoundary extends React.Component<{ children: ReactNode }, { error: Error | null }>`

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/ErrorBoundary.test.tsx
// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ErrorBoundary } from './ErrorBoundary';

afterEach(cleanup);

function Bomb(): never {
  throw new Error('kaboom');
}

describe('ErrorBoundary', () => {
  it('renders children when there is no error', () => {
    render(
      <ErrorBoundary>
        <p>all good</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText('all good')).toBeTruthy();
  });

  it('renders a fallback UI when a child throws', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/something went wrong/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: /reload/i })).toBeTruthy();
    consoleError.mockRestore();
  });

  it('does not render the thrown error message directly in the fallback', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.queryByText('kaboom')).toBeNull();
    consoleError.mockRestore();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/ErrorBoundary.test.tsx`
Expected: FAIL with "Cannot find module './ErrorBoundary'"

- [ ] **Step 3: Write the implementation**

```tsx
// web/src/ErrorBoundary.tsx
import { Component, type ReactNode } from 'react';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: { componentStack: string }): void {
    console.error('Playground crashed:', error, info.componentStack);
  }

  private handleReload = (): void => {
    window.location.reload();
  };

  render(): ReactNode {
    if (this.state.error !== null) {
      return (
        <div className="error-boundary" role="alert">
          <h1>Something went wrong</h1>
          <p>The playground hit an unexpected error and needs to reload.</p>
          <button type="button" onClick={this.handleReload}>
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
```

Append to `web/src/style.css`:

```css
.error-boundary {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  height: 100vh;
  padding: 2rem;
  text-align: center;
  color: var(--text);
  background: var(--bg);
}

.error-boundary p {
  color: var(--text-muted);
  max-width: 28rem;
}
```

Modify `web/src/main.tsx` to wrap `<App />`:

```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './App';
import { ErrorBoundary } from './ErrorBoundary';
import './editor/monaco-environment';
import { registerServiceWorker } from './sw-registration';
import './style.css';
import { initTheme } from './theme';

initTheme();

const root = document.getElementById('root');
if (root === null) {
  throw new Error('Missing React root');
}

createRoot(root).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);

registerServiceWorker();
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/ErrorBoundary.test.tsx`
Expected: PASS (3 tests)

Run: `npx tsc --noEmit`
Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add web/src/ErrorBoundary.tsx web/src/ErrorBoundary.test.tsx web/src/main.tsx web/src/style.css
git commit -m "feat(web): add ErrorBoundary around the app root"
```

---

### Task 5: `suggestModels` tiering (fast/balanced/quality)

**Files:**
- Modify: `web/src/ai/webgpu-provider.ts` (replace `suggestModel` with `suggestModels`; update `ModelOption.recommended` → `recommendedTier`)
- Test: `web/src/ai/webgpu-provider.test.ts` (new `describe('suggestModels', ...)` block)

**Interfaces:**
- Produces: `export function suggestModels(models: ModelOption[], limits: GPUSupportedLimits | null): { fast?: string; balanced?: string; quality?: string }` (also exported as `export interface SuggestedModelTiers`). `ModelOption.recommended?: boolean` is removed; `ModelOption.recommendedTier?: 'fast' | 'balanced' | 'quality'` is added in its place.

- [ ] **Step 1: Write the failing tests**

Add to `web/src/ai/webgpu-provider.test.ts`:

```typescript
import { suggestModels, type ModelOption } from './webgpu-provider';

function model(id: string, vramMb: number): ModelOption {
  return { id, label: id, description: '', vramMb };
}

describe('suggestModels', () => {
  it('returns only fast fallback id when limits are null', () => {
    const models = [model('a', 500), model('b', 2000)];
    expect(suggestModels(models, null)).toEqual({
      fast: 'Qwen2.5-0.5B-Instruct-q4f16_1-MLC',
    });
  });

  it('returns empty object when no models fit', () => {
    const models = [model('a', 999999)];
    const limits = { maxStorageBufferBindingSize: 1 } as GPUSupportedLimits;
    expect(suggestModels(models, limits)).toEqual({});
  });

  it('assigns the single fitting model to fast only', () => {
    const models = [model('a', 500)];
    const limits = {
      maxStorageBufferBindingSize: 500 * 1024 * 1024,
    } as GPUSupportedLimits;
    expect(suggestModels(models, limits)).toEqual({ fast: 'a' });
  });

  it('assigns two fitting models to fast and quality', () => {
    const models = [model('small', 500), model('large', 2000)];
    const limits = {
      maxStorageBufferBindingSize: 2000 * 1024 * 1024,
    } as GPUSupportedLimits;
    expect(suggestModels(models, limits)).toEqual({
      fast: 'small',
      quality: 'large',
    });
  });

  it('assigns three or more fitting models to fast, balanced, and quality by VRAM position', () => {
    const models = [
      model('tiny', 500),
      model('mid', 2000),
      model('big', 8000),
    ];
    const limits = {
      maxStorageBufferBindingSize: 8000 * 1024 * 1024,
    } as GPUSupportedLimits;
    expect(suggestModels(models, limits)).toEqual({
      fast: 'tiny',
      balanced: 'mid',
      quality: 'big',
    });
  });

  it('picks the fitting model closest to the VRAM midpoint as balanced among many candidates', () => {
    const models = [
      model('tiny', 500),
      model('close-to-mid', 4200),
      model('far-from-mid', 6000),
      model('big', 8000),
    ];
    const limits = {
      maxStorageBufferBindingSize: 8000 * 1024 * 1024,
    } as GPUSupportedLimits;
    // midpoint of [500, 8000] is 4250; 4200 is closer to 4250 than 6000 is.
    expect(suggestModels(models, limits)).toEqual({
      fast: 'tiny',
      balanced: 'close-to-mid',
      quality: 'big',
    });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/ai/webgpu-provider.test.ts -t suggestModels`
Expected: FAIL with "suggestModels is not exported" / "not a function"

- [ ] **Step 3: Implement `suggestModels`**

In `web/src/ai/webgpu-provider.ts`, replace the `recommended?: boolean` field on `ModelOption`:

```typescript
  /** Which recommendation tier this model falls into for the detected GPU, if any. */
  recommendedTier?: 'fast' | 'balanced' | 'quality';
```

Replace the entire `suggestModel` function with:

```typescript
export interface SuggestedModelTiers {
  fast?: string;
  balanced?: string;
  quality?: string;
}

/** Suggests fast/balanced/quality model tiers based on GPU limits. */
export function suggestModels(
  models: ModelOption[],
  limits: GPUSupportedLimits | null,
): SuggestedModelTiers {
  if (limits === null) {
    // Default to a small model if no limits found
    return { fast: 'Qwen2.5-0.5B-Instruct-q4f16_1-MLC' };
  }

  const maxStorageBuffer = limits.maxStorageBufferBindingSize;

  const filtered = models.filter((m) => {
    if (m.bufferSizeRequiredBytes !== undefined) {
      return m.bufferSizeRequiredBytes <= maxStorageBuffer;
    }
    // Fallback heuristic if bufferSizeRequiredBytes is missing
    if (m.vramMb > 0) {
      const estimatedBufferReq = m.vramMb * 1024 * 1024;
      return estimatedBufferReq <= maxStorageBuffer;
    }
    return true;
  });

  if (filtered.length === 0) return {};

  const sorted = [...filtered].sort((a, b) => a.vramMb - b.vramMb);

  if (sorted.length === 1) {
    return { fast: sorted[0]!.id };
  }
  if (sorted.length === 2) {
    return { fast: sorted[0]!.id, quality: sorted[1]!.id };
  }

  const fast = sorted[0]!;
  const quality = sorted[sorted.length - 1]!;
  const midpoint = (fast.vramMb + quality.vramMb) / 2;
  const middleCandidates = sorted.slice(1, -1);
  const balanced = middleCandidates.reduce((closest, candidate) =>
    Math.abs(candidate.vramMb - midpoint) < Math.abs(closest.vramMb - midpoint)
      ? candidate
      : closest,
  );

  return { fast: fast.id, balanced: balanced.id, quality: quality.id };
}
```

Delete the old `suggestModel` function entirely (it's fully superseded).

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/ai/webgpu-provider.test.ts`
Expected: PASS (all `suggestModels` tests plus pre-existing `WebGpuProvider`/`detectWebGpu` tests)

Run: `npx tsc --noEmit`
Expected: FAIL at this point — `App.tsx` still imports and calls the now-deleted `suggestModel`, and `ChatPanel.tsx` still reads `m.recommended`. This is expected; Task 6 fixes the `App.tsx` call site and Task 7 fixes `ChatPanel.tsx`. Do not attempt to fix those files in this task — just confirm the failure is exactly those two leftover references (`grep -n "suggestModel\b" web/src/App.tsx` and `grep -n "\.recommended\b" web/src/ai/ChatPanel.tsx`).

- [ ] **Step 5: Commit**

```bash
git add web/src/ai/webgpu-provider.ts web/src/ai/webgpu-provider.test.ts
git commit -m "feat(web): replace single suggestModel with tiered suggestModels"
```

---

### Task 6: Fix unhandled rejection, wire toasts and tiering into `App.tsx`

**Files:**
- Modify: `web/src/App.tsx:628-768` (WebGPU-detection effect, `handleAiDownload`, `handleAiFetchModels`)
- Modify: `web/src/App.tsx` top-level render (mount `ToastProvider`)
- Test: `web/src/App.test.tsx` (new test near other AI-related tests)

**Interfaces:**
- Consumes: `useToasts` from `./Toast` (Task 3), `toErrorMessage` from `./errors` (Task 1), `AiProviderError` from `./ai/webgpu-provider` (Task 2), `suggestModels`/`SuggestedModelTiers` from `./ai/webgpu-provider` (Task 5).

- [ ] **Step 1: Write the failing test**

`App.test.tsx` has no existing mock for `./ai/webgpu-provider` — in jsdom, `detectWebGpu()` returns `false` (no `navigator.gpu`), so today's tests never exercise the WebGPU-detection branch at all. Add a `vi.mock` for that module near the other `vi.mock(...)` calls at the top of `web/src/App.test.tsx` (after the existing `vi.mock('./editor/ArtifactEditor', ...)` block, before the `beforeEach`/`afterEach` setup):

```typescript
vi.mock('./ai/webgpu-provider', async () => {
  const actual = await vi.importActual<typeof import('./ai/webgpu-provider')>(
    './ai/webgpu-provider',
  );
  return {
    ...actual,
    detectWebGpu: vi.fn(() => false),
  };
});
```

This defaults `detectWebGpu` to `false` (preserving today's behavior for every existing test) while making it a `vi.fn()` that individual tests can override. `WebGpuProvider` itself is passed through unchanged via `...actual`, so `new WebGpuProvider()` and `WebGpuProvider.getWebLlmModels` keep working exactly as before for tests that don't touch them.

Add these imports near the top of the file, alongside the existing `import { BrowserCompilerError } from './client';` line:

```typescript
import {
  AiProviderError,
  detectWebGpu,
  WebGpuProvider,
} from './ai/webgpu-provider';
```

Add the test inside the existing `describe('App', ...)` block, after the `'validation and generation send every file in path order'` test:

```typescript
  test('shows an error toast when listing WebLLM models fails', async () => {
    vi.mocked(detectWebGpu).mockReturnValue(true);
    const getWebLlmModelsSpy = vi
      .spyOn(WebGpuProvider, 'getWebLlmModels')
      .mockRejectedValue(new AiProviderError('MODEL_LIST_FAILED', 'worker crashed'));

    const client = new FakeCompilerClient();
    render(<App createClient={() => client} />);

    expect(await screen.findByText('worker crashed')).toBeTruthy();

    getWebLlmModelsSpy.mockRestore();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/App.test.tsx -t "shows an error toast when listing WebLLM models fails"`
Expected: FAIL — no toast is rendered (unhandled rejection today).

- [ ] **Step 3: Implement the fix**

In `web/src/App.tsx`, add imports and swap `suggestModel` for `suggestModels` in the existing `./ai/webgpu-provider` import block:

```typescript
import { ToastProvider, useToasts } from './Toast';
import { toErrorMessage } from './errors';
import {
  DEFAULT_MODELS,
  createModelOption,
  detectWebGpu,
  WebGpuProvider,
  getGpuLimits,
  suggestModels,
  AiProviderError,
  type ModelOption,
} from './ai/webgpu-provider';
```

(This replaces the existing `import { DEFAULT_MODELS, createModelOption, detectWebGpu, WebGpuProvider, getGpuLimits, suggestModel, type ModelOption } from './ai/webgpu-provider';` block — note `suggestModel` becomes `suggestModels` and `AiProviderError` is added.)

`useToasts()` can only be called from inside a component under `ToastProvider`. Since `App` itself needs to push toasts, restructure the default export so `ToastProvider` wraps an inner component that does the actual work. Find the current top-level `export function App(...)` declaration and its closing brace. Rename the existing function to `AppInner` (keep its body untouched) and add a thin wrapper in its place:

```typescript
export function App(props: AppProps) {
  return (
    <ToastProvider>
      <AppInner {...props} />
    </ToastProvider>
  );
}

function AppInner(props: AppProps) {
  // ... existing App body, unchanged ...
}
```

Inside `AppInner`, add near the other hooks (after `aiDispatch` is defined):

```typescript
  const { push: pushToast } = useToasts();
```

Fix the WebGPU-detection effect (`App.tsx:653-690`), replacing the block from `if (detectWebGpu()) {` through its closing `}`:

```typescript
    if (detectWebGpu()) {
      aiDispatch({ type: 'detect_available' });
      void WebGpuProvider.getWebLlmModels()
        .then((webLlmModels) => {
          setModels((current) => {
            const merged = [...current];
            for (const m of webLlmModels) {
              if (!merged.some((existing) => existing.id === m.id)) {
                merged.push(m);
              }
            }
            return merged;
          });

          void getGpuLimits().then((limits) => {
            setModels((current) => {
              const suggested = suggestModels(current, limits);
              const updated = current
                .map((m) => ({
                  ...m,
                  recommendedTier:
                    m.id === suggested.fast
                      ? ('fast' as const)
                      : m.id === suggested.balanced
                        ? ('balanced' as const)
                        : m.id === suggested.quality
                          ? ('quality' as const)
                          : undefined,
                }))
                .sort((a, b) => {
                  const rank = { fast: 0, balanced: 1, quality: 2 } as const;
                  const aRank = a.recommendedTier ? rank[a.recommendedTier] : 3;
                  const bRank = b.recommendedTier ? rank[b.recommendedTier] : 3;
                  if (aRank !== bRank) return aRank - bRank;
                  return a.vramMb - b.vramMb;
                });

              if (params.get('model') === null && suggested.fast !== undefined) {
                setSelectedModel(suggested.fast);
              }
              return updated;
            });
          });
        })
        .catch((error: unknown) => {
          const message = toErrorMessage(error, 'Failed to list WebLLM models');
          pushToast('error', message);
          aiDispatch({ type: 'error', message });
        });
    } else {
      aiDispatch({ type: 'detect_unsupported' });
    }
```

(This fixes the missing `.catch()`, switches from the deleted `suggestModel` to `suggestModels`/`recommendedTier`, and removes the dead `const allModels = [...models];` line by omitting it — it's not referenced anywhere in the replacement.)

Add toasts to `handleAiDownload`'s rejection branch (`App.tsx:707-714`):

```typescript
      .then(
        () => aiDispatch({ type: 'ready' }),
        (error: unknown) => {
          const message = toErrorMessage(error, 'Download failed');
          pushToast('error', message);
          aiDispatch({ type: 'error', message });
        },
      );
```

Add a toast to `handleAiFetchModels`'s catch (`App.tsx:762-767`):

```typescript
      .catch((error: unknown) => {
        const message = toErrorMessage(error, 'Fetch failed');
        pushToast('error', message);
        aiDispatch({ type: 'error', message });
      });
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/App.test.tsx`
Expected: PASS, including the new toast test and all pre-existing `App.test.tsx` tests (the `AppInner` extraction must not change any other test's behavior — `App` is still the exported component under test).

Run: `npx tsc --noEmit` (from `web/`)
Expected: FAIL only on `ChatPanel.tsx`'s remaining `m.recommended` reference (fixed in Task 7). No other errors should remain.

- [ ] **Step 5: Commit**

```bash
git add web/src/App.tsx web/src/App.test.tsx
git commit -m "fix(web): surface AI/model-list failures as toasts, adopt tiered recommendations"
```

---

### Task 7: Render recommendation tiers in `ChatPanel`

**Files:**
- Modify: `web/src/ai/ChatPanel.tsx:170-175` (the `<option>` mapping)
- Test: `web/src/ai/ChatPanel.test.tsx`

**Interfaces:**
- Consumes: `ModelOption.recommendedTier` (Task 5).

- [ ] **Step 1: Write the failing test**

Add to `web/src/ai/ChatPanel.test.tsx`:

```typescript
test('shows the recommendation tier label for a tiered model', () => {
  render(
    <ChatPanel
      messages={emptyMessages}
      activeFileContent=""
      aiState={initialProviderState}
      actionsDisabled={false}
      onSend={vi.fn()}
      onExplain={vi.fn()}
      onSuggestProjection={vi.fn()}
      onAccept={vi.fn()}
      onDiscard={vi.fn()}
      onDownloadModel={vi.fn()}
      onUseHeuristic={vi.fn()}
      selectedModel="Qwen2.5-0.5B-Instruct-q4f16_1-MLC"
      onModelChange={vi.fn()}
      models={[
        { ...DEFAULT_MODELS[0]!, recommendedTier: 'fast' },
        { ...DEFAULT_MODELS[1]! },
      ]}
      onReset={vi.fn()}
      onAddModel={vi.fn()}
      onFetchModels={vi.fn()}
    />,
  );

  const option = screen.getByRole('option', {
    name: /Recommended · Fast/i,
  });
  expect(option).toBeTruthy();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/ai/ChatPanel.test.tsx -t "recommendation tier"`
Expected: FAIL — `ChatPanel.tsx` still reads `m.recommended` (undefined on the new `ModelOption` shape), so no tier label renders.

- [ ] **Step 3: Implement the tier label**

In `web/src/ai/ChatPanel.tsx`, replace the `<option>` mapping (lines 170-175):

```tsx
                          {models.map((m: ModelOption) => {
                            const tierLabel =
                              m.recommendedTier === 'fast'
                                ? ' (Recommended · Fast)'
                                : m.recommendedTier === 'balanced'
                                  ? ' (Recommended · Balanced)'
                                  : m.recommendedTier === 'quality'
                                    ? ' (Recommended · Quality)'
                                    : '';
                            return (
                              <option key={m.id} value={m.id}>
                                {m.label} — {m.description}
                                {tierLabel}
                              </option>
                            );
                          })}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/ai/ChatPanel.test.tsx`
Expected: PASS (new test plus all pre-existing `ChatPanel.test.tsx` tests)

Run: `npx tsc --noEmit` (from `web/`)
Expected: no errors — this closes out the `recommended` → `recommendedTier` rename across the codebase.

Run: `npx vitest run` (from `web/`)
Expected: full suite PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/ai/ChatPanel.tsx web/src/ai/ChatPanel.test.tsx
git commit -m "feat(web): render fast/balanced/quality recommendation labels in model picker"
```

---

### Task 8: Full verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full TypeScript check**

Run (from `web/`): `npm run check`
Expected: no errors

- [ ] **Step 2: Run the full test suite**

Run (from `web/`): `npm test`
Expected: all tests pass, including every test added in Tasks 1-7

- [ ] **Step 3: Grep for leftover references to the old API**

Run: `grep -rn "suggestModel\b\|\.recommended\b" web/src --include=*.ts --include=*.tsx`

Expected: no matches other than `recommendedTier` occurrences (the `\b` boundary should exclude those, but eyeball the output). Fix any stragglers found.

- [ ] **Step 4: Manual smoke check (if a WebGPU-capable browser is available)**

Run `npm run build && npm run preview` from `web/`, open the preview URL, open the model dropdown in the Assistant panel, and confirm: (a) multiple entries show distinct `(Recommended · Fast/Balanced/Quality)` labels when enough models fit the detected GPU, (b) every model from the dynamic list is still present in the dropdown, (c) temporarily breaking the worker (e.g. throwing inside `handleListModels` in `ai.worker.ts`, then reverting) produces a visible toast instead of a silent failure.

No commit for this task — it's verification only.
