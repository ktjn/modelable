# Browser Editor MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the browser compiler proof UI with a static, single-file React and Monaco editor that validates, formats, generates, previews, imports, and exports entirely in the browser.

**Architecture:** React owns layout and user-facing lifecycle state, while narrow Monaco adapters own the source and read-only artifact models. The existing `BrowserCompilerClient`, protocol v1, Pyodide worker, and Python compiler remain the semantic boundary; asynchronous results are revision-checked before they can update diagnostics or artifacts.

**Tech Stack:** React 19.2.7, React DOM 19.2.7, Monaco Editor 0.55.1, TypeScript 7.0.2, Vite 8.1.5, Vitest 4.1.10, Testing Library, jsdom, Playwright 1.61.1, Pyodide 314.0.2.

**Design:** [Browser Editor MVP — Design](../../specs/archived/2026-07-19-browser-editor-mvp-design.md)

## Global Constraints

- Work in an isolated worktree created with `superpowers:using-git-worktrees`; do not implement directly in a dirty `main` checkout.
- Keep Phase 2 single-file with one stable source URI: `file:///main.mdl`.
- Keep the deployed base path exactly `/modelable/playground/`.
- Preserve `BrowserCompilerClient`, browser protocol version 1, and the Pyodide worker as the compiler boundary.
- Do not add a protocol method or field unless the existing diagnostic or artifact DTO cannot meet a tested requirement.
- Bundle React, Monaco, workers, Pyodide, Python wheels, and fixtures as same-origin assets; add no CDN, telemetry, remote API, or server persistence.
- Keep compilation user-triggered; do not add debounced or continuous compilation.
- Accept only `.mdl` and `.txt` imports up to `1_048_576` bytes.
- Treat imported source and generated artifacts as untrusted text.
- Keep multi-file workspaces, IndexedDB, language services, WebLLM, and the VS Code Language Model adapter out of this implementation.
- Retain all native/browser conformance and compiler timing budgets.
- Before every commit, run these commands from `cli/` in this order:

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

## File Structure

### Browser application

- Modify `web/package.json` and `web/package-lock.json`: pin React, Monaco, DOM-test dependencies, and rename the package from spike to playground.
- Modify `web/tsconfig.json`: enable `react-jsx` and DOM library typing.
- Modify `web/vite.config.ts`: retain the production base, split Monaco into a named chunk, and keep Vitest defaults.
- Replace `web/src/main.ts` with `web/src/main.tsx`: bootstrap React with `createRoot`.
- Modify `web/index.html`: reduce the document to the CSP, metadata, skip link target, and React root.
- Modify `web/src/style.css`: style the responsive editor workbench and accessible states.
- Create `web/src/App.tsx`: compose runtime lifecycle, toolbar, editors, diagnostics, artifact selection, and file actions.
- Create `web/src/App.test.tsx`: component tests using a fake compiler and mocked Monaco panes.
- Create `web/src/app-state.ts` and `web/src/app-state.test.ts`: reducer, revision checks, artifact freshness, and operation exclusion.
- Create `web/src/example.mdl`: immediately available initial single-file source.

### Monaco boundary

- Create `web/src/editor/monaco-environment.ts`: configure the editor and JSON Vite workers.
- Create `web/src/editor/SourceEditor.tsx`: own the `file:///main.mdl` model and expose an imperative source-editor handle.
- Create `web/src/editor/ArtifactEditor.tsx`: own the read-only JSON model.
- Create `web/src/editor/types.ts`: define `SourceEditorHandle`.
- Create `web/src/diagnostics.ts` and `web/src/diagnostics.test.ts`: map browser diagnostics to Monaco markers and retain document-level diagnostics.

### Local files

- Create `web/src/files.ts` and `web/src/files.test.ts`: validate imports, sanitize filenames, and download text with object URLs.

### Verification and delivery

- Modify `web/tests/playground.spec.ts`: cover the complete real-editor workflow, downloads, import confirmation, stale artifacts, failure/retry, focus, and hostile text.
- Modify `web/tests/conformance.spec.ts`: preserve test-only compiler access after React bootstrap.
- Modify `web/scripts/check-budgets.mjs` and `web/src/budgets.test.ts`: report Monaco separately without inventing a Phase 2 limit.
- Rename `.github/scripts/run_browser_spike.py` to `.github/scripts/run_browser_playground.py`.
- Rename `cli/tests/test_browser_spike_runner.py` to `cli/tests/test_browser_playground_runner.py`.
- Modify `.github/workflows/validate.yml`, `.github/scripts/detect_validate_surfaces.py`, `cli/tests/test_release_workflow.py`, and `cli/tests/test_validate_surface_detection.py`: use the truthful playground gate name.
- Modify `docs/architecture.md`, `docs/maintainers.md`, `docs/playground-design.md`, and `ROADMAP.md`: document the shipped editor and the next phase.
- Move this plan and its design spec into `docs/superpowers/plans/archived/` and `docs/superpowers/specs/archived/` in the final implementation task.

---

### Task 1: React shell and pinned browser toolchain

**Files:**
- Modify: `web/package.json`
- Modify: `web/package-lock.json`
- Modify: `web/tsconfig.json`
- Modify: `web/index.html`
- Delete: `web/src/main.ts`
- Create: `web/src/main.tsx`
- Create: `web/src/App.tsx`
- Create: `web/src/App.test.tsx`
- Create: `web/src/example.mdl`

**Interfaces:**
- Consumes: existing Vite entry point and `/modelable/playground/` base.
- Produces: `App`, a React root, an immediately editable initial source, and jsdom component-test support.

- [ ] **Step 1: Install exact runtime and test dependencies**

Run from `web/`:

```powershell
npm pkg set name=modelable-playground
npm install --save-exact react@19.2.7 react-dom@19.2.7 monaco-editor@0.55.1
npm install --save-dev --save-exact @axe-core/playwright@4.12.1 @types/react@19.2.17 @types/react-dom@19.2.3 @testing-library/react@16.3.2 @testing-library/user-event@14.6.1 jsdom@29.1.1
```

Expected: `package.json` and `package-lock.json` contain the exact versions; `pyodide` remains `314.0.2`.

- [ ] **Step 2: Write the failing React-shell test**

Create `web/src/App.test.tsx`:

```tsx
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
```

- [ ] **Step 3: Run the test to verify the missing React shell**

Run from `web/`:

```powershell
npm test -- src/App.test.tsx
```

Expected: FAIL because `App.tsx` does not exist.

- [ ] **Step 4: Add JSX configuration, initial source, and minimal shell**

Add `"jsx": "react-jsx"`, `"lib": ["ES2022", "DOM", "DOM.Iterable"]`, and
`"types": ["node", "vite/client", "vitest/globals"]` to `compilerOptions` in
`web/tsconfig.json`.

Create `web/src/example.mdl`:

```mdl
domain customer {
  owner: "team-customer"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
    email?: string
  }
}
```

Create `web/src/App.tsx` with the initial semantic structure:

```tsx
import initialSource from './example.mdl?raw';

export function App() {
  return (
    <main className="workbench">
      <header className="workbench-header">
        <div>
          <p className="eyebrow">Local schema workbench</p>
          <h1>Modelable playground</h1>
        </div>
        <p role="status" aria-live="polite">
          Initializing compiler…
        </p>
      </header>
      <nav className="toolbar" aria-label="Playground actions">
        <button type="button">Import</button>
        <button type="button">Export source</button>
        <button type="button" disabled>Validate</button>
        <button type="button" disabled>Format</button>
        <button type="button" disabled>Generate</button>
        <button type="button" disabled>Export artifact</button>
      </nav>
      <section className="workspace" aria-label="Single-file workspace">
        <section aria-label="Modelable source" data-initial-source={initialSource} />
        <section aria-label="Generated JSON Schema" />
      </section>
    </main>
  );
}
```

Replace `web/src/main.ts` with `web/src/main.tsx`:

```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './App';
import './style.css';

const root = document.getElementById('root');
if (root === null) {
  throw new Error('Missing React root');
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

Reduce `web/index.html` to the existing CSP and metadata plus:

```html
<body>
  <a class="skip-link" href="#source-editor">Skip to source</a>
  <div id="root"></div>
  <script type="module" src="/src/main.tsx"></script>
</body>
```

Change the title to `Modelable Playground` and describe it as a local browser
editor rather than a proof.

- [ ] **Step 5: Run focused shell checks**

Run from `web/`:

```powershell
npm run check
npm test -- src/App.test.tsx
```

Expected: TypeScript passes and the shell test passes.

- [ ] **Step 6: Run the mandatory pre-commit gate and commit**

Run the four global pre-commit commands from `cli/`, then:

```powershell
git add web/package.json web/package-lock.json web/tsconfig.json web/index.html web/src/main.ts web/src/main.tsx web/src/App.tsx web/src/App.test.tsx web/src/example.mdl
git commit -m "feat: add React playground shell"
```

Expected: one commit containing only the React shell and pinned dependencies.

---

### Task 2: Monaco source, artifact, and diagnostic adapters

**Files:**
- Create: `web/src/editor/types.ts`
- Create: `web/src/editor/monaco-environment.ts`
- Create: `web/src/editor/SourceEditor.tsx`
- Create: `web/src/editor/ArtifactEditor.tsx`
- Create: `web/src/diagnostics.ts`
- Create: `web/src/diagnostics.test.ts`
- Modify: `web/src/App.tsx`
- Modify: `web/vite.config.ts`

**Interfaces:**
- Consumes: `BrowserDiagnostic`, React shell, Vite worker imports.
- Produces: `SourceEditorHandle`, `SourceEditor`, `ArtifactEditor`, `normalizeDiagnostics`, and a separately emitted Monaco chunk.

- [ ] **Step 1: Write failing diagnostic-normalization tests**

Create `web/src/diagnostics.test.ts`:

```ts
import { describe, expect, test } from 'vitest';

import { normalizeDiagnostics } from './diagnostics';
import type { BrowserDiagnostic } from './protocol';

const ranged: BrowserDiagnostic = {
  code: 'E100',
  severity: 'error',
  message: 'Invalid field',
  uri: 'file:///main.mdl',
  line: 3,
  column: 5,
  end_line: 3,
  end_column: 9,
};

describe('normalizeDiagnostics', () => {
  test('maps current-source locations to Monaco markers', () => {
    const result = normalizeDiagnostics([ranged], 'file:///main.mdl');
    expect(result.markers).toEqual([
      expect.objectContaining({
        code: 'E100',
        message: 'Invalid field',
        startLineNumber: 3,
        startColumn: 5,
        endLineNumber: 3,
        endColumn: 9,
      }),
    ]);
    expect(result.documentDiagnostics).toEqual([]);
  });

  test('retains missing or foreign locations as document diagnostics', () => {
    const result = normalizeDiagnostics(
      [
        { ...ranged, line: null, column: null },
        { ...ranged, uri: 'file:///other.mdl' },
      ],
      'file:///main.mdl',
    );
    expect(result.markers).toEqual([]);
    expect(result.documentDiagnostics).toHaveLength(2);
  });
});
```

- [ ] **Step 2: Run the focused test to verify failure**

Run from `web/`:

```powershell
npm test -- src/diagnostics.test.ts
```

Expected: FAIL because `diagnostics.ts` does not exist.

- [ ] **Step 3: Implement diagnostic normalization**

Create `web/src/diagnostics.ts`:

```ts
import type { editor } from 'monaco-editor';

import type { BrowserDiagnostic } from './protocol';

export interface NormalizedDiagnostics {
  markers: editor.IMarkerData[];
  documentDiagnostics: BrowserDiagnostic[];
}

const severity: Record<string, editor.IMarkerData['severity']> = {
  error: 8,
  warning: 4,
  info: 2,
  hint: 1,
};

export function normalizeDiagnostics(
  diagnostics: BrowserDiagnostic[],
  sourceUri: string,
): NormalizedDiagnostics {
  const markers: editor.IMarkerData[] = [];
  const documentDiagnostics: BrowserDiagnostic[] = [];
  for (const diagnostic of diagnostics) {
    if (
      diagnostic.uri !== sourceUri ||
      diagnostic.line === null ||
      diagnostic.column === null
    ) {
      documentDiagnostics.push(diagnostic);
      continue;
    }
    markers.push({
      code: diagnostic.code,
      severity: severity[diagnostic.severity] ?? 2,
      message: diagnostic.message,
      startLineNumber: Math.max(1, diagnostic.line),
      startColumn: Math.max(1, diagnostic.column),
      endLineNumber: Math.max(
        diagnostic.line,
        diagnostic.end_line ?? diagnostic.line,
      ),
      endColumn: Math.max(
        diagnostic.column + 1,
        diagnostic.end_column ?? diagnostic.column + 1,
      ),
    });
  }
  return { markers, documentDiagnostics };
}
```

- [ ] **Step 4: Add Monaco workers and imperative editor interfaces**

Create `web/src/editor/types.ts`:

```ts
import type { BrowserSource } from '../protocol';

export interface SourceEditorHandle {
  getSource(): BrowserSource;
  applyFormattedText(text: string): void;
  replaceText(text: string): void;
  focus(): void;
}
```

Create `web/src/editor/monaco-environment.ts` using Vite worker imports:

```ts
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';
import jsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker';

type MonacoScope = typeof globalThis & {
  MonacoEnvironment?: {
    getWorker(moduleId: string, label: string): Worker;
  };
};

(globalThis as MonacoScope).MonacoEnvironment = {
  getWorker(_moduleId, label) {
    return label === 'json' ? new jsonWorker() : new editorWorker();
  },
};
```

Create `SourceEditor.tsx` with:

- `forwardRef<SourceEditorHandle, SourceEditorProps>`;
- one model at `file:///main.mdl` with language id `modelable`;
- `ariaLabel: 'Model source'`, automatic layout, minimap disabled;
- a local positive version counter starting at `1`;
- `onDidChangeModelContent` calling `onRevisionChange(version)`;
- `editor.setModelMarkers(model, 'modelable', markers)`;
- `executeEdits('modelable.format', ...)` plus undo stops for formatting;
- disposal of change listeners, editor, and model.

The exported props must be:

```ts
export interface SourceEditorProps {
  initialValue: string;
  markers: editor.IMarkerData[];
  onRevisionChange(version: number): void;
}
```

Create `ArtifactEditor.tsx` with one `file:///generated.schema.json` model,
`language: 'json'`, `readOnly: true`, `ariaLabel: 'Generated JSON Schema'`,
automatic layout, and model/editor disposal.

- [ ] **Step 5: Wire both panes into the React shell**

Import `monaco-environment.ts` once from `main.tsx`. Render `SourceEditor` with a
ref and `ArtifactEditor` with an empty initial artifact. Keep all compiler
buttons disabled until Task 3.

In `web/vite.config.ts`, retain the base path and add a named Monaco chunk:

```ts
build: {
  outDir: 'dist',
  emptyOutDir: true,
  rollupOptions: {
    output: {
      manualChunks(id) {
        return id.includes('/node_modules/monaco-editor/')
          ? 'monaco'
          : undefined;
      },
    },
  },
},
```

- [ ] **Step 6: Run Monaco-focused verification**

Run from `web/`:

```powershell
npm run check
npm test -- src/diagnostics.test.ts src/App.test.tsx
npm run build
```

Expected: all tests and type checks pass; the production build emits a named
Monaco chunk plus editor and JSON worker assets.

- [ ] **Step 7: Run the mandatory pre-commit gate and commit**

Run the four global pre-commit commands from `cli/`, then:

```powershell
git add web/src/editor web/src/diagnostics.ts web/src/diagnostics.test.ts web/src/App.tsx web/src/main.tsx web/vite.config.ts
git commit -m "feat: add Monaco editor surfaces"
```

Expected: one commit containing the Monaco boundary and diagnostic mapping.

---

### Task 3: Compiler lifecycle, operations, revision safety, and retry

**Files:**
- Modify: `web/src/client.ts`
- Create: `web/src/app-state.ts`
- Create: `web/src/app-state.test.ts`
- Modify: `web/src/App.tsx`
- Modify: `web/src/App.test.tsx`

**Interfaces:**
- Consumes: `BrowserCompilerClient`, `SourceEditorHandle`, normalized diagnostics, artifact DTOs.
- Produces: `BrowserCompilerClientLike`, `AppState`, `appReducer`, operation actions, retryable client creation, and revision-safe compiler workflows.

- [ ] **Step 1: Add failing reducer tests**

Create `web/src/app-state.test.ts` covering:

```ts
import { describe, expect, test } from 'vitest';

import { appReducer, initialAppState } from './app-state';

describe('appReducer', () => {
  test('allows only one operation at a time', () => {
    const working = appReducer({ ...initialAppState, runtime: 'ready' }, {
      type: 'operationStarted',
      operation: 'validate',
      revision: 2,
    });
    expect(working.runtime).toBe('working');
    expect(
      appReducer(working, {
        type: 'operationStarted',
        operation: 'generate',
        revision: 2,
      }),
    ).toEqual(working);
  });

  test('rejects diagnostics and artifacts from an older revision', () => {
    const edited = appReducer(
      { ...initialAppState, runtime: 'working', revision: 4 },
      {
        type: 'operationSucceeded',
        operation: 'generate',
        revision: 3,
        diagnostics: [],
        artifacts: [
          {
            path: 'customer.schema.json',
            media_type: 'application/schema+json',
            content: '{}',
            source_refs: [],
          },
        ],
        duration: 12,
      },
    );
    expect(edited.artifacts).toEqual([]);
    expect(edited.runtime).toBe('ready');
    expect(edited.lastOperationDuration).toBe(12);
  });

  test('marks retained artifacts stale after edits and failed generation', () => {
    const state = {
      ...initialAppState,
      runtime: 'ready' as const,
      revision: 2,
      artifactRevision: 1,
      artifacts: [
        {
          path: 'customer.schema.json',
          media_type: 'application/schema+json',
          content: '{}',
          source_refs: [],
        },
      ],
    };
    expect(state.artifactRevision).not.toBe(state.revision);
    const failed = appReducer(state, {
      type: 'operationFailed',
      operation: 'generate',
      revision: 2,
      message: 'Generation failed',
      duration: 5,
    });
    expect(failed.artifacts).toHaveLength(1);
    expect(failed.artifactRevision).toBe(1);
  });
});
```

- [ ] **Step 2: Run reducer tests to verify failure**

Run from `web/`:

```powershell
npm test -- src/app-state.test.ts
```

Expected: FAIL because `app-state.ts` does not exist.

- [ ] **Step 3: Implement the closed application state model**

Create `app-state.ts` with:

```ts
import type { BrowserArtifact, BrowserDiagnostic } from './protocol';

export type RuntimePhase = 'loading' | 'ready' | 'working' | 'failed';
export type CompilerOperation = 'validate' | 'format' | 'generate';

export interface AppState {
  runtime: RuntimePhase;
  operation: CompilerOperation | null;
  revision: number;
  diagnostics: BrowserDiagnostic[];
  artifacts: BrowserArtifact[];
  selectedArtifactPath: string | null;
  artifactRevision: number | null;
  status: string;
  initializationDuration: number | null;
  lastOperationDuration: number | null;
}

export const initialAppState: AppState = {
  runtime: 'loading',
  operation: null,
  revision: 1,
  diagnostics: [],
  artifacts: [],
  selectedArtifactPath: null,
  artifactRevision: null,
  status: 'Initializing compiler…',
  initializationDuration: null,
  lastOperationDuration: null,
};

export type AppAction =
  | { type: 'initialized'; duration: number }
  | { type: 'runtimeFailed'; message: string; duration: number | null }
  | { type: 'retryRequested' }
  | { type: 'revisionChanged'; revision: number }
  | {
      type: 'operationStarted';
      operation: CompilerOperation;
      revision: number;
    }
  | {
      type: 'operationSucceeded';
      operation: CompilerOperation;
      revision: number;
      diagnostics: BrowserDiagnostic[];
      artifacts?: BrowserArtifact[];
      duration: number;
    }
  | {
      type: 'operationFailed';
      operation: CompilerOperation;
      revision: number;
      message: string;
      diagnostics?: BrowserDiagnostic[];
      duration: number;
    }
  | { type: 'artifactSelected'; path: string };
```

`operationSucceeded` must always record timing and return to `ready`, but it
must update diagnostics/artifacts only when `action.revision === state.revision`.
`revisionChanged` clears diagnostics and preserves artifacts with their older
`artifactRevision`. `operationFailed` records any returned diagnostics while
preserving existing artifacts. `runtimeFailed` moves worker crashes to the
retryable `failed` state. Ignore `operationStarted` unless runtime is `ready`,
and ignore artifact selections whose path is not present.

- [ ] **Step 4: Define the compiler test seam**

Export from `client.ts`:

```ts
export type BrowserCompilerClientLike = Pick<
  BrowserCompilerClient,
  | 'initialize'
  | 'openWorkspace'
  | 'formatSource'
  | 'compileJsonSchema'
  | 'dispose'
>;
```

Add optional props to `App`:

```ts
export interface AppProps {
  createClient?: () => BrowserCompilerClientLike;
  now?: () => number;
}
```

Production defaults are `() => new BrowserCompilerClient()` and
`() => performance.now()`.

- [ ] **Step 5: Add failing component tests for lifecycle and stale results**

Mock `SourceEditor` and `ArtifactEditor` in `App.test.tsx` with a textarea-backed
imperative handle. Add a fake client whose deferred promises are controlled by
the test. Cover:

- actions disabled during initialization and enabled after success;
- duplicate actions disabled while one request is pending;
- validation diagnostics rendered after a current result;
- a validation result ignored after the textarea revision changes;
- formatting calls `applyFormattedText`;
- failed generation retains and marks the old artifact stale;
- initialization failure shows **Retry compiler** and creates a fresh client.

Run:

```powershell
npm test -- src/App.test.tsx
```

Expected: FAIL because `App` has not connected the compiler lifecycle.

- [ ] **Step 6: Implement initialization and compiler actions in App**

Use `useReducer(appReducer, initialAppState)`, one client ref, and one source
editor ref. Initialization must:

1. create a fresh client;
2. expose it as `__modelableBrowserCompiler` only when `?test=1`;
3. call `initialize`;
4. dispatch duration and ready/failure state; and
5. dispose on `pagehide` and component cleanup.

Each action captures `sourceEditorRef.current.getSource()` and its version.
Validation calls `openWorkspace`. Formatting calls `formatSource`, applies
`replacement_text` only when there are no error diagnostics and the revision
is still current, then clears diagnostics invalidated by the edit. Generation
calls `compileJsonSchema`; a result with error diagnostics or no artifacts is
an `operationFailed` that preserves the prior artifact, while a successful
result stores every compiler-ordered artifact and selects the first path. All
failures use the sanitized `BrowserCompilerError.message`. A
`COMPILER_FAILED` error dispatches `runtimeFailed`; validation/format/compile
diagnostics remain recoverable operation results.

Derive Monaco markers and document-level diagnostics with
`normalizeDiagnostics`. Pass markers to `SourceEditor`; render document-level
items and the raw diagnostic count in the status region. Render initialization
and last-operation durations without making timing the accessible status
message.

Retry must dispose the terminal client, clear only runtime failure state, create
a new client, and preserve source text and retained artifacts.

- [ ] **Step 7: Run lifecycle verification**

Run from `web/`:

```powershell
npm run check
npm test -- src/app-state.test.ts src/App.test.tsx src/client.test.ts src/protocol.test.ts
```

Expected: lifecycle, stale-result, client, and protocol tests pass without a
protocol version change.

- [ ] **Step 8: Run the mandatory pre-commit gate and commit**

Run the four global pre-commit commands from `cli/`, then:

```powershell
git add web/src/client.ts web/src/app-state.ts web/src/app-state.test.ts web/src/App.tsx web/src/App.test.tsx
git commit -m "feat: connect editor compiler workflows"
```

Expected: one commit containing the lifecycle and compiler operations.

---

### Task 4: Safe import, source export, and selected-artifact export

**Files:**
- Create: `web/src/files.ts`
- Create: `web/src/files.test.ts`
- Modify: `web/src/App.tsx`
- Modify: `web/src/App.test.tsx`

**Interfaces:**
- Consumes: `SourceEditorHandle`, `BrowserArtifact`, browser `File`, `Blob`, and object URL APIs.
- Produces: `MAX_IMPORT_BYTES`, `readSourceFile`, `sanitizeDownloadName`, `downloadText`, dirty replacement confirmation, and selected-artifact export.

- [ ] **Step 1: Write failing file-boundary tests**

Create `web/src/files.test.ts`:

```ts
// @vitest-environment jsdom

import { describe, expect, test, vi } from 'vitest';

import {
  MAX_IMPORT_BYTES,
  downloadText,
  readSourceFile,
  sanitizeDownloadName,
} from './files';

describe('local file boundary', () => {
  test.each(['schema.exe', 'schema.json', 'schema'])(
    'rejects unsupported import %s',
    async (name) => {
      await expect(readSourceFile(new File(['text'], name))).rejects.toThrow(
        /\\.mdl or \\.txt/i,
      );
    },
  );

  test('rejects files above the exact size limit', async () => {
    const file = new File(
      [new Uint8Array(MAX_IMPORT_BYTES + 1)],
      'large.mdl',
    );
    await expect(readSourceFile(file)).rejects.toThrow(/1 MiB/i);
  });

  test('sanitizes an untrusted download filename', () => {
    expect(sanitizeDownloadName('../Customer<>', '.mdl')).toBe('Customer.mdl');
  });

  test('revokes the object URL after starting a download', () => {
    const createObjectURL = vi.fn(() => 'blob:test');
    const revokeObjectURL = vi.fn();
    downloadText('source', 'main.mdl', 'text/plain', {
      createObjectURL,
      revokeObjectURL,
    });
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:test');
  });
});
```

- [ ] **Step 2: Run the file tests to verify failure**

Run from `web/`:

```powershell
npm test -- src/files.test.ts
```

Expected: FAIL because `files.ts` does not exist.

- [ ] **Step 3: Implement the local file boundary**

Create `web/src/files.ts` with:

```ts
export const MAX_IMPORT_BYTES = 1_048_576;

export interface ObjectUrlApi {
  createObjectURL(blob: Blob): string;
  revokeObjectURL(url: string): void;
}

export async function readSourceFile(
  file: File,
): Promise<{ name: string; text: string }> {
  if (!/\.(?:mdl|txt)$/i.test(file.name)) {
    throw new Error('Choose a .mdl or .txt source file');
  }
  if (file.size > MAX_IMPORT_BYTES) {
    throw new Error('Source files must be 1 MiB or smaller');
  }
  return { name: file.name, text: await file.text() };
}

export function sanitizeDownloadName(name: string, extension: '.mdl' | '.json') {
  const stem =
    name
      .normalize('NFKC')
      .replace(/\.[^.]+$/, '')
      .replace(/[^a-zA-Z0-9._-]+/g, '-')
      .replace(/^[.-]+|[.-]+$/g, '')
      .slice(0, 96) || 'modelable';
  return `${stem}${extension}`;
}

export function downloadText(
  text: string,
  filename: string,
  mediaType: string,
  objectUrls: ObjectUrlApi = URL,
): void {
  const url = objectUrls.createObjectURL(new Blob([text], { type: mediaType }));
  const anchor = document.createElement('a');
  try {
    anchor.href = url;
    anchor.download = filename;
    anchor.hidden = true;
    document.body.append(anchor);
    anchor.click();
  } finally {
    anchor.remove();
    objectUrls.revokeObjectURL(url);
  }
}
```

- [ ] **Step 4: Add import/export component tests**

Extend `App.test.tsx` to cover:

- importing `customer.mdl` replaces source and clears diagnostics;
- importing over changed source calls an injected `confirmReplace` and respects
  cancellation;
- exporting source passes the current editor text and sanitized `.mdl` name to
  an injected `download`;
- multiple generated artifacts render a selector ordered exactly as returned;
- selecting an artifact updates the read-only preview;
- export downloads only the selected artifact with a `.json` name;
- export artifact stays disabled before successful generation.

Extend `AppProps` with:

```ts
confirmReplace?: (message: string) => boolean;
download?: typeof downloadText;
```

Production defaults are `globalThis.confirm` and `downloadText`.

- [ ] **Step 5: Implement toolbar file actions and artifact selection**

Add a hidden file input with `accept=".mdl,.txt,text/plain"`. The **Import**
button activates it. Track a clean source snapshot in a ref; update that
snapshot after initial load, accepted import, and source export. Compare the
current editor text to the snapshot before replacement. Track the current
source filename separately, starting with `main.mdl` and replacing it with the
accepted import name, while keeping the compiler URI fixed at
`file:///main.mdl`.

Render a labeled artifact `<select>` only when more than one artifact exists.
The preview and export button use `selectedArtifactPath`. Show a visible
`Stale—source changed after generation` label whenever
`artifactRevision !== revision`.

- [ ] **Step 6: Run local-file verification**

Run from `web/`:

```powershell
npm run check
npm test -- src/files.test.ts src/App.test.tsx src/app-state.test.ts
```

Expected: file-boundary, selection, stale-artifact, and component tests pass.

- [ ] **Step 7: Run the mandatory pre-commit gate and commit**

Run the four global pre-commit commands from `cli/`, then:

```powershell
git add web/src/files.ts web/src/files.test.ts web/src/App.tsx web/src/App.test.tsx
git commit -m "feat: add playground file workflows"
```

Expected: one commit containing import/export and selected-artifact behavior.

---

### Task 5: Responsive UX, accessibility, browser workflows, and bundle reporting

**Files:**
- Modify: `web/src/App.tsx`
- Modify: `web/src/App.test.tsx`
- Modify: `web/src/style.css`
- Modify: `web/tests/playground.spec.ts`
- Modify: `web/tests/conformance.spec.ts`
- Modify: `web/scripts/check-budgets.mjs`
- Modify: `web/src/budgets.test.ts`
- Modify: `web/vite.config.ts`

**Interfaces:**
- Consumes: complete editor application and existing real Pyodide Playwright harness.
- Produces: keyboard-accessible responsive UI, real end-to-end editor coverage, preserved conformance access, and separate Monaco size reporting.

- [ ] **Step 1: Add failing keyboard and status component tests**

Extend `App.test.tsx` to assert:

- `Control+Shift+Enter` invokes validate;
- `Shift+Alt+F` invokes format;
- `Control+Enter` invokes generate;
- shortcuts do nothing while loading or working;
- the skip link calls `SourceEditorHandle.focus`;
- status uses `role="status"` and operation failures use `role="alert"`;
- every toolbar button has a visible name and `aria-keyshortcuts` where
  applicable.

Run:

```powershell
npm test -- src/App.test.tsx
```

Expected: FAIL until shortcut and focus handling is implemented.

- [ ] **Step 2: Implement accessible interaction and responsive styling**

Add one window `keydown` listener with cleanup. Match both `Control` and `Meta`
for validate/generate, prevent default only when an enabled command runs, and
route every command through the same button handler.

Retain the existing visual language—graphite borders, blue action signal, green
ready state, orange diagnostic state—but replace textarea/pre rules with Monaco
containers. The wide layout is two panes; at `max-width: 50rem` it stacks source
above artifact. Provide visible focus, reduced-motion behavior, a minimum
44-pixel toolbar target, non-color stale/error labels, and no horizontal page
overflow at 320 CSS pixels.

- [ ] **Step 3: Refactor Playwright coverage around the real Monaco UI**

Update `playground.spec.ts` to use Monaco's labeled textarea and the revised
button names. The complete-workflow test must:

1. observe disabled compiler actions during initialization;
2. wait for `Compiler ready`;
3. replace source through Monaco;
4. validate invalid source and observe a visible diagnostic;
5. format valid compact source and observe multiline output;
6. undo to the compact source, then format it again;
7. generate and preview JSON Schema;
8. change source and observe the stale label;
9. import one in-memory `.mdl` through `setInputFiles`;
10. accept the dirty-source confirmation dialog;
11. verify source and artifact downloads and suggested extensions; and
12. assert every HTTP request remains on `http://127.0.0.1:4173`.

Retain hostile-text, test-client opt-in, pagehide disposal, native/browser
conformance, and timing-budget tests. Replace the old fixture-fetch
initialization failure case with a one-time
`**/python/runtime-manifest.json` failure, then unroute it, click
**Retry compiler**, and assert that editor text survived.

Add `AxeBuilder` from `@axe-core/playwright` and require zero automated
accessibility violations after the editor reaches ready state. Add a
320-by-720 viewport case that asserts the artifact pane follows the source pane,
every toolbar control remains reachable, and
`document.documentElement.scrollWidth === document.documentElement.clientWidth`.

- [ ] **Step 4: Add a separate report-only Monaco category**

Change `check-budgets.mjs` so enforced `BUDGETS` remain:

```js
export const BUDGETS = {
  modelableWheel: 2 * 1024 * 1024,
  application: 750 * 1024,
  additionalPython: 15 * 1024 * 1024,
};

export const REPORT_ONLY = ['monaco'];
```

Classify named `monaco-*`, `editor.worker-*`, and `json.worker-*` JavaScript
assets as `monaco` before the general application rule. `measureBudgets` and
the JSON report include all four categories, while `findViolations` evaluates
only keys in `BUDGETS`.

Extend `budgets.test.ts` to prove Monaco assets are separately reported and can
never hide application, wheel, or Python budget violations.

- [ ] **Step 5: Run the complete browser verification**

Run from `web/`:

```powershell
npm run check
npm test
npm run build
npm run test:e2e
npm run check:budgets
```

Expected: TypeScript, all Vitest tests, the production build, all Playwright
tests, compiler timing budgets, existing asset budgets, and the report-only
Monaco measurement pass.

- [ ] **Step 6: Run the mandatory pre-commit gate and commit**

Run the four global pre-commit commands from `cli/`, then:

```powershell
git add web/src/App.tsx web/src/App.test.tsx web/src/style.css web/tests/playground.spec.ts web/tests/conformance.spec.ts web/scripts/check-budgets.mjs web/src/budgets.test.ts web/vite.config.ts
git commit -m "test: prove the browser editor workflow"
```

Expected: one commit containing accessible UX and complete browser evidence.

---

### Task 6: Truthful gate naming, documentation, roadmap, and archival

**Files:**
- Rename: `.github/scripts/run_browser_spike.py` → `.github/scripts/run_browser_playground.py`
- Rename: `cli/tests/test_browser_spike_runner.py` → `cli/tests/test_browser_playground_runner.py`
- Modify: `.github/workflows/validate.yml`
- Modify: `.github/scripts/detect_validate_surfaces.py`
- Modify: `cli/tests/test_browser_playground_runner.py`
- Modify: `cli/tests/test_release_workflow.py`
- Modify: `cli/tests/test_validate_surface_detection.py`
- Modify: `docs/architecture.md`
- Modify: `docs/maintainers.md`
- Modify: `docs/playground-design.md`
- Modify: `ROADMAP.md`
- Move: `docs/superpowers/specs/2026-07-19-browser-editor-mvp-design.md` → `docs/superpowers/specs/archived/2026-07-19-browser-editor-mvp-design.md`
- Move: `docs/superpowers/plans/2026-07-19-browser-editor-mvp.md` → `docs/superpowers/plans/archived/2026-07-19-browser-editor-mvp.md`

**Interfaces:**
- Consumes: completed editor, browser gate, roadmap, and plan/spec archive policy.
- Produces: one truthful `run_browser_playground.py` gate, shipped Phase 2 docs, archived completed planning artifacts, and a roadmap whose next item is conversational operational management.

- [ ] **Step 1: Write failing gate-name expectations**

Update focused tests to expect:

```python
SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "run_browser_playground.py"
```

and:

```python
assert "uv run python .github/scripts/run_browser_playground.py --skip-install" in commands
```

Update validation-surface expectations so changes to
`.github/scripts/run_browser_playground.py` activate the browser surface.

Run from `cli/`:

```powershell
uv run pytest tests/test_browser_playground_runner.py tests/test_release_workflow.py tests/test_validate_surface_detection.py -v
```

Expected: FAIL until the script, workflow, and detector use the new name.

- [ ] **Step 2: Rename the complete browser gate**

Run:

```powershell
git mv .github/scripts/run_browser_spike.py .github/scripts/run_browser_playground.py
git mv cli/tests/test_browser_spike_runner.py cli/tests/test_browser_playground_runner.py
```

Change the script parser description to `Run the complete browser playground
gate.` Change the GitHub Actions job display name to `Browser playground`.
Update every live, non-archived script, workflow, test, and maintainer command
to `run_browser_playground.py`. Do not rewrite archived plan/spec history.

- [ ] **Step 3: Run gate-name tests**

Run from `cli/`:

```powershell
uv run pytest tests/test_browser_playground_runner.py tests/test_release_workflow.py tests/test_validate_surface_detection.py -v
```

Expected: all focused gate and workflow tests pass.

- [ ] **Step 4: Update shipped architecture and maintainer documentation**

In `docs/architecture.md`, replace `Minimal browser UI` with
`React and Monaco single-file editor` while retaining the same client, worker,
Pyodide, and Python compiler direction.

In `docs/maintainers.md`:

- rename the section to `Browser playground troubleshooting`;
- use `run_browser_playground.py`;
- describe Monaco worker failures alongside Pyodide asset failures;
- retain `/modelable/playground/`, combined Pages assembly, conformance, and
  budget commands; and
- explain that Monaco is reported separately while compiler budgets remain
  enforced.

In `docs/playground-design.md`, mark Phase 2 shipped and list the delivered
single-file React shell, Monaco diagnostics/formatting, selected artifact
preview, import/export, failure retry, accessibility coverage, and static
deployment. Link to the archived design.

In `ROADMAP.md`, mark the browser editor MVP shipped, update its design link to
the archived path, and mark the existing conversational operational-management
item as **Next**. Keep WebLLM in Phase 6 and the VS Code Language Model adapter
at the end of the candidate pool.

- [ ] **Step 5: Archive the completed plan and specification**

Run:

```powershell
git mv docs/superpowers/specs/2026-07-19-browser-editor-mvp-design.md docs/superpowers/specs/archived/2026-07-19-browser-editor-mvp-design.md
git mv docs/superpowers/plans/2026-07-19-browser-editor-mvp.md docs/superpowers/plans/archived/2026-07-19-browser-editor-mvp.md
```

Update every live cross-link to the archived paths.

Inside the archived specification, change the playground link to
`../../../playground-design.md`, the roadmap link to `../../../../ROADMAP.md`,
and the implementation-plan link to
`../../plans/archived/2026-07-19-browser-editor-mvp.md`. Inside the archived
plan, change the design link to
`../../specs/archived/2026-07-19-browser-editor-mvp-design.md`.

- [ ] **Step 6: Run the mandatory document review**

Invoke `doc-review` and require all four phases to pass. Confirm:

- active `plans/` and `specs/` contain no completed editor documents;
- roadmap and playground links resolve to the archived files;
- Phase 3 remains multi-file/language services;
- Phase 6 remains WebLLM; and
- no ADR update is needed because the implementation realizes the accepted
  architecture without changing its boundaries.

- [ ] **Step 7: Run the complete repository and deployment gates**

Run from the repository root:

```powershell
uv run python .github/scripts/run_browser_playground.py --skip-install
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
uv run --project cli python .github/scripts/assemble_pages.py --site site --web-dist web/dist
Test-Path site/playground/index.html
Select-String -Path site/playground/index.html -Pattern '/modelable/playground/'
```

Expected: the browser playground gate, strict docs build, and Pages assembly
pass; `site/playground/index.html` exists and references the configured base.

- [ ] **Step 8: Run the mandatory pre-commit gate and commit**

Run the four global pre-commit commands from `cli/`, then:

```powershell
git add .github/scripts/run_browser_playground.py .github/scripts/detect_validate_surfaces.py .github/workflows/validate.yml cli/tests/test_browser_playground_runner.py cli/tests/test_release_workflow.py cli/tests/test_validate_surface_detection.py docs/architecture.md docs/maintainers.md docs/playground-design.md ROADMAP.md docs/superpowers/specs/archived/2026-07-19-browser-editor-mvp-design.md docs/superpowers/plans/archived/2026-07-19-browser-editor-mvp.md
git commit -m "docs: ship browser editor MVP"
```

Expected: one final implementation commit with truthful gates, shipped docs,
roadmap progression, and archived completed planning artifacts.

---

## Final verification checklist

- [ ] `git status --short` contains no unexpected files.
- [ ] `npm run check` passes from `web/`.
- [ ] `npm test` passes from `web/`.
- [ ] `npm run build` passes from `web/`.
- [ ] `npm run test:e2e` passes from `web/`.
- [ ] `npm run check:budgets` preserves compiler limits and reports Monaco.
- [ ] Native/browser conformance snapshots remain unchanged.
- [ ] The four mandatory CLI commands pass in the required order.
- [ ] Strict MkDocs and combined Pages assembly pass.
- [ ] `site/playground/index.html` loads all assets under `/modelable/playground/`.
- [ ] No browser request leaves the static site's origin.
- [ ] Active plan/spec directories contain only unfinished work.
- [ ] Phase 3 workspace/language services and Phase 6 WebLLM remain deferred.
