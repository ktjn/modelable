# Playground Analysis Views Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add field lineage, compatibility, and governance analysis views to
the browser Playground, plus SVG/PNG diagram export for all visualization
modes.

**Architecture:** Wire the three existing Python analysis engines to the
browser compiler protocol as new methods, create browser DTOs, add TypeScript
protocol types and client methods, convert analysis results to React Flow
nodes and edges for rendering in the existing graph panel, and add SVG/PNG
export using React Flow's built-in viewport utilities.

**Tech Stack:** Python 3.11+, dataclasses, Modelable lineage/compat/governance
engines, Pyodide worker RPC, TypeScript, React, React Flow (`@xyflow/react`),
ELK.js, Vitest, pytest, and Playwright.

**Design:**
[Playground Analysis Views — Design](../../specs/2026-07-21-playground-analysis-views-design.md)

## Global Constraints

- `modelable.planner.lineage`, `modelable.compat`, and `modelable.governance`
  must not import browser-specific modules.
- Browser analysis processing remains local and same-origin; no external
  requests are allowed.
- Analysis results are derived state — never persisted in IndexedDB.
- Analysis data crosses the Pyodide structured-clone boundary with the same
  validation as existing protocol results.
- Reuse the existing ELK layout worker and React Flow infrastructure.
- Before every commit, run from `cli/`, in order:
  `uv run ruff format .`, `uv run ruff check .`,
  `uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes`,
  and `uv run pytest --tb=short`.
- Follow red-green-refactor for every behavior change.

---

## File and interface map

### Python browser analysis adapters

- Create `cli/src/modelable/browser/lineage.py` — adapter that calls
  `build_projection_lineage` for all projection versions and converts to
  browser DTOs.
- Create `cli/src/modelable/browser/compatibility.py` — adapter that calls
  `check_model_version_compatibility` for all consecutive version pairs,
  `find_projection_dependents` and `analyze_impact` for breaking reports,
  and converts to browser DTOs.
- Create `cli/src/modelable/browser/governance.py` — adapter that calls
  `build_projection_governance_findings` for all projection versions and
  converts to browser DTOs.
- Extend `cli/src/modelable/browser/dto.py` — add lineage, compatibility,
  and governance frozen dataclasses.
- Extend `cli/src/modelable/browser/dispatch.py` — add three new methods to
  `_METHODS`, add dispatch branches, add serialization.
- Extend `cli/src/modelable/browser/api.py` — add `lineage()`,
  `compatibility()`, and `governance()` methods on `BrowserCompiler`.

### TypeScript protocol and client

- Extend `web/src/protocol.ts` — add `workspace.lineage`,
  `workspace.compatibility`, `workspace.governance` to
  `BrowserCompilerMethod`, add result types and type guards.
- Extend `web/src/client.ts` — add `lineage()`, `compatibility()`,
  `governance()` methods on `BrowserCompilerClient`, extend
  `BrowserCompilerClientLike`.

### TypeScript visualization layer

- Create `web/src/visualization/LineageView.tsx` — converts lineage result to
  React Flow nodes/edges and renders field derivation chains.
- Create `web/src/visualization/CompatibilityView.tsx` — converts
  compatibility result to React Flow nodes/edges and renders version diffs.
- Create `web/src/visualization/GovernanceView.tsx` — converts governance
  result to React Flow nodes/edges and renders finding groups.
- Create `web/src/visualization/nodes/ChangeNode.tsx` — custom node for
  compatibility field changes.
- Create `web/src/visualization/nodes/FindingNode.tsx` — custom node for
  governance findings.
- Create `web/src/visualization/ExportControls.tsx` — SVG/PNG export buttons.
- Extend `web/src/visualization/GraphPanel.tsx` — add lineage, compatibility,
  governance mode tabs and export toolbar.
- Extend `web/src/visualization/GraphPanelContainer.tsx` — fetch analysis
  data for new modes.

### Conformance fixtures

- Create `cli/tests/conformance/browser/analysis-customer.mdl` and
  `cli/tests/conformance/browser/analysis-billing.mdl` — multi-file fixture
  with projections, multiple versions, PII/classification, and cross-domain
  references.

### Tests

- Create `cli/tests/test_browser_lineage.py` — Python lineage adapter tests.
- Create `cli/tests/test_browser_compatibility.py` — Python compatibility
  adapter tests.
- Create `cli/tests/test_browser_governance.py` — Python governance adapter
  tests.
- Extend `web/src/protocol.test.ts` — type guard tests for analysis results.
- Extend `web/src/client.test.ts` — analysis method dispatch tests.
- Extend `web/tests/conformance.spec.ts` — browser conformance and budget
  tests for analysis methods.
- Extend `web/tests/playground.spec.ts` — analysis view integration tests.

---

## Batch A — Protocol and analysis data

### Task 1: Conformance fixtures for analysis views

**Files:** `cli/tests/conformance/browser/analysis-customer.mdl`,
`cli/tests/conformance/browser/analysis-billing.mdl`

- [ ] Create `analysis-customer.mdl`: a `customer` domain with entity
  `Customer` at versions 1 and 2 (additive), where v2 adds `@pii email` and
  `@classification("confidential") riskScore` fields.
- [ ] Create `analysis-billing.mdl`: a `billing` domain with projection
  `BillingCustomer@1` from `customer.Customer@2`, including direct mappings
  and at least one computed mapping (CEL expression), plus `@pii` on a
  projected field.
- [ ] Verify the fixtures parse and validate cleanly with the CLI.

### Task 2: Python browser DTOs for analysis results

**Files:** `cli/src/modelable/browser/dto.py`

- [ ] Add `BrowserFieldLineage`, `BrowserProjectionLineage`,
  `BrowserLineageResult` frozen dataclasses.
- [ ] Add `BrowserFieldChange`, `BrowserCompatibilityReport`,
  `BrowserProjectionImpact`, `BrowserCompatibilityResult` frozen dataclasses.
- [ ] Add `BrowserGovernanceFinding`, `BrowserGovernanceResult` frozen
  dataclasses.
- [ ] Run `ruff format`, `ruff check`, `mypy`.

### Task 3: Python lineage browser adapter

**Files:** `cli/src/modelable/browser/lineage.py`,
`cli/tests/test_browser_lineage.py`

- [ ] Create `lineage.py` with `build_browser_lineage(workspace, workspace_revision)`
  that iterates all projection versions, calls `build_projection_lineage` for
  each, and returns `BrowserLineageResult`.
- [ ] Write `test_browser_lineage.py` covering: workspace with projections
  (direct and computed mappings), workspace with no projections (empty result),
  DTO field correctness.
- [ ] Run lint/type/test gates.

### Task 4: Python compatibility browser adapter

**Files:** `cli/src/modelable/browser/compatibility.py`,
`cli/tests/test_browser_compatibility.py`

- [ ] Create `compatibility.py` with
  `build_browser_compatibility(workspace, workspace_revision)` that:
  - finds all models with ≥ 2 published versions;
  - generates `CompatibilityReport` for each consecutive version pair;
  - for breaking reports, calls `find_projection_dependents` and
    `analyze_impact` for each dependent;
  - returns `BrowserCompatibilityResult`.
- [ ] Write `test_browser_compatibility.py` covering: breaking changes,
  compatible changes, projection impacts, workspace with single-version models
  (empty result).
- [ ] Run lint/type/test gates.

### Task 5: Python governance browser adapter

**Files:** `cli/src/modelable/browser/governance.py`,
`cli/tests/test_browser_governance.py`

- [ ] Create `governance.py` with
  `build_browser_governance(workspace, workspace_revision)` that iterates all
  projection versions, calls `build_projection_governance_findings` for each,
  and returns `BrowserGovernanceResult`.
- [ ] Write `test_browser_governance.py` covering: workspace with governance
  findings (missing grants, PII), workspace with no projections (empty result),
  finding aggregation.
- [ ] Run lint/type/test gates.

### Task 6: Python dispatch and API wiring

**Files:** `cli/src/modelable/browser/dispatch.py`,
`cli/src/modelable/browser/api.py`

- [ ] Add `"workspace.lineage"`, `"workspace.compatibility"`,
  `"workspace.governance"` to `_METHODS` in `dispatch.py`.
- [ ] Add dispatch branches: validate `{workspaceRevision}` payload for each,
  call corresponding `_compiler` method.
- [ ] Add `BrowserLineageResult`, `BrowserCompatibilityResult`,
  `BrowserGovernanceResult` to `_DispatchResult` union.
- [ ] Add `lineage(workspace_revision)`, `compatibility(workspace_revision)`,
  `governance(workspace_revision)` methods on `BrowserCompiler` in `api.py`:
  validate revision staleness, require semantic workspace, call adapters.
- [ ] Extend `cli/tests/test_browser_dispatch.py` with dispatch tests for
  all three methods (valid request, stale revision, missing fields).
- [ ] Run lint/type/test gates.

### Task 7: TypeScript protocol types and client methods

**Files:** `web/src/protocol.ts`, `web/src/client.ts`,
`web/src/protocol.test.ts`, `web/src/client.test.ts`, `web/src/App.test.tsx`

- [ ] Add `'workspace.lineage'`, `'workspace.compatibility'`,
  `'workspace.governance'` to `BrowserCompilerMethod` union and `methods` set.
- [ ] Add TypeScript types: `BrowserFieldLineage`, `BrowserProjectionLineage`,
  `BrowserLineageResult`, `BrowserFieldChange`, `BrowserCompatibilityReport`,
  `BrowserProjectionImpact`, `BrowserCompatibilityResult`,
  `BrowserGovernanceFinding`, `BrowserGovernanceResult`.
- [ ] Add type guards: `isBrowserLineageResult`,
  `isBrowserCompatibilityResult`, `isBrowserGovernanceResult`.
- [ ] Add `lineage(workspaceRevision)`, `compatibility(workspaceRevision)`,
  `governance(workspaceRevision)` methods on `BrowserCompilerClient`.
- [ ] Extend `BrowserCompilerClientLike` Pick type.
- [ ] Add methods to test fakes in `App.test.tsx` and other test files.
- [ ] Write protocol guard tests and client dispatch tests.
- [ ] Run `npm run check` and `npm test`.

### Task 8: Conformance test extension

**Files:** `web/tests/conformance.spec.ts`,
`web/scripts/vendor-python-assets.mjs`

- [ ] Add `'analysis-views'` scenario to conformance fixture map with
  `['analysis-customer.mdl', 'analysis-billing.mdl']`.
- [ ] Add conformance fixture vendoring for the new scenario.
- [ ] Extend `TestClient` type with `lineage`, `compatibility`, `governance`.
- [ ] Add conformance tests: call all three analysis methods on the
  analysis-views fixture; verify result shapes and non-empty data.
- [ ] Add budget assertions: ≤ 200 ms median for each analysis method.

---

## Batch B — Visualization rendering

### Task 9: Lineage view rendering

**Files:** `web/src/visualization/LineageView.tsx`

- [ ] Create `LineageView` component: convert `BrowserLineageResult` to
  React Flow nodes (source fields on left, projection fields on right) and
  `derived-from` edges (solid for direct, dashed for computed).
- [ ] Use ELK layout with `LEFT_TO_RIGHT` direction.
- [ ] Show empty state when no projections exist.
- [ ] Write unit tests for the conversion logic.

### Task 10: Compatibility view rendering

**Files:** `web/src/visualization/CompatibilityView.tsx`,
`web/src/visualization/nodes/ChangeNode.tsx`

- [ ] Create `ChangeNode` component: displays field change kind (badge),
  field name, type change details. Non-color-only indicators for change kind.
- [ ] Create `CompatibilityView` component: convert
  `BrowserCompatibilityResult` to React Flow nodes (version pair headers,
  field change nodes, impact nodes) and edges.
- [ ] Use ELK layout with `DOWN` direction.
- [ ] Show empty state when no consecutive versions exist.
- [ ] Write unit tests for the conversion logic.

### Task 11: Governance view rendering

**Files:** `web/src/visualization/GovernanceView.tsx`,
`web/src/visualization/nodes/FindingNode.tsx`

- [ ] Create `FindingNode` component: displays finding code badge, subject,
  and message. Non-color-only severity indicators.
- [ ] Create `GovernanceView` component: convert `BrowserGovernanceResult`
  to React Flow nodes (grouped by subject) and edges.
- [ ] Use ELK layout with `DOWN` direction.
- [ ] Show empty state when no governance findings exist.
- [ ] Write unit tests for the conversion logic.

### Task 12: Graph panel mode extension

**Files:** `web/src/visualization/GraphPanel.tsx`,
`web/src/visualization/GraphPanelContainer.tsx`

- [ ] Add `'lineage' | 'compatibility' | 'governance'` to mode type.
- [ ] Add mode tabs in graph panel: Domain, Entity, Lineage, Compatibility,
  Governance.
- [ ] In `GraphPanelContainer`, fetch analysis data when mode changes to an
  analysis mode (call `client.lineage()`, `client.compatibility()`, or
  `client.governance()`).
- [ ] Pass analysis results to the appropriate view component.
- [ ] Verify keyboard navigation and screen-reader labels for new modes.

---

## Batch C — Export and integration

### Task 13: SVG and PNG export

**Files:** `web/src/visualization/ExportControls.tsx`,
`web/src/visualization/GraphPanel.tsx`

- [ ] Create `ExportControls` component with "Export SVG" and "Export PNG"
  buttons.
- [ ] SVG export: use React Flow's `toSVG()` viewport utility, trigger
  browser download as `modelable-{mode}-{timestamp}.svg`.
- [ ] PNG export: render SVG to canvas via `Image` + `canvas.toDataURL()`,
  trigger download as `modelable-{mode}-{timestamp}.png`.
- [ ] Add export controls to graph panel toolbar (visible in all modes).
- [ ] Write unit tests for filename generation.

### Task 14: Playwright integration tests

**Files:** `web/tests/playground.spec.ts`

- [ ] Add integration test: analysis mode tabs visible when graph panel is
  expanded.
- [ ] Add integration test: switching to lineage/compatibility/governance
  mode renders content or empty state.
- [ ] Add integration test: export buttons trigger downloads (intercept
  download events).
- [ ] Verify no off-origin requests from analysis or export code.

### Task 15: Performance budgets and conformance

**Files:** `web/tests/conformance.spec.ts`

- [ ] Add budget assertions for analysis method timings.
- [ ] Add budget assertion for SVG export timing.
- [ ] Verify all existing conformance tests continue to pass.

### Task 16: Documentation and Phase 5 closeout

- [ ] Update `docs/playground-design.md` status to mark Phase 5 shipped.
- [ ] Update `ROADMAP.md` to mark analysis views shipped, advance Phase 6.
- [ ] Update `CHANGELOG.md` with analysis views entries.
- [ ] Archive this spec and plan to `archived/` directories.
- [ ] Fix any relative links broken by archive moves.
- [ ] Run complete release gate.
