# Graph Theme CSS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore semantic, accessible graph styling that is coherent in the playground's light and dark themes.

**Architecture:** Keep the existing React Flow components and semantic `graph-node` markup unchanged. Lock the visual contract with a browser regression test, then define graph-specific theme tokens and component rules in the shared stylesheet so browser rendering and SVG export use the same cascade.

**Tech Stack:** React 19, TypeScript 7, React Flow 12, CSS custom properties, Playwright 1.61

**Design Spec:** [Graph Theme CSS Design](../../specs/archived/2026-07-27-graph-theme-css-design.md)

## Global Constraints

- Keep the implementation CSS-only unless the failing browser test exposes a missing state hook.
- Do not alter graph layout, data, interactions, node dimensions, or export behavior.
- Use restrained accent borders and kind badges instead of saturated node fills.
- Preserve the dashed version-node treatment.
- Support default light, system dark, and explicit dark themes.
- Run all four `AGENTS.md` repository gates from `cli/` before every commit.

---

### Task 1: Lock the graph visual contract with a browser regression test

**Files:**
- Modify: `web/tests/playground.spec.ts`
- Test: `web/tests/playground.spec.ts`

**Interfaces:**
- Consumes: the existing `openGraphTab(page)` and `waitForReady(page)` helpers
- Produces: an end-to-end contract for semantic node structure, transparent React Flow wrappers, selected-node visibility, and explicit-dark theming

- [ ] **Step 1: Add a failing test for semantic graph styling**

Add this test after `graph panel renders laid out nodes for every mode`:

```ts
test('graph nodes retain semantic styling in light and dark themes', async ({
  page,
}) => {
  await page.addInitScript(() => {
    localStorage.setItem('modelable:theme', 'light');
  });
  await page.goto('?test=1');
  await waitForReady(page);
  await openGraphTab(page);

  const graphSection = page.getByTestId('graph');
  const flowNode = graphSection.locator('.react-flow__node').first();
  const domainNode = graphSection.locator('.graph-node--domain').first();
  const kindBadge = domainNode.locator('.graph-node__kind');

  await expect(domainNode).toBeVisible({ timeout: 30_000 });
  await expect(flowNode).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  await expect(domainNode).toHaveCSS('padding', '6px 10px');
  await expect(domainNode).toHaveCSS('border-radius', '6px');
  await expect(kindBadge).toHaveCSS('display', 'flex');

  await flowNode.focus();
  await expect(flowNode).toHaveCSS(
    'outline-color',
    'rgb(37, 99, 235)',
  );

  await page.getByRole('button', { name: /Theme:/ }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(domainNode).toHaveCSS(
    'background-color',
    'rgb(39, 52, 73)',
  );
  await flowNode.focus();
  await expect(flowNode).toHaveCSS(
    'outline-color',
    'rgb(96, 165, 250)',
  );
});
```

- [ ] **Step 2: Run the test and verify the regression is exposed**

Run:

```bash
cd web
npx playwright test tests/playground.spec.ts --grep "graph nodes retain semantic styling"
```

Expected: FAIL because the outer React Flow node has an opaque background and
the semantic node lacks padding, radius, badge layout, and selected outline.

- [ ] **Step 3: Commit the failing browser contract**

Run the four required `cli/` gates, then:

```bash
git add web/tests/playground.spec.ts
git commit -m "test(web): cover graph theme styling"
```

---

### Task 2: Restore theme-aware semantic graph CSS

**Files:**
- Modify: `web/src/style.css`
- Test: `web/tests/playground.spec.ts`

**Interfaces:**
- Consumes: existing `.graph-node`, `.graph-node--domain`, `.graph-node--entity`, `.graph-node--version`, `.graph-node--projection`, `.graph-node--field`, `.graph-node__label`, `.graph-node__kind`, `.graph-edge--contains`, and `.graph-edge--projects` classes
- Produces: graph-specific CSS custom properties resolved by default light, system dark, and explicit dark theme cascades

- [ ] **Step 1: Replace the three broad graph tokens in every theme block**

In `web/src/style.css`, replace `--graph-node-bg`,
`--graph-node-border`, and `--graph-edge` with this light palette:

```css
--graph-canvas: #f8fafc;
--graph-dot: #cbd5e1;
--graph-surface: #ffffff;
--graph-surface-muted: #f1f5f9;
--graph-border: #94a3b8;
--graph-edge: #64748b;
--graph-selection: #2563eb;
--graph-minimap-node: #94a3b8;
--graph-minimap-mask: rgba(226, 232, 240, 0.7);
--graph-domain: #64748b;
--graph-entity: #2563eb;
--graph-version: #7c3aed;
--graph-projection: #047857;
--graph-field: #64748b;
```

Use this palette in both the system-dark and explicit-dark blocks:

```css
--graph-canvas: #111827;
--graph-dot: #475569;
--graph-surface: #1f2937;
--graph-surface-muted: #273449;
--graph-border: #64748b;
--graph-edge: #94a3b8;
--graph-selection: #60a5fa;
--graph-minimap-node: #64748b;
--graph-minimap-mask: rgba(15, 23, 42, 0.72);
--graph-domain: #94a3b8;
--graph-entity: #60a5fa;
--graph-version: #c4b5fd;
--graph-projection: #34d399;
--graph-field: #94a3b8;
```

- [ ] **Step 2: Restore the semantic node rules**

Replace the current graph-visualization block with rules equivalent to:

```css
.graph-panel .react-flow {
  background: var(--graph-canvas);
  --xy-background-pattern-dots-color-default: var(--graph-dot);
}

.graph-panel .react-flow__node {
  background: transparent;
  color: var(--text);
}

.graph-panel .react-flow__node.selected,
.graph-panel .react-flow__node.selectable:focus {
  border-radius: 0.375rem;
  outline: 2px solid var(--graph-selection);
  outline-offset: 2px;
}

.graph-node {
  width: 100%;
  padding: 0.375rem 0.625rem;
  overflow: hidden;
  border: 1.5px solid var(--graph-border);
  border-radius: 0.375rem;
  background: var(--graph-surface);
  color: var(--text);
  font-family: inherit;
  font-size: 0.75rem;
  cursor: pointer;
}

.graph-node__label {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 0.375rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.graph-node__kind {
  display: flex;
  width: 1.25rem;
  height: 1.25rem;
  flex: 0 0 1.25rem;
  align-items: center;
  justify-content: center;
  border-radius: 0.25rem;
  background: var(--graph-surface-muted);
  color: var(--text-muted);
  font-size: 0.625rem;
  font-weight: 700;
}

.graph-node--domain {
  border-color: var(--graph-domain);
  background: var(--graph-surface-muted);
  font-weight: 600;
}

.graph-node--entity {
  border-color: var(--graph-entity);
  border-width: 2px;
}

.graph-node--version {
  border-color: var(--graph-version);
  border-style: dashed;
  color: var(--text-muted);
  font-size: 0.6875rem;
}

.graph-node--projection {
  border-color: var(--graph-projection);
  border-width: 2px;
}

.graph-node--field {
  border-color: var(--graph-field);
  color: var(--text-muted);
  font-size: 0.6875rem;
}
```

Keep the existing controls rules. Update handles, edges, edge variants, and the
MiniMap to use the new tokens:

```css
.graph-panel .react-flow__handle {
  background: var(--graph-border);
  border-color: var(--graph-surface);
}

.graph-panel .react-flow__edge-path,
.graph-panel .react-flow__connection-path {
  stroke: var(--graph-edge);
}

.graph-panel .graph-edge--contains {
  stroke: var(--graph-border);
  stroke-width: 1.5;
}

.graph-panel .graph-edge--projects {
  stroke: var(--graph-projection);
  stroke-width: 1.5;
}

.graph-panel .react-flow__minimap {
  border: 1px solid var(--graph-border);
  background: var(--graph-surface-muted);
}

.graph-panel .react-flow__minimap-node {
  fill: var(--graph-minimap-node);
}

.graph-panel .react-flow__minimap-mask {
  fill: var(--graph-minimap-mask);
}
```

- [ ] **Step 3: Run the focused browser test and verify it passes**

Run:

```bash
cd web
npx playwright test tests/playground.spec.ts --grep "graph nodes retain semantic styling"
```

Expected: PASS.

- [ ] **Step 4: Run the full web verification**

Run:

```bash
cd web
npm test
npm run check
npm run build
npx playwright test tests/playground.spec.ts
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit the CSS implementation**

Run the four required `cli/` gates, then:

```bash
git add web/src/style.css
git commit -m "fix(web): reconcile graph styles with dark mode"
```

---

### Task 3: Perform visual and export verification

**Files:**
- Verify: `web/src/style.css`
- Verify: `web/src/visualization/useGraphExport.ts`
- Verify: `web/tests/playground.spec.ts`

**Interfaces:**
- Consumes: the production preview and existing graph export action
- Produces: light/dark screenshots and confirmation that exported SVG resolves the active theme tokens

- [ ] **Step 1: Start the production preview**

Run:

```bash
cd web
npm run build
npm run preview
```

Open `http://127.0.0.1:4173/modelable/playground/?test=1`.

- [ ] **Step 2: Inspect the graph in explicit light mode**

Open the Graph tab and check:

- Domain, entity, version, projection, and field nodes retain distinct borders.
- Labels remain inside their nodes and truncate instead of overflowing.
- Selected and keyboard-focused nodes have a visible blue outline.
- Edges, handles, canvas dots, controls, and MiniMap are legible.

Save `graph-light-fixed.png` under the ignored browser-output directory.

- [ ] **Step 3: Inspect the graph in explicit dark mode**

Switch the theme control to explicit dark and repeat every light-mode check.
Confirm that node fills remain dark, semantic accents remain restrained, and
the MiniMap mask does not become a bright block.

Save `graph-dark-fixed.png` under the ignored browser-output directory.

- [ ] **Step 4: Inspect an exported SVG**

Use the graph Export action in light mode and dark mode. Open each SVG and
confirm its root has the matching `data-theme`, its canvas uses the active
theme, and its nodes and edges retain the browser styling.

- [ ] **Step 5: Run final repository verification**

From `cli/`:

```bash
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

From `web/`:

```bash
npm test
npm run check
npm run build
npx playwright test tests/playground.spec.ts
```

Expected: all commands exit 0 and the working tree contains only the intended
plan, test, and stylesheet changes.
