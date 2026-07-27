# Responsive Graph Viewport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep graph nodes readable on constrained panels while using widened and ultrawide canvases to reveal more graph context without overlay collisions.

**Design:** [Responsive Graph Viewport Design](../../specs/archived/2026-07-27-responsive-graph-viewport-design.md)

**Architecture:** Add a pure viewport policy module and a focused React hook that applies that policy through React Flow's `fitView`, `Controls.fitViewOptions`, and canvas `ResizeObserver`. `GraphPanel` composes the hook with the existing export ref, while CSS handles responsive toolbar and overlay presentation and Playwright verifies real rendered geometry.

**Tech Stack:** React 19, TypeScript 7, React Flow 12, ELK.js, Vitest, Testing Library, Playwright, CSS

## Global Constraints

- Automatic fitting must not reduce graph zoom below `0.8`.
- Automatic fitting must not enlarge normal graph nodes above `1`.
- Deliberate user zoom may still reach the existing interactive minimum of `0.1`.
- Domain and Lineage show the complete graph when it fits at the readable scale; Entity and Projection prefer readable nodes with panning.
- Resize-driven fitting is debounced and stops after deliberate user pan or zoom.
- Changing graph mode or graph layout permits a new initial fit.
- Nodes retain their authored dimensions on larger displays.
- The playground workbench uses the full available browser width instead of the existing `120rem` cap.
- MiniMap and controls must not obscure nodes in the initial fitted view.
- All graph modes must be screenshot-checked in explicit light and dark themes.
- No compiler graph DTO, protocol, persistence, ELK dependency, or React Flow dependency changes.
- Before every commit, run the four `AGENTS.md` commands from `cli/`.

---

### Task 1: Define the readable viewport policy

**Files:**
- Create: `web/src/visualization/graph-viewport.ts`
- Create: `web/src/visualization/graph-viewport.test.ts`

**Interfaces:**
- Consumes: `BrowserGraphMode` from `web/src/protocol.ts` and `FitViewOptions` from `@xyflow/react`.
- Produces: `READABLE_FIT_MIN_ZOOM`, `INTERACTIVE_MIN_ZOOM`, `AUTO_FIT_MAX_ZOOM`, `RESIZE_FIT_DEBOUNCE_MS`, `CanvasSize`, `readableFitOptions(showMiniMap)`, and `shouldShowMiniMap(size, nodeCount)`.

- [ ] **Step 1: Write the failing viewport-policy tests**

```ts
import { describe, expect, test } from 'vitest';

import {
  AUTO_FIT_MAX_ZOOM,
  INTERACTIVE_MIN_ZOOM,
  READABLE_FIT_MIN_ZOOM,
  readableFitOptions,
  shouldShowMiniMap,
} from './graph-viewport';

describe('readableFitOptions', () => {
  test('keeps automatic fitting readable without restricting deliberate overview zoom', () => {
    expect(READABLE_FIT_MIN_ZOOM).toBe(0.8);
    expect(INTERACTIVE_MIN_ZOOM).toBe(0.1);
    expect(AUTO_FIT_MAX_ZOOM).toBe(1);
    expect(readableFitOptions(false)).toMatchObject({
      minZoom: 0.8,
      maxZoom: 1,
    });
  });

  test('reserves additional right-side space when the minimap is visible', () => {
    const withoutMiniMap = readableFitOptions(false);
    const withMiniMap = readableFitOptions(true);
    expect(withMiniMap.padding).not.toEqual(withoutMiniMap.padding);
  });
});

describe('shouldShowMiniMap', () => {
  test('shows navigation context only for a dense graph on a roomy canvas', () => {
    expect(shouldShowMiniMap({ width: 900, height: 600 }, 37)).toBe(true);
    expect(shouldShowMiniMap({ width: 500, height: 600 }, 37)).toBe(false);
    expect(shouldShowMiniMap({ width: 900, height: 300 }, 37)).toBe(false);
    expect(shouldShowMiniMap({ width: 900, height: 600 }, 7)).toBe(false);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npm test -- --run src/visualization/graph-viewport.test.ts`

Expected: FAIL because `graph-viewport.ts` does not exist.

- [ ] **Step 3: Implement the viewport policy**

```ts
import type { FitViewOptions } from '@xyflow/react';

export const READABLE_FIT_MIN_ZOOM = 0.8;
export const AUTO_FIT_MAX_ZOOM = 1;
export const INTERACTIVE_MIN_ZOOM = 0.1;
export const RESIZE_FIT_DEBOUNCE_MS = 160;

const MINIMAP_MIN_CANVAS_WIDTH = 640;
const MINIMAP_MIN_CANVAS_HEIGHT = 360;
const MINIMAP_MIN_NODE_COUNT = 10;

export interface CanvasSize {
  width: number;
  height: number;
}

export function shouldShowMiniMap(
  size: CanvasSize,
  nodeCount: number,
): boolean {
  return (
    size.width >= MINIMAP_MIN_CANVAS_WIDTH &&
    size.height >= MINIMAP_MIN_CANVAS_HEIGHT &&
    nodeCount >= MINIMAP_MIN_NODE_COUNT
  );
}

export function readableFitOptions(showMiniMap: boolean): FitViewOptions {
  return {
    minZoom: READABLE_FIT_MIN_ZOOM,
    maxZoom: AUTO_FIT_MAX_ZOOM,
    padding: {
      top: '24px',
      right: showMiniMap ? '164px' : '24px',
      bottom: '64px',
      left: '64px',
    },
  };
}
```

- [ ] **Step 4: Run the viewport-policy tests**

Run: `cd web && npm test -- --run src/visualization/graph-viewport.test.ts`

Expected: PASS.

- [ ] **Step 5: Run TypeScript checking**

Run: `cd web && npm run check`

Expected: PASS with no type errors from React Flow padding or exported policy types.

- [ ] **Step 6: Run the mandatory repository gates**

Run from `cli/`, in order:

```bash
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Expected: all four commands pass cleanly.

- [ ] **Step 7: Commit**

```bash
git add web/src/visualization/graph-viewport.ts web/src/visualization/graph-viewport.test.ts
git commit -m "test: define readable graph viewport policy"
```

---

### Task 2: Apply resize-aware fitting without overriding user navigation

**Files:**
- Create: `web/src/visualization/useReadableGraphViewport.ts`
- Create: `web/src/visualization/useReadableGraphViewport.test.tsx`

**Interfaces:**
- Consumes: a shared `RefObject<HTMLDivElement | null>`, the current `GraphNode[]`, `fitView()` from `useReactFlow`, and the Task 1 viewport policy.
- Produces:

```ts
export interface ReadableGraphViewport {
  fitViewOptions: FitViewOptions;
  showMiniMap: boolean;
  onMoveStart: OnMoveStart;
  onFitView(): void;
}

export function useReadableGraphViewport(
  containerRef: RefObject<HTMLDivElement | null>,
  nodes: GraphNode[],
): ReadableGraphViewport;
```

- [ ] **Step 1: Write failing hook tests with controlled browser primitives**

Mock `useReactFlow()` to return `fitView`, install a test `ResizeObserver`, and
stub `requestAnimationFrame` so fits execute deterministically:

```tsx
// @vitest-environment jsdom

import { act, renderHook } from '@testing-library/react';
import { createRef } from 'react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

const fitView = vi.fn(async () => true);
let animationFrame: FrameRequestCallback | null = null;
let resizeCallback: ResizeObserverCallback | null = null;

vi.mock('@xyflow/react', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@xyflow/react')>()),
  useReactFlow: () => ({ fitView }),
}));

function graphNode(id: string): GraphNode {
  return {
    id,
    position: { x: 0, y: 0 },
    data: {
      label: id,
      kind: 'entity',
      metadata: {},
      sourceRange: null,
      direction: 'DOWN',
    },
  };
}

function setCanvasRect(
  element: HTMLDivElement,
  width: number,
  height: number,
): void {
  vi.spyOn(element, 'getBoundingClientRect').mockReturnValue({
    x: 0,
    y: 0,
    top: 0,
    right: width,
    bottom: height,
    left: 0,
    width,
    height,
    toJSON: () => ({}),
  });
}

function runAnimationFrame(): void {
  const callback = animationFrame;
  animationFrame = null;
  callback?.(0);
}

function resizeCanvas(
  target: HTMLDivElement,
  width: number,
  height: number,
): void {
  setCanvasRect(target, width, height);
  resizeCallback?.(
    [
      {
        target,
        contentRect: target.getBoundingClientRect(),
      } as ResizeObserverEntry,
    ],
    {} as ResizeObserver,
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  fitView.mockClear();
  animationFrame = null;
  resizeCallback = null;
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    animationFrame = callback;
    return 1;
  });
  vi.stubGlobal('cancelAnimationFrame', () => {
    animationFrame = null;
  });
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(callback: ResizeObserverCallback) {
        resizeCallback = callback;
      }
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    },
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test('fits a completed layout and refits a resized untouched canvas', async () => {
  const containerRef = createRef<HTMLDivElement>();
  containerRef.current = document.createElement('div');
  setCanvasRect(containerRef.current, 700, 500);
  const { result } = renderHook(() =>
    useReadableGraphViewport(containerRef, [graphNode('one')]),
  );

  await act(async () => runAnimationFrame());
  expect(fitView).toHaveBeenLastCalledWith(result.current.fitViewOptions);

  act(() => resizeCanvas(containerRef.current!, 900, 600));
  await act(async () =>
    vi.advanceTimersByTimeAsync(RESIZE_FIT_DEBOUNCE_MS),
  );
  expect(fitView).toHaveBeenCalledTimes(2);
});

test('does not refit resize after pointer navigation begins', async () => {
  const containerRef = createRef<HTMLDivElement>();
  containerRef.current = document.createElement('div');
  setCanvasRect(containerRef.current, 700, 500);
  const { result } = renderHook(() =>
    useReadableGraphViewport(containerRef, [graphNode('one')]),
  );
  await act(async () => runAnimationFrame());

  act(() => result.current.onMoveStart(new MouseEvent('mousedown'), {
    x: 0,
    y: 0,
    zoom: 1,
  }));
  act(() => resizeCanvas(containerRef.current!, 1000, 700));
  await act(async () =>
    vi.advanceTimersByTimeAsync(RESIZE_FIT_DEBOUNCE_MS),
  );

  expect(fitView).toHaveBeenCalledTimes(1);
});

test('a new node array establishes a new initial fit', async () => {
  const containerRef = createRef<HTMLDivElement>();
  containerRef.current = document.createElement('div');
  setCanvasRect(containerRef.current, 700, 500);
  const first = [graphNode('one')];
  const { rerender } = renderHook(
    ({ nodes }) => useReadableGraphViewport(containerRef, nodes),
    { initialProps: { nodes: first } },
  );
  await act(async () => runAnimationFrame());
  rerender({ nodes: [graphNode('two')] });
  await act(async () => runAnimationFrame());
  expect(fitView).toHaveBeenCalledTimes(2);
});
```

- [ ] **Step 2: Run the hook tests to verify they fail**

Run: `cd web && npm test -- --run src/visualization/useReadableGraphViewport.test.tsx`

Expected: FAIL because `useReadableGraphViewport.ts` does not exist.

- [ ] **Step 3: Implement the hook**

Implement the hook with these state transitions:

```ts
const { fitView } = useReactFlow();
const [canvasSize, setCanvasSize] = useState<CanvasSize>({
  width: 0,
  height: 0,
});
const userNavigatedRef = useRef(false);
const previousSizeRef = useRef<CanvasSize | null>(null);
const showMiniMap = shouldShowMiniMap(canvasSize, nodes.length);
const fitViewOptions = useMemo(
  () => readableFitOptions(showMiniMap),
  [showMiniMap],
);

const fitViewOptionsRef = useRef(fitViewOptions);
fitViewOptionsRef.current = fitViewOptions;

const measureFitOptions = useCallback((): FitViewOptions => {
  const bounds = containerRef.current?.getBoundingClientRect();
  if (bounds === undefined) return fitViewOptionsRef.current;
  const size = { width: bounds.width, height: bounds.height };
  const next = readableFitOptions(shouldShowMiniMap(size, nodes.length));
  setCanvasSize(size);
  fitViewOptionsRef.current = next;
  return next;
}, [containerRef, nodes.length]);

const fitReadableView = useCallback(() => {
  void fitView(measureFitOptions());
}, [fitView, measureFitOptions]);

useEffect(() => {
  if (nodes.length === 0) return;
  userNavigatedRef.current = false;
  const frame = requestAnimationFrame(fitReadableView);
  return () => cancelAnimationFrame(frame);
}, [fitReadableView, nodes]);
```

The `nodes` dependency intentionally represents a completed new layout. A
canvas-size change updates `fitViewOptionsRef` but does not clear
`userNavigatedRef`.

Add a `ResizeObserver` effect that calls `measureFitOptions`, compares the
observed width and height with `previousSizeRef`, and schedules
`fitReadableView` after `RESIZE_FIT_DEBOUNCE_MS` only when nodes exist,
dimensions actually changed, and `userNavigatedRef.current === false`. On the
observer's first notification, record the size without scheduling a duplicate
fit. Clear the timeout and disconnect the observer during cleanup.

Return an `onMoveStart` callback that sets `userNavigatedRef.current = true`
only when React Flow supplies a non-null pointer or touch event. Programmatic
fits use a null event and must not disable future responsive fitting. Return
`onFitView` as a callback that sets `userNavigatedRef.current = false`, so the
explicit fit control restores responsive fitting after the user resets the
view.

- [ ] **Step 4: Run the hook and policy tests**

Run:

```bash
cd web
npm test -- --run src/visualization/useReadableGraphViewport.test.tsx src/visualization/graph-viewport.test.ts
```

Expected: PASS.

- [ ] **Step 5: Run TypeScript checking**

Run: `cd web && npm run check`

Expected: PASS.

- [ ] **Step 6: Run the mandatory repository gates**

Run the four commands in `Global Constraints` from `cli/`.

Expected: all four commands pass cleanly.

- [ ] **Step 7: Commit**

```bash
git add web/src/visualization/useReadableGraphViewport.ts web/src/visualization/useReadableGraphViewport.test.tsx
git commit -m "feat: add responsive graph viewport fitting"
```

---

### Task 3: Integrate readable fitting, responsive MiniMap, and export ref ownership

**Files:**
- Modify: `web/src/visualization/GraphPanel.tsx:1-145`
- Modify: `web/src/visualization/useGraphExport.ts:1-111`
- Create: `web/src/visualization/GraphPanel.test.tsx`

**Interfaces:**
- Consumes: `useReadableGraphViewport(containerRef, nodes)` from Task 2.
- Produces: one shared graph canvas ref, readable initial and control fits,
  user-interaction tracking, and conditional MiniMap rendering.
- Changes `useGraphExport` to:

```ts
export function useGraphExport(
  containerRef: RefObject<HTMLDivElement | null>,
): {
  exportSvg(): void;
  exportPng(): void;
};
```

- [ ] **Step 1: Write failing GraphPanel composition tests**

Mock `useGraphLayout`, `useGraphSync`, `useGraphExport`,
`useReadableGraphViewport`, and the lightweight React Flow surface. Assert the
policy is connected to both the canvas and built-in controls:

```tsx
test('shares readable fit options with React Flow and its fit control', () => {
  render(<GraphPanel {...props} />);

  expect(screen.getByTestId('react-flow')).toHaveAttribute('data-min-zoom', '0.1');
  expect(screen.getByTestId('react-flow')).toHaveAttribute(
    'data-fit-min-zoom',
    '0.8',
  );
  expect(screen.getByTestId('controls')).toHaveAttribute(
    'data-fit-min-zoom',
    '0.8',
  );
});

test('renders the minimap only when the responsive policy enables it', () => {
  mockViewport.showMiniMap = false;
  const { rerender } = render(<GraphPanel {...props} />);
  expect(screen.queryByTestId('minimap')).toBeNull();

  mockViewport.showMiniMap = true;
  rerender(<GraphPanel {...props} />);
  expect(screen.getByTestId('minimap')).toBeTruthy();
});
```

The React Flow mock must render its `children`, expose `fitViewOptions.minZoom`,
`minZoom`, and `onMoveStart`, and use distinct `data-testid` values for
`Controls` and `MiniMap`.

- [ ] **Step 2: Run the GraphPanel tests to verify they fail**

Run: `cd web && npm test -- --run src/visualization/GraphPanel.test.tsx`

Expected: FAIL because `GraphPanel` still uses unconditional `fitView()` and
always renders the MiniMap.

- [ ] **Step 3: Give GraphPanel one shared container ref**

In `GraphPanelInner`, create the ref and pass it to both hooks:

```ts
const containerRef = useRef<HTMLDivElement>(null);
const { exportSvg, exportPng } = useGraphExport(containerRef);
const { fitViewOptions, showMiniMap, onMoveStart, onFitView } =
  useReadableGraphViewport(containerRef, nodes);
```

Update `useGraphExport` to consume the supplied ref and remove its internal
`useRef`. Keep export behavior and filenames unchanged.

- [ ] **Step 4: Replace unconditional fitting with the shared policy**

Remove the existing `useReactFlow`/`useEffect` fit block. Configure React Flow
and its children:

```tsx
<ReactFlow
  nodes={nodesWithSelection}
  edges={edges}
  nodeTypes={nodeTypes}
  edgeTypes={edgeTypes}
  onNodeClick={(_event, node) => onNodeClick(node as GraphNode)}
  onMoveStart={onMoveStart}
  fitView
  fitViewOptions={fitViewOptions}
  minZoom={INTERACTIVE_MIN_ZOOM}
  maxZoom={2}
  proOptions={{ hideAttribution: true }}
>
  <Controls fitViewOptions={fitViewOptions} onFitView={onFitView} />
  {showMiniMap ? (
    <MiniMap
      aria-hidden="true"
      className="graph-panel__minimap"
      style={{ width: 144, height: 104 }}
    />
  ) : null}
  <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
</ReactFlow>
```

Group the existing toolbar buttons without changing their labels or accessible
toolbar role:

```tsx
<div className="tab-strip" role="toolbar" aria-label="Graph mode">
  <div className="graph-panel__modes">
    {([
      ['domain', 'Domain'],
      ['entity', 'Entity'],
      ['projection', 'Projection'],
      ['lineage', 'Lineage'],
    ] as const).map(([candidate, label]) => (
      <button
        key={candidate}
        className={`tab${mode === candidate ? ' tab--active' : ''}`}
        onClick={() => onModeChange(candidate)}
        aria-pressed={mode === candidate}
      >
        {label}
      </button>
    ))}
  </div>
  <div className="graph-panel__exports">
    <button
      className="graph-panel__export-btn"
      onClick={exportSvg}
      disabled={nodes.length === 0}
    >
      Export SVG
    </button>
    <button
      className="graph-panel__export-btn"
      onClick={exportPng}
      disabled={nodes.length === 0}
    >
      Export PNG
    </button>
  </div>
</div>
```

Remove `.graph-panel__toolbar-spacer`; the two groups own toolbar distribution.

- [ ] **Step 5: Run the focused tests and type check**

Run:

```bash
cd web
npm test -- --run src/visualization/GraphPanel.test.tsx src/visualization/useReadableGraphViewport.test.tsx src/visualization/graph-viewport.test.ts
npm run check
```

Expected: all tests and TypeScript checking pass.

- [ ] **Step 6: Run the mandatory repository gates**

Run the four commands in `Global Constraints` from `cli/`.

Expected: all four commands pass cleanly.

- [ ] **Step 7: Commit**

```bash
git add web/src/visualization/GraphPanel.tsx web/src/visualization/useGraphExport.ts web/src/visualization/GraphPanel.test.tsx
git commit -m "feat: keep dense graph views readable"
```

---

### Task 4: Polish responsive canvas, overlays, toolbar, and ultrawide layout

**Files:**
- Modify: `web/src/style.css:213-221`
- Modify: `web/src/style.css:612-795`
- Modify: `web/src/style.css:1419-1495`
- Modify: `web/tests/playground.spec.ts`

**Interfaces:**
- Consumes: `.graph-panel__minimap`, `.graph-panel__canvas`, existing React
  Flow classes, and the readable viewport behavior from Tasks 1–3.
- Produces: full-width workbench CSS, compact graph toolbar, bounded MiniMap,
  compact horizontal controls, and end-to-end geometry assertions.

- [ ] **Step 1: Add failing Playwright checks for readable dense modes**

Add helpers:

```ts
function graphZoom(page: Page): Promise<number> {
  return page.locator('.graph-panel .react-flow__viewport').evaluate((element) => {
    const transform = (element as HTMLElement).style.transform;
    const match = transform.match(/scale\(([\d.]+)\)/);
    if (match?.[1] === undefined) throw new Error(`Missing graph scale: ${transform}`);
    return Number(match[1]);
  });
}

function rectanglesOverlap(
  left: { x: number; y: number; width: number; height: number },
  right: { x: number; y: number; width: number; height: number },
): boolean {
  return (
    left.x < right.x + right.width &&
    left.x + left.width > right.x &&
    left.y < right.y + right.height &&
    left.y + left.height > right.y
  );
}
```

Add a test that opens Entity and Projection modes at 1280×720, waits for each
layout, and asserts `await graphZoom(page) >= 0.8`. Collect visible node,
controls, and optional MiniMap bounding boxes and assert no initial
intersection.

- [ ] **Step 2: Add failing large-screen and responsive-MiniMap checks**

At 2560×1440, assert:

```ts
const workbenchWidth = await page.locator('.workbench').evaluate(
  (element) => element.getBoundingClientRect().width,
);
expect(workbenchWidth).toBeGreaterThanOrEqual(2500);
```

Record canvas width and visible node count, widen the visualization panel by
dragging its left separator, and assert the canvas grows. Verify the graph
still starts at or above `0.8`.

At a graph canvas narrower than `640px`, assert the MiniMap is absent. On a
roomy dense canvas, assert it is present and no larger than `144px` by `104px`.

- [ ] **Step 3: Run the new Playwright tests to verify they fail**

Run:

```bash
cd web
npx playwright test tests/playground.spec.ts --project=chromium --grep "graph.*readable|ultrawide|responsive minimap"
```

Expected: FAIL because Entity and Projection start below `0.8`, the workbench
is capped at 1920px, and the default MiniMap is 202px by 152px.

- [ ] **Step 4: Implement the responsive graph CSS**

Replace the workbench width cap:

```css
.workbench {
  width: 100%;
  max-width: none;
}
```

Refine the graph toolbar and canvas:

```css
.graph-panel .tab-strip {
  align-items: center;
  flex-wrap: wrap;
  gap: 0.25rem;
  padding: 0.3rem 0.4rem;
}

.graph-panel {
  container-type: inline-size;
}

.graph-panel__modes,
.graph-panel__exports {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.graph-panel__modes {
  flex: 1 1 auto;
}

.graph-panel__exports {
  margin-left: auto;
}

.graph-panel .tab,
.graph-panel__export-btn {
  min-height: 1.75rem;
  padding: 0.2rem 0.45rem;
  white-space: nowrap;
}

.graph-panel__canvas {
  isolation: isolate;
}

.graph-panel .react-flow__controls {
  display: flex;
  overflow: hidden;
  flex-direction: row;
  border: 1px solid var(--graph-border);
  border-radius: 0.45rem;
  box-shadow: 0 0.25rem 0.75rem color-mix(in srgb, var(--text) 12%, transparent);
}

.graph-panel .react-flow__controls-button {
  width: 1.75rem;
  height: 1.75rem;
  border-bottom: 0;
  border-right: 1px solid var(--border);
}

.graph-panel .react-flow__controls-button:last-child {
  border-right: 0;
}

.graph-panel__minimap {
  overflow: hidden;
  border-radius: 0.5rem;
  box-shadow: 0 0.25rem 0.75rem color-mix(in srgb, var(--text) 12%, transparent);
}

@container (max-width: 34rem) {
  .graph-panel__exports {
    width: 100%;
    margin-left: 0;
  }

  .graph-panel__export-btn {
    flex: 1;
  }
}
```

The container query tracks the resizable graph panel instead of the browser
viewport. Keep visible focus indicators and the existing graph theme tokens.

- [ ] **Step 5: Tune graph spacing only where screenshots show collisions**

If the initial screenshot pass shows unnecessarily tight paths, adjust
`buildElkGraph()` with explicit per-mode spacing helpers covered in
`layout-model.test.ts`:

```ts
export function layoutSpacing(mode: BrowserGraphMode): {
  nodeNode: string;
  betweenLayers: string;
} {
  return mode === 'entity'
    ? { nodeNode: '36', betweenLayers: '72' }
    : { nodeNode: '32', betweenLayers: '68' };
}
```

Do not change node dimensions or semantic edge relationships. Skip this edit
when the viewport and overlay changes already produce clear spacing.

- [ ] **Step 6: Run focused web verification**

Run:

```bash
cd web
npm test -- --run src/visualization
npm run check
npx playwright test tests/playground.spec.ts --project=chromium --grep "graph"
```

Expected: all graph unit, component, and Playwright tests pass.

- [ ] **Step 7: Run the mandatory repository gates**

Run the four commands in `Global Constraints` from `cli/`.

Expected: all four commands pass cleanly.

- [ ] **Step 8: Commit**

```bash
git add web/src/style.css web/tests/playground.spec.ts web/src/visualization/layout-model.ts web/src/visualization/layout-model.test.ts
git commit -m "style: polish responsive graph composition"
```

Omit unchanged layout-model files from `git add` when Step 5 was unnecessary.

---

### Task 5: Capture the final visual matrix and run release verification

**Files:**
- Modify only files that require evidence-driven visual tuning from Task 4.
- Capture ignored artifacts under: `web/output/playwright/graph-cleanup/`

**Interfaces:**
- Consumes: the complete responsive graph implementation.
- Produces: before/after screenshot evidence at constrained, default, and
  ultrawide sizes and a fully verified branch.

- [ ] **Step 1: Build and start the production preview**

Run:

```bash
cd web
npm run build
npm run preview
```

Expected: production build succeeds and preview listens on
`http://127.0.0.1:4173/modelable/playground/`.

- [ ] **Step 2: Capture explicit light-theme screenshots**

Using the Playwright CLI, set `localStorage['modelable:theme'] = 'light'`, open
the graph tab, and capture Domain, Entity, Projection, and Lineage at 1280×720:

```text
web/output/playwright/graph-cleanup/domain-light.png
web/output/playwright/graph-cleanup/entity-light.png
web/output/playwright/graph-cleanup/projection-light.png
web/output/playwright/graph-cleanup/lineage-light.png
```

- [ ] **Step 3: Capture explicit dark-theme screenshots**

Switch to the explicit dark theme and capture the same four modes:

```text
web/output/playwright/graph-cleanup/domain-dark.png
web/output/playwright/graph-cleanup/entity-dark.png
web/output/playwright/graph-cleanup/projection-dark.png
web/output/playwright/graph-cleanup/lineage-dark.png
```

- [ ] **Step 4: Capture constrained and ultrawide dense-graph screenshots**

Capture Entity mode with a constrained graph panel and at 2560×1440:

```text
web/output/playwright/graph-cleanup/entity-constrained.png
web/output/playwright/graph-cleanup/entity-ultrawide.png
```

Verify visually that labels remain readable, extra ultrawide space reveals
more context, controls and MiniMap do not cover nodes, and toolbar actions do
not overflow.

- [ ] **Step 5: Make evidence-driven visual corrections**

Limit corrections to the approved design: viewport padding, MiniMap bounds,
toolbar density, overlay placement, graph-specific theme tokens, edges, and
mode spacing. Re-run the focused unit and Playwright tests after every
correction and recapture any affected screenshots.

- [ ] **Step 6: Run complete web verification**

Run:

```bash
cd web
npm test
npm run check
npm run build
npx playwright test --project=chromium
```

Expected: all commands pass.

- [ ] **Step 7: Run the mandatory repository gates**

Run from `cli/`, in order:

```bash
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Expected: all four commands pass cleanly.

- [ ] **Step 8: Confirm branch scope and commit any final tuning**

Run:

```bash
git status --short
git diff --check
git diff --stat
```

If Step 5 changed tracked files, commit exactly those files:

```bash
git add web/src web/tests/playground.spec.ts
git commit -m "style: finish graph visual cleanup"
```

Do not add `web/output/playwright/`; screenshots remain local verification
artifacts for the user.
