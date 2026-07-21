# Playground Visualization MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add compiler-owned semantic graph export to the browser compiler
protocol, ELK-based layout in a web worker, React Flow rendering with domain
and entity visualization modes, and bidirectional editor–graph navigation.

**Architecture:** Adapt the existing Python `build_graph_export` to produce a
browser-compatible graph DTO, expose it through a `workspace.graph` protocol
method, lay out with ELK.js in a dedicated worker, render with React Flow,
and synchronize selection between editor and graph. Batch A ships the protocol
and graph data pipeline; Batch B ships layout, rendering, and integration.

**Tech Stack:** Python 3.11+, dataclasses, Modelable graph/compiler workspace,
Pyodide worker RPC, TypeScript, React, React Flow (`@xyflow/react`), ELK.js,
Monaco Editor, Vitest, pytest, and Playwright.

**Design:**
[Playground Visualization MVP — Design](../specs/2026-07-21-playground-visualization-design.md)

## Global Constraints

- `modelable.graph` must not import browser-specific modules.
- Browser graph processing remains local and same-origin; no external
  requests are allowed.
- Graph DTOs are derived state — never persisted in IndexedDB.
- Graph data crosses the Pyodide structured-clone boundary with the same
  validation as existing protocol results.
- Source ranges use 0-based line/character coordinates consistent with the
  browser language protocol.
- ELK layout must execute in a separate web worker.
- Before every commit, run from `cli/`, in order:
  `uv run ruff format .`, `uv run ruff check .`,
  `uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes`,
  and `uv run pytest --tb=short`.
- Follow red-green-refactor for every behavior change and keep Batch A
  independently releasable before starting Batch B.

---

## File and interface map

### Python browser graph adapter

- Create `cli/src/modelable/browser/graph.py` — adapter that calls
  `build_graph_export` and converts to browser DTOs, applying mode filtering
  and source range attachment.
- Extend `cli/src/modelable/browser/dto.py` — add `BrowserGraphNode`,
  `BrowserGraphEdge`, `BrowserGraph`, `BrowserGraphResult`,
  `BrowserSourceRange` dataclasses.
- Extend `cli/src/modelable/browser/dispatch.py` — add `workspace.graph` to
  `_METHODS`, add dispatch branch, add serialization.
- Extend `cli/src/modelable/browser/api.py` — add `graph()` method on
  `BrowserCompiler`.

### TypeScript protocol and client

- Extend `web/src/protocol.ts` — add `workspace.graph` to
  `BrowserCompilerMethod`, add `BrowserGraphResult`, `ModelGraph`,
  `ModelGraphNode`, `ModelGraphEdge`, `SourceRange` types and type guards.
- Extend `web/src/client.ts` — add `graph(workspaceRevision, mode)` method on
  `BrowserCompilerClient`, extend `BrowserCompilerClientLike`.

### TypeScript visualization layer (new)

- Create `web/src/visualization/GraphPanel.tsx` — main panel component with
  mode tabs and React Flow canvas.
- Create `web/src/visualization/nodes/` — custom React Flow node components
  (`DomainNode.tsx`, `EntityNode.tsx`, `VersionNode.tsx`, `FieldNode.tsx`,
  `ProjectionNode.tsx`).
- Create `web/src/visualization/edges/` — custom edge components
  (`ContainsEdge.tsx`, `DependsOnEdge.tsx`, `ProjectsEdge.tsx`).
- Create `web/src/visualization/layout.worker.ts` — ELK layout web worker.
- Create `web/src/visualization/useGraphLayout.ts` — React hook coordinating
  layout requests and stale-response filtering.
- Create `web/src/visualization/useGraphSync.ts` — React hook for
  editor↔graph selection synchronization.
- Create `web/src/visualization/graph-types.ts` — shared TypeScript types for
  layout and rendering (positioned nodes, edge routes).

### Tests

- Create `cli/tests/test_browser_graph.py` — Python browser graph adapter
  tests.
- Extend `web/src/protocol.test.ts` — type guard tests for graph results.
- Extend `web/src/client.test.ts` — graph method dispatch test.
- Create `web/src/visualization/GraphPanel.test.tsx` — unit tests for graph
  panel rendering and interaction.
- Extend `web/tests/conformance.spec.ts` — browser graph conformance and
  budget tests.
- Extend `web/tests/playground.spec.ts` — graph panel integration tests.

---

## Batch A — Protocol and graph data

### Task 1: Python browser graph DTO and adapter

**Files:** `cli/src/modelable/browser/dto.py`,
`cli/src/modelable/browser/graph.py`

- [ ] Add `BrowserSourceRange`, `BrowserGraphNode`, `BrowserGraphEdge`,
  `BrowserGraph`, `BrowserGraphResult` frozen dataclasses to `dto.py`.
- [ ] Create `graph.py` with `build_browser_graph(workspace, mode)` that:
  - calls `build_graph_export(workspace)`;
  - maps Python node kinds to browser DTO kinds (`model` → `entity`,
    `model_version`/`projection_version` → `version`,
    `projection_field` → `field`);
  - maps Python edge kinds to browser DTO edge kinds (`owns`/`version_of`/
    `contains_field`/`has_projection`/`version_of_projection` → `contains`,
    `maps_to` → `projects`);
  - generates deterministic edge IDs from `(kind, source, target)`;
  - attaches `source_range` from workspace IR span data when available;
  - filters by mode (`domain` excludes version/field nodes and their edges);
  - returns `BrowserGraphResult`.
- [ ] Write `cli/tests/test_browser_graph.py` covering both modes, kind
  mapping, source range attachment, edge ID determinism, and empty workspace.
- [ ] Run `ruff format`, `ruff check`, `mypy`, `pytest`.

### Task 2: Python dispatch and API wiring

**Files:** `cli/src/modelable/browser/dispatch.py`,
`cli/src/modelable/browser/api.py`

- [ ] Add `"workspace.graph"` to `_METHODS` in `dispatch.py`.
- [ ] Add `_GRAPH_MODES = {"domain", "entity"}` validation set.
- [ ] Add dispatch branch: validate `{workspaceRevision, mode}` payload,
  reject unknown modes, call `_compiler.graph(...)`.
- [ ] Add `BrowserGraphResult` to `_DispatchResult` union and
  `_serialize_result`.
- [ ] Add `graph(workspace_revision, mode)` method on `BrowserCompiler` in
  `api.py`: validate revision staleness, require semantic workspace, call
  `build_browser_graph`.
- [ ] Extend `cli/tests/test_browser_dispatch.py` with graph dispatch tests
  (valid request, stale revision, invalid mode, missing fields).
- [ ] Run lint/type/test gates.

### Task 3: TypeScript protocol types and client method

**Files:** `web/src/protocol.ts`, `web/src/client.ts`,
`web/src/protocol.test.ts`, `web/src/client.test.ts`, `web/src/App.test.tsx`

- [ ] Add `'workspace.graph'` to `BrowserCompilerMethod` union and `methods`
  set.
- [ ] Add TypeScript types: `SourceRange`, `ModelGraphNode`, `ModelGraphEdge`,
  `ModelGraph`, `BrowserGraphResult`.
- [ ] Add type guard `isBrowserGraphResult` with structural validation.
- [ ] Add `graph(workspaceRevision: number, mode: 'domain' | 'entity')`
  method on `BrowserCompilerClient`.
- [ ] Extend `BrowserCompilerClientLike` Pick type.
- [ ] Add `graph` to test fakes in `App.test.tsx` and any other test files
  that construct fake clients.
- [ ] Write protocol guard tests and client dispatch tests.
- [ ] Run `npm run check` and `npm test`.

### Task 4: Playwright conformance extension

**Files:** `web/tests/conformance.spec.ts`

- [ ] Extend `TestClient` type with `graph(workspaceRevision, mode)`.
- [ ] Add conformance test: call `workspace.graph` with both `"domain"` and
  `"entity"` modes on the single-valid fixture; verify result shape
  (`schema_version`, node/edge arrays, node kinds per mode).
- [ ] Add `workspace.graph` timing to the budget test for both modes.
- [ ] Add budget assertion: ≤ 200 ms median for `workspace.graph`.

---

## Batch B — Layout, rendering, and integration

### Task 5: Install dependencies and ELK layout worker

**Files:** `web/package.json`, `web/src/visualization/layout.worker.ts`,
`web/src/visualization/graph-types.ts`

- [ ] Install `@xyflow/react` and `elkjs` as production dependencies.
- [ ] Create `graph-types.ts` with positioned node/edge types for React Flow.
- [ ] Create `layout.worker.ts`: accept `LayoutRequest`, run ELK layout,
  return `LayoutResponse` with positioned nodes and edge routes.
- [ ] Write unit test for layout worker message protocol.
- [ ] Verify Vite builds the worker correctly.

### Task 6: React Flow node and edge components

**Files:** `web/src/visualization/nodes/*.tsx`,
`web/src/visualization/edges/*.tsx`

- [ ] Create `DomainNode`, `EntityNode`, `VersionNode`, `FieldNode`,
  `ProjectionNode` as custom React Flow node components.
- [ ] Create `ContainsEdge`, `DependsOnEdge`, `ProjectsEdge` as custom
  edge components.
- [ ] Style with CSS modules or inline styles matching the Playground theme
  (light/dark support via existing CSS custom properties).
- [ ] Write snapshot or structural render tests.

### Task 7: Graph panel with mode switching

**Files:** `web/src/visualization/GraphPanel.tsx`,
`web/src/visualization/useGraphLayout.ts`,
`web/src/visualization/GraphPanel.test.tsx`

- [ ] Create `useGraphLayout` hook: manage layout worker lifecycle, send
  layout requests, filter stale responses by graph revision.
- [ ] Create `GraphPanel`: accept graph data and mode, render React Flow
  canvas with minimap, mode tabs (Domain / Entity), loading/empty states.
- [ ] Wire into `App.tsx`: add graph panel to desktop layout (right of
  editor); request graph on workspace revalidation; pass graph result and
  mode to `GraphPanel`.
- [ ] Write unit tests for `GraphPanel` rendering with mock graph data.
- [ ] Verify mode switching triggers a new `workspace.graph` request.

### Task 8: Editor–graph bidirectional synchronization

**Files:** `web/src/visualization/useGraphSync.ts`, `web/src/App.tsx`

- [ ] Create `useGraphSync` hook:
  - **Graph → Editor**: on node click, find `source_range`, switch active file
    if needed, call `editor.revealRange()`.
  - **Editor → Graph**: on cursor position change, find matching graph node by
    `source_range`, highlight it, optionally pan into view.
- [ ] Wire synchronization into `App.tsx`.
- [ ] Write unit tests for selection matching logic.

### Task 9: Responsive layout and accessibility

**Files:** `web/src/App.tsx`, `web/src/style.css`,
`web/src/visualization/GraphPanel.tsx`

- [ ] Desktop (≥ 768px): resizable split between editor and graph panel.
- [ ] Mobile (< 768px): tabbed "Source" / "Graph" view.
- [ ] Graph panel collapse: unmount React Flow when hidden.
- [ ] Accessibility: keyboard-navigable nodes, screen-reader labels,
  non-color-only node kind indicators, `aria-hidden` minimap.
- [ ] Verify with existing axe-core Playwright tests.

### Task 10: Performance budgets and conformance

**Files:** `web/tests/conformance.spec.ts`, `web/tests/playground.spec.ts`

- [ ] Add Playwright integration test: graph panel renders nodes for default
  workspace, node click reveals source, mode switch works.
- [ ] Enforce performance budgets in budget test.
- [ ] Verify no off-origin requests from graph dependencies.

### Task 11: Documentation and Phase 4 closeout

- [ ] Update `docs/playground-design.md` status to mark Phase 4 shipped.
- [ ] Update `ROADMAP.md` to mark visualization MVP shipped, advance Phase 5.
- [ ] Update `CHANGELOG.md` with visualization entries.
- [ ] Archive this spec and plan to `archived/` directories.
- [ ] Fix any relative links broken by archive moves.
- [ ] Run complete release gate.
