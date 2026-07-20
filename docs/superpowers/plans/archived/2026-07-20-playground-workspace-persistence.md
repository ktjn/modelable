# Playground Workspace and Persistence Implementation Plan

**Status:** Completed and archived on 2026-07-20.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Playground's temporary single-file state with a safe, persistent multi-file Modelable workspace that validates and compiles as one deterministic snapshot.

**Architecture:** A pure TypeScript workspace domain owns normalized `.mdl` paths, immutable file mutations, and monotonic revisions. A versioned IndexedDB repository persists validated snapshots without allowing stale writes, while a Monaco model registry and React adapters render the active file and submit sorted whole-workspace sources through the existing browser compiler client. Derived diagnostics and artifacts remain revision-bound and unpersisted.

**Tech Stack:** TypeScript 7, React 19, Monaco Editor 0.55, IndexedDB, `fake-indexeddb` 6.2.5 for isolated Vitest coverage, Pyodide browser compiler worker, Vitest 4, Testing Library, Playwright 1.61, Vite 8.

## Global Constraints

- The accepted
  [Playground Workspace and Persistence design](../../specs/archived/2026-07-20-playground-workspace-persistence-design.md)
  is authoritative.
- Phase 3a supports one local workspace containing `.mdl` text files only.
- Paths use forward slashes, remain relative, end in `.mdl`, and reject empty segments, `.`, `..`, absolute paths, URL schemes, control characters, NUL, and normalized duplicates.
- The workspace always contains at least one file; reset produces the bundled `main.mdl`.
- Every file mutation increments that file's positive version and the workspace's positive revision.
- Validation and compilation receive every file in deterministic path order; formatting mutates only the active file.
- Phase 3a keeps browser compiler protocol version `1`; the existing
  `workspace.open`, `source.format`, and `compile.jsonSchema` payloads already
  represent source arrays and active-file formatting.
- Stale compiler and persistence completions cannot replace newer state.
- IndexedDB stores source files, versions, active file, workspace ID, schema version, and workspace revision only.
- Diagnostics, artifacts, hashes, timing data, compiler caches, provider data, and credentials are derived and must not be persisted.
- Invalid or incompatible storage is never sent to the compiler or overwritten automatically.
- Workspace contents remain local and same-origin; imported or recovered source is rendered as text, never HTML.
- Existing CSP, Pyodide pinning, worker isolation, accessibility, browser/native conformance, and bundle budgets remain enforced.
- Completion, hover, definition, references, rename semantics, visualization, WebLLM, service-worker offline support, File System Access API synchronization, ZIP workflows, and multiple workspaces are out of scope.
- Before every commit, run these commands from `cli/` and require clean success:

```bash
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

---

### Task 1: Add the Immutable Workspace Domain

**Files:**
- Create: `web/src/workspace.ts`
- Create: `web/src/workspace.test.ts`

**Interfaces:**
- Consumes: bundled default source text and existing `BrowserSource`.
- Produces:

```ts
export const PLAYGROUND_WORKSPACE_SCHEMA_VERSION = 1 as const;

export interface PlaygroundFile {
  path: string;
  content: string;
  version: number;
}

export interface PlaygroundWorkspace {
  schemaVersion: typeof PLAYGROUND_WORKSPACE_SCHEMA_VERSION;
  id: string;
  revision: number;
  files: PlaygroundFile[];
  activeFile: string;
}

export type WorkspaceMutation =
  | { type: 'create'; path: string; content?: string }
  | { type: 'update'; path: string; content: string }
  | { type: 'rename'; from: string; to: string }
  | { type: 'delete'; path: string }
  | { type: 'select'; path: string };

export type WorkspaceValidationReason = 'invalid' | 'incompatible';

export class WorkspaceValidationError extends Error {
  constructor(
    readonly reason: WorkspaceValidationReason,
    message: string,
  );
}

export function normalizeWorkspacePath(path: string): string;
export function createDefaultWorkspace(
  defaultSource: string,
  id?: string,
): PlaygroundWorkspace;
export function mutateWorkspace(
  workspace: PlaygroundWorkspace,
  mutation: WorkspaceMutation,
): PlaygroundWorkspace;
export function mutateWorkspaceBatch(
  workspace: PlaygroundWorkspace,
  mutations: WorkspaceMutation[],
): PlaygroundWorkspace;
export function parseWorkspaceRecord(value: unknown): PlaygroundWorkspace;
export function workspaceSources(
  workspace: PlaygroundWorkspace,
): BrowserSource[];
```

- `BrowserSource.uri` remains a `file:///` URI derived from the normalized path.
- `BrowserSource.version` is the corresponding `PlaygroundFile.version`.

- [ ] **Step 1: Write failing path and default-workspace tests**

```ts
import { describe, expect, test } from 'vitest';

import {
  WorkspaceValidationError,
  createDefaultWorkspace,
  normalizeWorkspacePath,
} from './workspace';

describe('playground workspace paths', () => {
  test.each([
    ['', ''],
    ['../secret.mdl', '../secret.mdl'],
    ['/absolute.mdl', '/absolute.mdl'],
    ['file:///main.mdl', 'file:///main.mdl'],
    ['domain//model.mdl', 'domain//model.mdl'],
    ['domain/./model.mdl', 'domain/./model.mdl'],
    ['domain/model.txt', 'domain/model.txt'],
    ['domain/\u202emodel.mdl', 'domain/\u202emodel.mdl'],
  ])('rejects unsafe path %s', (input) => {
    expect(() => normalizeWorkspacePath(input)).toThrow(
      WorkspaceValidationError,
    );
  });

  test('normalizes separators and creates the default workspace', () => {
    expect(normalizeWorkspacePath('domain\\model.mdl')).toBe(
      'domain/model.mdl',
    );
    expect(createDefaultWorkspace('domain demo {}')).toEqual({
      schemaVersion: 1,
      id: 'local',
      revision: 1,
      files: [
        {
          path: 'main.mdl',
          content: 'domain demo {}',
          version: 1,
        },
      ],
      activeFile: 'main.mdl',
    });
  });
});
```

- [ ] **Step 2: Run the path tests and verify RED**

Run:

```bash
cd web
npx vitest run src/workspace.test.ts
```

Expected: FAIL because `workspace.ts` does not exist.

- [ ] **Step 3: Implement path normalization and the default workspace**

```ts
const controlCharacters = /[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/u;
const urlScheme = /^[A-Za-z][A-Za-z0-9+.-]*:/u;

export function normalizeWorkspacePath(path: string): string {
  const normalized = path.replaceAll('\\', '/');
  const segments = normalized.split('/');
  if (
    normalized.length === 0 ||
    normalized.startsWith('/') ||
    urlScheme.test(normalized) ||
    controlCharacters.test(normalized) ||
    !normalized.endsWith('.mdl') ||
    segments.some(
      (segment) =>
        segment.length === 0 || segment === '.' || segment === '..',
    )
  ) {
    throw new WorkspaceValidationError(
      'invalid',
      'Choose a safe relative .mdl path',
    );
  }
  return normalized;
}
```

Construct the default record exactly as asserted, with positive versions and
no timestamp or environment-dependent fields.

- [ ] **Step 4: Write failing mutation, parsing, and source-order tests**

```ts
test('mutations are immutable and increment exact versions', () => {
  const initial = createDefaultWorkspace('domain demo {}');
  const created = mutateWorkspace(initial, {
    type: 'create',
    path: 'customer/customer.mdl',
    content: 'domain customer {}',
  });
  const edited = mutateWorkspace(created, {
    type: 'update',
    path: 'customer/customer.mdl',
    content: 'domain customer { entity Customer@1 {} }',
  });
  const renamed = mutateWorkspace(edited, {
    type: 'rename',
    from: 'customer/customer.mdl',
    to: 'customer/model.mdl',
  });

  expect(initial.files).toHaveLength(1);
  expect(created.revision).toBe(2);
  expect(edited.revision).toBe(3);
  expect(edited.files.find((file) => file.path === 'customer/customer.mdl'))
    .toMatchObject({ version: 2 });
  expect(renamed).toMatchObject({
    revision: 4,
    activeFile: 'customer/model.mdl',
  });
});

test('rejects duplicates, missing selections, and final-file deletion', () => {
  const workspace = createDefaultWorkspace('domain demo {}');
  expect(() =>
    mutateWorkspace(workspace, { type: 'create', path: 'main.mdl' }),
  ).toThrow(WorkspaceValidationError);
  expect(() =>
    mutateWorkspace(workspace, { type: 'select', path: 'missing.mdl' }),
  ).toThrow(WorkspaceValidationError);
  expect(() =>
    mutateWorkspace(workspace, { type: 'delete', path: 'main.mdl' }),
  ).toThrow(WorkspaceValidationError);
});

test('parses only complete valid records and emits sorted browser sources', () => {
  const parsed = parseWorkspaceRecord({
    schemaVersion: 1,
    id: 'local',
    revision: 7,
    activeFile: 'z.mdl',
    files: [
      { path: 'z.mdl', content: 'domain z {}', version: 3 },
      { path: 'a.mdl', content: 'domain a {}', version: 2 },
    ],
  });

  expect(workspaceSources(parsed)).toEqual([
    { uri: 'file:///a.mdl', text: 'domain a {}', version: 2 },
    { uri: 'file:///z.mdl', text: 'domain z {}', version: 3 },
  ]);
  try {
    parseWorkspaceRecord({ ...parsed, schemaVersion: 2 });
    expect.unreachable('schema version 2 must be rejected');
  } catch (error) {
    expect(error).toMatchObject({
      name: 'WorkspaceValidationError',
      reason: 'incompatible',
    });
  }
});

test('a failed batch leaves the original workspace unchanged', () => {
  const initial = createDefaultWorkspace('domain demo {}');
  expect(() =>
    mutateWorkspaceBatch(initial, [
      { type: 'create', path: 'customer.mdl', content: 'domain customer {}' },
      { type: 'create', path: '../escape.mdl', content: 'secret' },
    ]),
  ).toThrow(WorkspaceValidationError);
  expect(initial).toEqual(createDefaultWorkspace('domain demo {}'));
});
```

- [ ] **Step 5: Run the domain tests and verify RED**

Run:

```bash
cd web
npx vitest run src/workspace.test.ts
```

Expected: FAIL because mutation, parsing, and source conversion are not
implemented.

- [ ] **Step 6: Implement immutable mutations, parsing, and source conversion**

Implement every mutation by returning a new workspace and new files array.
`select` increments the workspace revision but does not increment a file
version. `rename` increments the renamed file version because its compiler URI
changes. `delete` selects the lexicographically first remaining file when the
active file is removed. `parseWorkspaceRecord()` accepts exactly
`schemaVersion`, `id`, `revision`, `files`, and `activeFile` on the workspace
record, and exactly `path`, `content`, and `version` on each file. It rejects
extra or missing keys, duplicate normalized paths, and an `activeFile` that
does not exist. A schema version other than `1` throws
`WorkspaceValidationError` with `reason: 'incompatible'`; every other shape or
path failure uses `reason: 'invalid'`.

`mutateWorkspaceBatch()` reduces mutations against local immutable snapshots
and returns only the final snapshot. Because no mutation changes its input, a
later failure cannot expose any earlier intermediate snapshot to the caller.

Use:

```ts
function sourceUri(path: string): string {
  return `file:///${path.split('/').map(encodeURIComponent).join('/')}`;
}
```

Sort copies of file arrays; never mutate the workspace passed by the caller.

- [ ] **Step 7: Run focused and web checks**

Run:

```bash
cd web
npx vitest run src/workspace.test.ts src/protocol.test.ts
npm run check
```

Expected: all selected tests and TypeScript checks PASS.

- [ ] **Step 8: Run the mandatory pre-commit gate and commit**

Run:

```bash
cd cli
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
cd ..
git add web/src/workspace.ts web/src/workspace.test.ts
git commit -m "feat: add playground workspace domain"
```

Expected: all four CLI commands pass and the commit contains only Task 1.

---

### Task 2: Add the Versioned IndexedDB Repository

**Files:**
- Modify: `web/package.json`
- Modify: `web/package-lock.json`
- Create: `web/src/workspace-repository.ts`
- Create: `web/src/workspace-repository.test.ts`

**Interfaces:**
- Consumes: `PlaygroundWorkspace` and `parseWorkspaceRecord()` from Task 1.
- Produces:

```ts
export type WorkspaceLoadResult =
  | { status: 'missing' }
  | { status: 'ready'; workspace: PlaygroundWorkspace }
  | {
      status: 'recovery-required';
      reason: 'invalid' | 'incompatible';
      raw: unknown;
    };

export type WorkspaceSaveResult = 'saved' | 'stale';

export interface WorkspaceRepository {
  load(id: string): Promise<WorkspaceLoadResult>;
  save(workspace: PlaygroundWorkspace): Promise<WorkspaceSaveResult>;
  remove(id: string): Promise<void>;
}

export class IndexedDbWorkspaceRepository implements WorkspaceRepository {
  constructor(
    factory?: IDBFactory,
    databaseName?: string,
  );
}
```

- Production defaults: database `modelable-playground`, version `1`, object
  store `workspaces`, key path `id`.
- Tests inject a new `IDBFactory` from `fake-indexeddb` for each case.

- [ ] **Step 1: Add the isolated IndexedDB test dependency**

Run:

```bash
cd web
npm install --save-dev --save-exact fake-indexeddb@6.2.5
```

Expected: `package.json` and `package-lock.json` contain exactly version 6.2.5.

- [ ] **Step 2: Write failing repository round-trip tests**

```ts
import { IDBFactory } from 'fake-indexeddb';
import { beforeEach, describe, expect, test } from 'vitest';

import { createDefaultWorkspace, mutateWorkspace } from './workspace';
import { IndexedDbWorkspaceRepository } from './workspace-repository';

let repository: IndexedDbWorkspaceRepository;

beforeEach(() => {
  repository = new IndexedDbWorkspaceRepository(
    new IDBFactory(),
    `test-${crypto.randomUUID()}`,
  );
});

test('round-trips a valid multi-file workspace', async () => {
  const workspace = mutateWorkspace(
    createDefaultWorkspace('domain demo {}'),
    {
      type: 'create',
      path: 'customer/customer.mdl',
      content: 'domain customer {}',
    },
  );

  await expect(repository.save(workspace)).resolves.toBe('saved');
  await expect(repository.load('local')).resolves.toEqual({
    status: 'ready',
    workspace,
  });
});

test('removes only the requested workspace', async () => {
  const workspace = createDefaultWorkspace('domain demo {}');
  await repository.save(workspace);
  await repository.remove('local');
  await expect(repository.load('local')).resolves.toEqual({
    status: 'missing',
  });
});
```

- [ ] **Step 3: Run repository tests and verify RED**

Run:

```bash
cd web
npx vitest run src/workspace-repository.test.ts
```

Expected: FAIL because `workspace-repository.ts` does not exist.

- [ ] **Step 4: Implement database open, load, save, and remove**

Use one helper that converts `IDBRequest` completion to a promise and one
helper that resolves or rejects on transaction completion. During
`onupgradeneeded`, create only the `workspaces` store:

```ts
if (!database.objectStoreNames.contains('workspaces')) {
  database.createObjectStore('workspaces', { keyPath: 'id' });
}
```

`load()` passes the retrieved value through `parseWorkspaceRecord()`. A
schema-version mismatch returns `reason: 'incompatible'`; every other
validation failure returns `reason: 'invalid'`. Preserve the unmodified raw
value in the result.

- [ ] **Step 5: Write failing stale-save and recovery tests**

```ts
test('a stale revision cannot overwrite a newer workspace', async () => {
  const initial = createDefaultWorkspace('domain demo {}');
  const newer = mutateWorkspace(initial, {
    type: 'update',
    path: 'main.mdl',
    content: 'domain newer {}',
  });

  await repository.save(newer);
  await expect(repository.save(initial)).resolves.toBe('stale');
  await expect(repository.load('local')).resolves.toEqual({
    status: 'ready',
    workspace: newer,
  });
});

test('returns invalid raw state without overwriting it', async () => {
  await putRawRecord(repository, {
    id: 'local',
    schemaVersion: 1,
    revision: 2,
    files: [{ path: '../escape.mdl', content: 'secret', version: 1 }],
    activeFile: '../escape.mdl',
  });

  const result = await repository.load('local');
  expect(result).toMatchObject({
    status: 'recovery-required',
    reason: 'invalid',
  });
  expect(await readRawRecord(repository, 'local')).toEqual(
    result.status === 'recovery-required' ? result.raw : undefined,
  );
});
```

Expose test-only raw helpers from the test module by opening the same injected
database, not from production exports.

- [ ] **Step 6: Implement conditional saves in one read-write transaction**

Within one `readwrite` transaction:

1. get the current record;
2. if its numeric revision is greater than the incoming revision, complete
   without a put and return `stale`;
3. otherwise put `structuredClone(workspace)`; and
4. resolve `saved` only after transaction completion.

Do not use timestamps for ordering.

- [ ] **Step 7: Run repository, type, and dependency checks**

Run:

```bash
cd web
npx vitest run src/workspace.test.ts src/workspace-repository.test.ts
npm run check
npm audit --omit=dev
```

Expected: tests and type checks PASS; production dependency audit introduces no
new finding because `fake-indexeddb` is development-only.

- [ ] **Step 8: Run the mandatory pre-commit gate and commit**

Run:

```bash
cd cli
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
cd ..
git add web/package.json web/package-lock.json web/src/workspace-repository.ts web/src/workspace-repository.test.ts
git commit -m "feat: persist playground workspaces"
```

Expected: all gates pass and the repository implementation is independently
reviewable.

---

### Task 3: Give Monaco Stable Multi-file Model Ownership

**Files:**
- Create: `web/src/editor/SourceModelRegistry.ts`
- Create: `web/src/editor/SourceModelRegistry.test.ts`
- Modify: `web/src/editor/SourceEditor.tsx`
- Modify: `web/src/editor/types.ts`
- Modify: `web/src/diagnostics.ts`
- Modify: `web/src/diagnostics.test.ts`

**Interfaces:**
- Consumes: `PlaygroundFile[]`, active normalized path, per-URI diagnostics.
- Produces:

```ts
export interface SourceModelRegistry {
  reconcile(files: PlaygroundFile[]): void;
  model(path: string): editor.ITextModel | undefined;
  paths(): string[];
  dispose(): void;
}

export interface SourceModelApi {
  createModel(content: string, uri: string): editor.ITextModel;
}

export function createSourceModelRegistry(
  api: SourceModelApi,
): SourceModelRegistry;

export interface SourceEditorProps {
  files: PlaygroundFile[];
  activeFile: string;
  markersByUri: ReadonlyMap<string, editor.IMarkerData[]>;
  onContentChange(path: string, content: string): void;
}

export interface SourceEditorHandle {
  applyFormattedText(path: string, text: string): void;
  focus(): void;
}
```

- Unaffected file models retain identity across reconciliation.
- Removed or renamed old-path models are disposed.
- The active model's in-memory view state is restored when switching back
  during the same page session.

- [ ] **Step 1: Write failing model-registry tests**

```ts
test('reconciles models without recreating unaffected files', () => {
  const api = fakeMonacoModelApi();
  const registry = createSourceModelRegistry(api);
  registry.reconcile([
    { path: 'a.mdl', content: 'domain a {}', version: 1 },
    { path: 'b.mdl', content: 'domain b {}', version: 1 },
  ]);
  const firstA = registry.model('a.mdl');

  registry.reconcile([
    { path: 'a.mdl', content: 'domain a {}', version: 1 },
    { path: 'c.mdl', content: 'domain b {}', version: 2 },
  ]);

  expect(registry.model('a.mdl')).toBe(firstA);
  expect(api.model('b.mdl')?.disposed).toBe(true);
  expect(registry.paths()).toEqual(['a.mdl', 'c.mdl']);
});

test('updates external content without reporting it as a user edit', () => {
  const api = fakeMonacoModelApi();
  const registry = createSourceModelRegistry(api);
  registry.reconcile([
    { path: 'main.mdl', content: 'domain old {}', version: 1 },
  ]);
  registry.reconcile([
    { path: 'main.mdl', content: 'domain formatted {}', version: 2 },
  ]);
  expect(registry.model('main.mdl')?.getValue()).toBe(
    'domain formatted {}',
  );
});
```

- [ ] **Step 2: Run the registry tests and verify RED**

Run:

```bash
cd web
npx vitest run src/editor/SourceModelRegistry.test.ts
```

Expected: FAIL because the registry does not exist.

- [ ] **Step 3: Implement the focused registry**

Store `{ model, version }` by normalized path. Reconcile in sorted path order.
When incoming version differs and content differs, call `model.setValue()`
under a registry-owned suppression flag so React does not receive a false user
edit. Dispose removed models and all models on registry disposal.

- [ ] **Step 4: Write failing editor-switch and diagnostic-routing tests**

Mock the registry in `SourceEditor` tests and assert:

```ts
test('switches active models and restores in-session view state', () => {
  const { editor, rerender } = renderSourceEditor({
    files: twoFiles,
    activeFile: 'a.mdl',
  });
  editor.setViewState({ position: { lineNumber: 3, column: 2 } });

  rerender({ files: twoFiles, activeFile: 'b.mdl' });
  rerender({ files: twoFiles, activeFile: 'a.mdl' });

  expect(editor.restoreViewState).toHaveBeenCalledWith(
    expect.objectContaining({ position: { lineNumber: 3, column: 2 } }),
  );
});

test('routes markers to every matching file model', () => {
  const result = normalizeDiagnosticsByUri(diagnostics, [
    'file:///a.mdl',
    'file:///b.mdl',
  ]);
  expect(result.get('file:///a.mdl')).toHaveLength(1);
  expect(result.get('file:///b.mdl')).toHaveLength(2);
});
```

- [ ] **Step 5: Adapt `SourceEditor` and diagnostics**

`SourceEditor` creates one standalone editor and one registry. On active-file
change:

1. save the old model's view state;
2. call `editor.setModel(registry.model(activeFile))`;
3. restore the saved state for the new model, when present; and
4. focus only when the caller requests it.

Register one content listener per model and invoke
`onContentChange(path, model.getValue())` only for user-originated changes.
Apply markers for every URI, clearing markers when a URI no longer has
diagnostics. `applyFormattedText(path, text)` must select the named model and
use the editor's `pushUndoStop()` plus `executeEdits()` sequence; it must not
call `setValue()`, so formatting remains one undoable editor action.

- [ ] **Step 6: Run editor and diagnostics checks**

Run:

```bash
cd web
npx vitest run src/editor/SourceModelRegistry.test.ts src/diagnostics.test.ts src/App.test.tsx
npm run check
```

Expected: selected tests and TypeScript checks PASS; existing single-file App
tests remain green through the default one-file props.

- [ ] **Step 7: Run the mandatory pre-commit gate and commit**

Run:

```bash
cd cli
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
cd ..
git add web/src/editor/SourceModelRegistry.ts web/src/editor/SourceModelRegistry.test.ts web/src/editor/SourceEditor.tsx web/src/editor/types.ts web/src/diagnostics.ts web/src/diagnostics.test.ts
git commit -m "feat: manage playground source models"
```

Expected: all gates pass and Task 3 contains no persistence or file-list UI.

---

### Task 4: Run Compiler Operations Against the Whole Workspace

**Files:**
- Modify: `web/src/app-state.ts`
- Modify: `web/src/app-state.test.ts`
- Modify: `web/src/App.tsx`
- Modify: `web/src/App.test.tsx`
- Modify: `web/src/client.test.ts`

**Interfaces:**
- Consumes: workspace mutations and `workspaceSources()` from Task 1; multi-file
  `SourceEditor` from Task 3.
- Produces:

```ts
export type WorkspaceAppState = Omit<AppState, 'revision'> & {
  workspace: PlaygroundWorkspace;
};

export type WorkspaceAppAction =
  | AppAction
  | { type: 'workspaceReplaced'; workspace: PlaygroundWorkspace }
  | { type: 'workspaceMutated'; mutation: WorkspaceMutation };

export interface AppProps {
  createClient?: () => BrowserCompilerClientLike;
  initialWorkspace?: PlaygroundWorkspace;
  now?: () => number;
  confirmReplace?: (message: string) => boolean;
  download?: typeof downloadText;
}
```

- Validation and generation capture `workspace.revision` and pass all sorted
  sources.
- Formatting captures the active path and version, calls `formatSource()` with
  that source only, and applies the replacement only when that file and
  workspace revision remain current.

- [ ] **Step 1: Write failing reducer tests for workspace-derived invalidation**

```ts
test('workspace edits invalidate diagnostics and artifacts', () => {
  const state = {
    ...readyState,
    workspace: twoFileWorkspace,
    diagnostics: [diagnostic],
    artifacts: [artifact],
    artifactRevision: twoFileWorkspace.revision,
  };

  const next = workspaceAppReducer(state, {
    type: 'workspaceMutated',
    mutation: {
      type: 'update',
      path: 'customer.mdl',
      content: 'domain customer { entity Customer@1 {} }',
    },
  });

  expect(next.workspace.revision).toBe(twoFileWorkspace.revision + 1);
  expect(next.diagnostics).toEqual([]);
  expect(next.artifacts).toEqual([]);
  expect(next.artifactRevision).toBeNull();
});
```

- [ ] **Step 2: Run reducer tests and verify RED**

Run:

```bash
cd web
npx vitest run src/app-state.test.ts
```

Expected: FAIL because the reducer has no workspace actions.

- [ ] **Step 3: Add workspace state without weakening stale-result guards**

Replace the standalone numeric source revision with
`state.workspace.revision`. Every workspace mutation clears diagnostics and
artifacts. Operation success updates derived results only when the captured
revision equals `state.workspace.revision`.

- [ ] **Step 4: Write failing whole-workspace App tests**

```ts
test('validation and generation send every file in path order', async () => {
  const client = new DeferredClient();
  render(<App createClient={() => client} initialWorkspace={twoFileWorkspace} />);
  await initialize(client);

  await user.click(screen.getByRole('button', { name: 'Validate' }));
  expect(client.workspaceRequests.at(-1)?.sources).toEqual([
    { uri: 'file:///a.mdl', text: 'domain a {}', version: 1 },
    { uri: 'file:///z.mdl', text: 'domain z {}', version: 1 },
  ]);

  await user.click(screen.getByRole('button', { name: 'Generate' }));
  expect(client.compileRequests.at(-1)?.sources).toEqual(
    client.workspaceRequests.at(-1)?.sources,
  );
});

test('formatting changes only the still-current active file', async () => {
  const client = new DeferredClient();
  render(<App createClient={() => client} initialWorkspace={twoFileWorkspace} />);
  await initialize(client);

  await user.click(screen.getByRole('button', { name: 'Format' }));
  selectFile('z.mdl');
  client.formatRequests[0].resolve({
    diagnostics: [],
    replacement_text: 'domain formatted_a {}',
  });

  expect(source('a.mdl')).toBe('domain a {}');
  expect(source('z.mdl')).toBe('domain z {}');
});
```

- [ ] **Step 5: Adapt `App` to workspace snapshots**

Add an injectable `initialWorkspace` only for tests; production uses the
default workspace until Task 6 adds restoration. Remove `SOURCE_URI`,
`sourceFilenameRef`, and single-source reads. Pass workspace files and active
path to `SourceEditor`.

On Monaco content change, dispatch:

```ts
{
  type: 'workspaceMutated',
  mutation: { type: 'update', path, content },
}
```

Capture source arrays before starting validate/generate. For format, capture
the active file path, version, and workspace revision and ignore a replacement
when any of those values changed before completion.

- [ ] **Step 6: Run App, client, and browser protocol tests**

Run:

```bash
cd web
npx vitest run src/app-state.test.ts src/App.test.tsx src/client.test.ts src/protocol.test.ts
npm run check
```

Expected: all selected tests and type checks PASS.

- [ ] **Step 7: Run the mandatory pre-commit gate and commit**

Run:

```bash
cd cli
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
cd ..
git add web/src/app-state.ts web/src/app-state.test.ts web/src/App.tsx web/src/App.test.tsx web/src/client.test.ts
git commit -m "feat: compile playground workspaces"
```

Expected: all gates pass and the default one-file workflow remains functional.

---

### Task 5: Add Accessible File Lifecycle UI

**Files:**
- Create: `web/src/WorkspaceFiles.tsx`
- Create: `web/src/WorkspaceFiles.test.tsx`
- Modify: `web/src/files.ts`
- Modify: `web/src/files.test.ts`
- Modify: `web/src/App.tsx`
- Modify: `web/src/App.test.tsx`
- Modify: `web/src/style.css`

**Interfaces:**
- Consumes: `PlaygroundWorkspace`, `WorkspaceMutation`, and App dispatch from
  Tasks 1 and 4.
- Produces:

```ts
export interface WorkspaceFilesProps {
  workspace: PlaygroundWorkspace;
  disabled: boolean;
  onCreate(path: string): void;
  onImport(files: ImportedWorkspaceFile[]): void;
  onRename(path: string): void;
  onDelete(): void;
  onSelect(path: string): void;
}

export interface ImportedWorkspaceFile {
  path: string;
  content: string;
}

export function readWorkspaceFiles(
  files: FileList | File[],
): Promise<ImportedWorkspaceFile[]>;
```

- Imports accept `.mdl` files of at most 1 MiB each.
- Duplicate imports require confirmation per conflicting path before the
  workspace mutation.

- [ ] **Step 1: Write failing file-reading tests**

```ts
test('reads multiple mdl files in deterministic name order', async () => {
  const files = [
    new File(['domain z {}'], 'z.mdl', { type: 'text/plain' }),
    new File(['domain a {}'], 'a.mdl', { type: 'text/plain' }),
  ];
  await expect(readWorkspaceFiles(files)).resolves.toEqual([
    { path: 'a.mdl', content: 'domain a {}' },
    { path: 'z.mdl', content: 'domain z {}' },
  ]);
});

test('rejects non-mdl, oversized, and duplicate normalized names', async () => {
  await expect(
    readWorkspaceFiles([new File(['x'], 'source.txt')]),
  ).rejects.toThrow('Choose .mdl workspace files');
  await expect(
    readWorkspaceFiles([
      new File([new Uint8Array(1024 * 1024 + 1)], 'large.mdl'),
    ]),
  ).rejects.toThrow('Workspace files must be 1 MiB or smaller');
});
```

- [ ] **Step 2: Run file tests and verify RED**

Run:

```bash
cd web
npx vitest run src/files.test.ts
```

Expected: FAIL because `readWorkspaceFiles()` does not exist.

- [ ] **Step 3: Implement safe multi-file reads**

Use `normalizeWorkspacePath(file.name)`, reject duplicates before reading
contents, read with `File.text()`, and sort results by normalized path. Do not
use `innerHTML`, object URLs, or file-system paths.

- [ ] **Step 4: Write failing accessible file-list tests**

```tsx
test('selects, creates, renames, and deletes workspace files', async () => {
  const handlers = workspaceHandlers();
  render(
    <WorkspaceFiles
      workspace={twoFileWorkspace}
      disabled={false}
      {...handlers}
    />,
  );

  await user.click(screen.getByRole('button', { name: 'a.mdl' }));
  expect(handlers.onSelect).toHaveBeenCalledWith('a.mdl');

  await user.type(screen.getByLabelText('Workspace file path'), 'new.mdl');
  await user.click(screen.getByRole('button', { name: 'New file' }));
  expect(handlers.onCreate).toHaveBeenCalledWith('new.mdl');

  expect(screen.getByRole('list', { name: 'Workspace files' })).toBeVisible();
  expect(screen.getByText('Active file')).toBeVisible();
});
```

Add tests that disabled controls do not dispatch, delete requires the injected
confirmation, invalid paths produce textual errors, and duplicate import
replacement affects only confirmed files.

- [ ] **Step 5: Implement `WorkspaceFiles` and App mutations**

Render the files as a semantic list of buttons, with `aria-current="true"` on
the active file. Use one labeled path input for create and rename. Add a hidden
`<input type="file" accept=".mdl" multiple>` activated by **Import files**.

App handlers convert successful actions to exact domain mutations. Apply
multi-file import as one reducer action that validates every path and
confirmation before replacing the workspace, so a later invalid file cannot
leave earlier imports applied.

- [ ] **Step 6: Add responsive workspace navigation styles**

Keep the existing bounded page-height behavior. On wide screens, render a
narrow file rail beside the source editor; on narrow screens, render a
horizontally scrollable file list above the editor without page-level
horizontal overflow. Preserve visible focus indicators and minimum target
sizes.

- [ ] **Step 7: Run file UI and accessibility-focused tests**

Run:

```bash
cd web
npx vitest run src/files.test.ts src/WorkspaceFiles.test.tsx src/App.test.tsx
npm run check
```

Expected: all selected tests and type checks PASS.

- [ ] **Step 8: Run the mandatory pre-commit gate and commit**

Run:

```bash
cd cli
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
cd ..
git add web/src/WorkspaceFiles.tsx web/src/WorkspaceFiles.test.tsx web/src/files.ts web/src/files.test.ts web/src/App.tsx web/src/App.test.tsx web/src/style.css
git commit -m "feat: manage playground workspace files"
```

Expected: all gates pass and Task 5 does not persist or restore state yet.

---

### Task 6: Integrate Restoration, Autosave, and Recovery

**Files:**
- Create: `web/src/usePersistentWorkspace.ts`
- Create: `web/src/usePersistentWorkspace.test.tsx`
- Create: `web/src/WorkspaceRecovery.tsx`
- Create: `web/src/WorkspaceRecovery.test.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/App.test.tsx`
- Modify: `web/src/files.ts`
- Modify: `web/src/files.test.ts`
- Modify: `web/src/style.css`

**Interfaces:**
- Consumes: `WorkspaceRepository` from Task 2 and workspace snapshots from
  Task 1.
- Produces:

```ts
export type PersistencePhase =
  | 'restoring'
  | 'saved'
  | 'saving'
  | 'memory-only'
  | 'recovery-required';

export interface PersistentWorkspaceState {
  workspace: PlaygroundWorkspace;
  phase: PersistencePhase;
  recovery:
    | {
        reason: 'invalid' | 'incompatible';
        raw: unknown;
    }
    | null;
  replace(
    workspace: PlaygroundWorkspace,
    options?: { immediate?: boolean },
  ): void;
  retry(): Promise<void>;
  reset(): Promise<void>;
}

export function usePersistentWorkspace(options: {
  repository: WorkspaceRepository;
  defaultWorkspace: PlaygroundWorkspace;
  debounceMs?: number;
}): PersistentWorkspaceState;

export function downloadRecoveryData(
  raw: unknown,
  download?: DownloadText,
): void;
```

- Production debounce: 300 ms.
- Tests use fake timers and an injected repository.

- [ ] **Step 1: Write failing restore and save-order hook tests**

```tsx
test('restores before exposing a workspace to the application', async () => {
  const repository = deferredRepository();
  const { result } = renderHook(() =>
    usePersistentWorkspace({
      repository,
      defaultWorkspace,
      debounceMs: 10,
    }),
  );
  expect(result.current.phase).toBe('restoring');

  repository.loadRequest.resolve({
    status: 'ready',
    workspace: restoredWorkspace,
  });
  await waitFor(() => expect(result.current.phase).toBe('saved'));
  expect(result.current.workspace).toEqual(restoredWorkspace);
});

test('an older save completion cannot mark newer state saved', async () => {
  vi.useFakeTimers();
  const repository = deferredRepository();
  const { result } = renderHook(() =>
    usePersistentWorkspace({
      repository,
      defaultWorkspace,
      debounceMs: 10,
    }),
  );
  repository.loadRequest.resolve({ status: 'missing' });
  await act(() => vi.runAllTimersAsync());

  act(() => result.current.replace(revision2));
  await act(() => vi.advanceTimersByTimeAsync(10));
  act(() => result.current.replace(revision3));
  await act(() => vi.advanceTimersByTimeAsync(10));
  repository.saveRequests[0].resolve('saved');
  expect(result.current.phase).toBe('saving');
  repository.saveRequests[1].resolve('saved');
  await waitFor(() => expect(result.current.phase).toBe('saved'));
});
```

- [ ] **Step 2: Run hook tests and verify RED**

Run:

```bash
cd web
npx vitest run src/usePersistentWorkspace.test.tsx
```

Expected: FAIL because the hook does not exist.

- [ ] **Step 3: Implement restoration and debounced persistence**

Use refs for the current workspace revision, pending timer, and mounted state.
Load exactly once per repository instance. `replace()` updates in-memory state
immediately, sets `saving`, and schedules a save. An immediate structural
mutation cancels the debounce and starts its save without delay.

When load returns `missing`, expose the default workspace and immediately save
it. When load returns `ready`, expose the restored workspace without rewriting
it. When load returns `recovery-required`, retain the raw record and do not
save. Treat repository rejection as `memory-only` without clearing the workspace.
`pagehide` starts a best-effort save only when unsaved state exists; it must
not register a new unload prompt or assume the promise will settle.

- [ ] **Step 4: Write failing recovery and reset tests**

```tsx
test('invalid stored state remains exportable until explicit reset', async () => {
  const raw = { schemaVersion: 99, secretLookingSource: '<script>x</script>' };
  const repository = resolvedRepository({
    status: 'recovery-required',
    reason: 'incompatible',
    raw,
  });
  const { result } = renderHook(() =>
    usePersistentWorkspace({ repository, defaultWorkspace }),
  );

  await waitFor(() =>
    expect(result.current.phase).toBe('recovery-required'),
  );
  expect(result.current.recovery?.raw).toBe(raw);
  expect(repository.save).not.toHaveBeenCalled();

  await act(() => result.current.reset());
  expect(repository.remove).toHaveBeenCalledWith('local');
  expect(result.current.workspace).toEqual(defaultWorkspace);
});

test('retry never replaces newer in-memory work with older storage', async () => {
  const repository = unavailableThenReadyRepository(restoredWorkspace);
  const { result } = renderHook(() =>
    usePersistentWorkspace({ repository, defaultWorkspace }),
  );
  await waitFor(() => expect(result.current.phase).toBe('memory-only'));
  act(() => result.current.replace(editedDefaultWorkspace));

  await act(() => result.current.retry());
  expect(result.current.workspace).toEqual(editedDefaultWorkspace);
  expect(repository.save).toHaveBeenCalledWith(editedDefaultWorkspace);
});
```

- [ ] **Step 5: Implement recovery UI and explicit recovery download**

`WorkspaceRecovery` renders:

- the reason without raw source;
- **Export recovery data**;
- **Reset local workspace**; and
- **Retry storage**.

`downloadRecoveryData()` serializes with `JSON.stringify(raw, null, 2)` and
passes it to the existing text-download helper as
`modelable-playground-recovery.json` with `application/json`. Never render raw
JSON into the page.

- [ ] **Step 6: Integrate persistence into App startup and file operations**

Add:

```ts
export interface AppProps {
  createClient?: () => BrowserCompilerClientLike;
  createRepository?: () => WorkspaceRepository;
  now?: () => number;
  confirmReplace?: (message: string) => boolean;
  download?: typeof downloadText;
}
```

Remove Task 4's test-only `initialWorkspace` prop and migrate those tests to an
injected repository that resolves to the requested workspace. Production and
tests then exercise the same restoration boundary.

The Pyodide runtime may initialize while storage restores, but do not call
`openWorkspace()` or any source-dependent compiler operation until persistence
leaves `restoring`. Open restored/default sources exactly once per client
attempt. Pass `{ immediate: true }` for create/import/rename/delete and use
debounced persistence for editor content updates and active-file selection.

Show persistence status in an `aria-live="polite"` region. In `memory-only`,
keep all editor and compiler actions usable and offer **Retry storage**.

- [ ] **Step 7: Run persistence and App integration tests**

Run:

```bash
cd web
npx vitest run src/workspace-repository.test.ts src/usePersistentWorkspace.test.tsx src/WorkspaceRecovery.test.tsx src/App.test.tsx src/files.test.ts
npm run check
```

Expected: all selected tests and type checks PASS.

- [ ] **Step 8: Run the mandatory pre-commit gate and commit**

Run:

```bash
cd cli
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
cd ..
git add web/src/usePersistentWorkspace.ts web/src/usePersistentWorkspace.test.tsx web/src/WorkspaceRecovery.tsx web/src/WorkspaceRecovery.test.tsx web/src/App.tsx web/src/App.test.tsx web/src/files.ts web/src/files.test.ts web/src/style.css
git commit -m "feat: restore playground workspaces"
```

Expected: all gates pass and Task 6 completes the product behavior from the
accepted spec.

---

### Task 7: Add Browser Acceptance, Documentation, and Archive Bookkeeping

**Files:**
- Modify: `web/tests/playground.spec.ts`
- Modify: `web/tests/conformance.spec.ts`
- Modify: `web/src/budgets.test.ts`
- Modify: `docs/playground-design.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `ROADMAP.md`
- Move: `docs/superpowers/specs/2026-07-20-playground-workspace-persistence-design.md` → `docs/superpowers/specs/archived/2026-07-20-playground-workspace-persistence-design.md`
- Move: `docs/superpowers/plans/2026-07-20-playground-workspace-persistence.md` → `docs/superpowers/plans/archived/2026-07-20-playground-workspace-persistence.md`
- Modify: links affected by the archive moves.

**Interfaces:**
- Consumes: complete Phase 3a behavior from Tasks 1–6.
- Produces: deployed acceptance coverage, truthful public docs, Priority 1
  advancement to Phase 3b, and no completed active plan/spec residue.

- [ ] **Step 1: Write failing browser tests for multi-file compilation**

```ts
test('creates a second file and compiles the complete workspace', async ({
  page,
}) => {
  await openReadyPlayground(page);
  await page.getByLabel('Workspace file path').fill('customer.mdl');
  await page.getByRole('button', { name: 'New file' }).click();
  await replaceEditorText(page, 'domain customer { entity Customer@1 {} }');
  await page.getByRole('button', { name: 'main.mdl' }).click();
  await replaceEditorText(
    page,
    'domain sales { projection CustomerView@1 from customer.Customer@1 {} }',
  );

  await page.getByRole('button', { name: 'Validate' }).click();
  await expect(page.getByText('Validation complete')).toBeVisible();
  await expect(page.getByText('0 errors')).toBeVisible();
});
```

Add a compiler test hook only when `?test=1` is present and use it to assert
the exact sorted source URIs. Do not expose repository internals in production.

- [ ] **Step 2: Write failing reload and recovery browser tests**

```ts
test('restores exact files and active selection after reload', async ({
  page,
}) => {
  await openReadyPlayground(page);
  await createWorkspaceFile(page, 'customer.mdl', 'domain customer {}');
  await expect(page.getByText('Saved locally')).toBeVisible();

  await page.reload();
  await expect(page.getByRole('button', { name: 'customer.mdl' }))
    .toHaveAttribute('aria-current', 'true');
  await expectEditorText(page, 'domain customer {}');
});

test('exports and resets an incompatible stored record', async ({ page }) => {
  await seedIndexedDb(page, {
    schemaVersion: 99,
    id: 'local',
    source: '<script>not markup</script>',
  });
  await page.reload();
  await expect(page.getByText('Stored workspace needs recovery')).toBeVisible();
  await page.getByRole('button', { name: 'Reset local workspace' }).click();
  await expect(page.getByRole('button', { name: 'main.mdl' })).toBeVisible();
});
```

Add cases for storage-unavailable fallback, rename/delete persistence, and
duplicate import confirmation.

- [ ] **Step 3: Run browser tests and verify RED**

Run:

```bash
cd web
npm run build
npx playwright test tests/playground.spec.ts
```

Expected: new tests FAIL until all UI selectors, persistence waits, and test
helpers reflect the completed implementation.

- [ ] **Step 4: Complete browser helpers and conformance coverage**

Use Playwright's `page.evaluate()` only to seed IndexedDB or inspect the
explicit `?test=1` compiler hook. User-visible actions must go through the UI.
Extend native/browser conformance with a two-file fixture that contains a
cross-file reference and compare diagnostics plus JSON Schema artifacts.

Keep median initialization and operation budgets unchanged unless measured
evidence and an explicit roadmap decision justify a new value.

- [ ] **Step 5: Update docs and roadmap truth**

Document:

- multi-file create/import/rename/delete/select workflows;
- automatic local persistence and what is not stored;
- storage recovery/export/reset;
- whole-workspace validation and generation;
- the one-workspace, `.mdl`-only, no-language-services Phase 3a boundary; and
- local-only privacy behavior.

In `ROADMAP.md`, mark Phase 3a shipped and make Phase 3b browser-native
language services the active next slice. In `docs/playground-design.md`, mark
Phase 3a shipped without marking all of Phase 3 complete.

State explicitly that no ADR changed because implementation follows the
accepted Playground architecture and introduces no new deployment or security
boundary.

- [ ] **Step 6: Archive the completed spec and plan**

Run:

```bash
git mv docs/superpowers/specs/2026-07-20-playground-workspace-persistence-design.md docs/superpowers/specs/archived/2026-07-20-playground-workspace-persistence-design.md
git mv docs/superpowers/plans/2026-07-20-playground-workspace-persistence.md docs/superpowers/plans/archived/2026-07-20-playground-workspace-persistence.md
```

Update the plan-to-spec link, roadmap link, and any public docs to the archived
paths. Verify no active copies remain.

- [ ] **Step 7: Run all web, browser, and documentation gates**

Run:

```bash
cd web
npm run check
npm test
npm run build
npm run test:e2e
npm run check:budgets
cd ..
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
git diff --check
```

Expected:

- TypeScript check passes;
- all web unit/component tests pass;
- production build passes;
- all Playwright tests pass;
- size and performance budgets pass;
- strict MkDocs passes; and
- diff check reports no whitespace errors.

- [ ] **Step 8: Run the mandatory CLI gate**

Run:

```bash
cd cli
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Expected: all four commands pass cleanly.

- [ ] **Step 9: Run the repository browser gate**

Run:

```bash
cd ..
uv run python .github/scripts/run_browser_playground.py --skip-install
```

Expected: CLI, web unit tests, production build, Playwright acceptance, and
bundle budgets all pass from the repository-owned orchestration script.

- [ ] **Step 10: Run the mandatory four-phase doc/spec review**

Review every changed document for:

1. valid Markdown and no placeholders;
2. valid and consistent spec/plan/roadmap links;
3. complete architecture, security, roadmap, changelog, and user coverage with
   the no-ADR rationale; and
4. no contradiction about Phase 3a being shipped while Phase 3b and later
   phases remain active.

Expected report:

```text
Doc/spec review: all phases passed
Warnings: 0
Blockers: 0
```

- [ ] **Step 11: Commit the acceptance and archive closeout**

Run:

```bash
git add README.md CHANGELOG.md ROADMAP.md docs/playground-design.md docs/superpowers/specs docs/superpowers/plans web/tests/playground.spec.ts web/tests/conformance.spec.ts web/src/budgets.test.ts
git commit -m "docs: ship playground workspace persistence"
```

Expected: the implementation branch is clean, Phase 3a's spec and plan are
archived, and Phase 3b is the only active Playground delivery slice named by
the roadmap.

---

## Final Verification

After Task 7, review the complete implementation range against
`docs/superpowers/specs/archived/2026-07-20-playground-workspace-persistence-design.md`.
Require an independent reviewer to inspect cross-task invariants:

- workspace path normalization matches Monaco URI and persistence keys;
- every mutation produces monotonic versions and atomic multi-file imports;
- compiler requests use the exact current sorted workspace;
- stale compiler and save completions cannot replace newer state;
- restoration happens before the compiler opens a workspace;
- corrupt state remains exportable until explicit reset;
- memory-only fallback does not claim persistence;
- model disposal cannot leak removed source contents;
- no raw source appears in logs or markup;
- CSP, accessibility, bounded layout, browser conformance, and budgets remain
  green; and
- the active spec/plan are archived only after all implementation tasks pass.

Any Critical or Important finding requires a focused RED/GREEN correction and
a fresh full-gate run before publication.
