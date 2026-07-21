# 2026-07-21 Playground Visualization MVP — Design

## Status

Accepted on 2026-07-21.

Execution is broken into reviewable tasks in the
[Playground Visualization implementation plan](../plans/2026-07-21-playground-visualization.md).

This specification defines Phase 4 of the
[Modelable Playground Architecture](../../playground-design.md). It builds on
the shipped workspace persistence and browser-native language services, and
adds compiler-owned semantic graph export, ELK-based layout, React Flow
rendering, and bidirectional editor–graph navigation.

The repository [roadmap](../../../ROADMAP.md) makes the remaining Playground
phases the immediate product priority, records Phases 1–4 as the active
visualization and analysis work, and names Scalable registration as the next
non-Playground priority.

## Context

The deployed Playground edits multi-file Modelable workspaces with full
compiler-backed language services (diagnostics, completion, hover, definition,
references, rename). Users can validate, format, and generate JSON Schema. All
source remains local and same-origin.

A visualization layer makes the workspace's structure navigable and
inspectable beyond textual source: domains, models, projections, versions,
field-level lineage, and cross-domain dependencies become visible in an
interactive graph.

The Python CLI already has `modelable.graph.export.build_graph_export`, which
produces a deterministic JSON graph from a `Workspace`. This function is
CLI-only; it is not wired to the browser compiler protocol, has no DTO
counterpart in `modelable.browser`, and uses node/edge kind vocabularies that
differ from the architecture document's specification.

## Goals

- Add a `workspace.graph` browser compiler protocol method that returns the
  semantic graph for the current workspace.
- Adapt the existing Python `build_graph_export` to produce a browser DTO
  whose node and edge kinds match the architecture document (section 10.2).
- Render two visualization modes: a domain graph (domains, models,
  projections, cross-domain edges) and an entity diagram (fields, types,
  keys, optionality, version evolution).
- Lay out graphs using ELK.js in a dedicated web worker so layout never
  blocks the main thread.
- Render and interact with graphs through React Flow (`@xyflow/react`).
- Support bidirectional navigation: clicking a graph node reveals the
  corresponding source range in the editor; placing the cursor on a
  definition highlights the graph node.
- Preserve the static, local-only, same-origin deployment and existing
  conformance, performance, and security gates.

## Non-goals

This phase does not include:

- field-level lineage visualization (Phase 5);
- compatibility or governance visualization (Phase 5);
- SVG or PNG export (Phase 5);
- WebLLM, model downloads, or AI-generated views (Phase 6);
- service-worker installation or offline caching (Phase 7);
- plugin contracts or additional visualization modes (Phase 8);
- persisting graph layouts, selected views, or visualization state in
  IndexedDB; or
- changing Modelable parsing, validation, formatting, compilation, registry,
  or compatibility semantics.

## Chosen approach

Wire the existing Python graph builder to the browser compiler protocol as a
new `workspace.graph` method. Adapt its output to the architecture's DTO
schema. On the TypeScript side, add ELK.js layout in a web worker and render
with React Flow. Graph state is derived — never persisted — and is discarded
when source changes invalidate it.

This approach was selected over:

- building a TypeScript-side graph from parsed AST, which would duplicate
  semantic inference that the Python compiler already owns; and
- embedding a full graph database or D3 force layout, which would add
  complexity beyond what a deterministic compiler graph requires.

## Architecture decision scope

No ADR change is required. The
[Playground Architecture](../../playground-design.md#10-visualization-architecture)
already assigns graph DTOs to the Python compiler, layout to ELK.js, and
rendering to React. This specification narrows Phase 4 delivery and makes its
protocol, DTO, layout, and rendering contracts executable.

## Protocol extension

### `workspace.graph` method

Request payload:

```json
{
  "workspaceRevision": 100,
  "mode": "domain"
}
```

- `workspaceRevision` must match the current compiler revision (same staleness
  rule as language methods).
- `mode` is `"domain"` or `"entity"`. The compiler filters nodes and edges
  to the requested view.

Response payload:

```json
{
  "ok": true,
  "result": {
    "workspace_revision": 100,
    "mode": "domain",
    "graph": {
      "schema_version": 1,
      "nodes": [...],
      "edges": [...]
    }
  }
}
```

### Graph DTO

The browser DTO aligns with the architecture document (section 10.2) but uses
only the kinds that are emittable today:

```python
@dataclass(frozen=True)
class BrowserGraphNode:
    id: str
    kind: str  # "domain" | "entity" | "version" | "field" | "projection"
    label: str
    metadata: dict[str, Any]
    source_range: BrowserSourceRange | None = None

@dataclass(frozen=True)
class BrowserSourceRange:
    uri: str
    start_line: int
    start_character: int
    end_line: int
    end_character: int

@dataclass(frozen=True)
class BrowserGraphEdge:
    id: str
    source: str
    target: str
    kind: str  # "contains" | "references" | "depends-on" | "projects"
    label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class BrowserGraphResult:
    workspace_revision: int
    mode: str
    graph: BrowserGraph

@dataclass(frozen=True)
class BrowserGraph:
    schema_version: int  # 1
    nodes: tuple[BrowserGraphNode, ...]
    edges: tuple[BrowserGraphEdge, ...]
```

Node kind mapping from existing Python export:

| Python `build_graph_export` kind | Browser DTO kind | Notes |
|---|---|---|
| `domain` | `domain` | unchanged |
| `model` | `entity` | architecture uses "entity" for all model kinds |
| `model_version` | `version` | |
| `field` | `field` | |
| `projection` | `projection` | unchanged |
| `projection_version` | `version` | version kind reused |
| `projection_field` | `field` | field kind reused |

Edge kind mapping:

| Python edge kind | Browser DTO edge kind |
|---|---|
| `owns` | `contains` |
| `version_of` | `contains` |
| `contains_field` | `contains` |
| `has_projection` | `contains` |
| `version_of_projection` | `contains` |
| `maps_to` | `projects` |

Cross-domain model references produce `depends-on` edges (new).

### Mode filtering

- **Domain mode**: emits `domain`, `entity`, `projection` nodes and their
  `contains`, `depends-on`, and `projects` edges. Version and field nodes are
  excluded.
- **Entity mode**: emits all nodes including `version` and `field`. All edge
  kinds are included.

The Python-side adapter applies the filter before serialization to keep
payloads small for domain-level views.

## Source range attachment

The existing `build_graph_export` does not attach source ranges. Phase 4 adds
optional `source_range` to graph nodes by cross-referencing the workspace's
parsed IR spans. Source ranges use 0-based line/character coordinates
consistent with the browser language protocol.

Nodes without a locatable source span (e.g., implicit workspace nodes) have
`source_range: null`.

## TypeScript graph types

```ts
interface ModelGraphNode {
  id: string;
  kind: 'domain' | 'entity' | 'version' | 'field' | 'projection';
  label: string;
  metadata: Record<string, unknown>;
  source_range: SourceRange | null;
}

interface SourceRange {
  uri: string;
  start_line: number;
  start_character: number;
  end_line: number;
  end_character: number;
}

interface ModelGraphEdge {
  id: string;
  source: string;
  target: string;
  kind: 'contains' | 'references' | 'depends-on' | 'projects';
  label?: string;
  metadata: Record<string, unknown>;
}

interface ModelGraph {
  schema_version: 1;
  nodes: ModelGraphNode[];
  edges: ModelGraphEdge[];
}

interface BrowserGraphResult {
  workspace_revision: number;
  mode: 'domain' | 'entity';
  graph: ModelGraph;
}
```

Type guards follow the same pattern as existing protocol results: check
`schema_version`, array shapes, and node/edge structural fields.

## ELK layout worker

Layout runs in a dedicated web worker using `elkjs/lib/elk.bundled.js`
(the self-contained WASM-free bundle). The worker accepts a `ModelGraph`
and returns positioned nodes and routed edges:

```ts
// layout.worker.ts — message protocol
interface LayoutRequest {
  id: number;
  graph: ModelGraph;
  options: ElkLayoutOptions;
}

interface LayoutResponse {
  id: number;
  positions: Map<string, { x: number; y: number; width: number; height: number }>;
  edgeRoutes: Map<string, { points: { x: number; y: number }[] }>;
}
```

The worker is instantiated once and reused. Layout requests carry an
incrementing ID; stale responses (from an older graph revision) are discarded.

Default ELK options:

- `elk.algorithm`: `layered`
- `elk.direction`: `DOWN`
- `elk.spacing.nodeNode`: `40`
- `elk.layered.spacing.nodeNodeBetweenLayers`: `60`

## React Flow rendering

The visualization panel uses `@xyflow/react` (React Flow v12+). Node and
edge types are registered as custom React components.

### Node components

- **DomainNode**: rounded rectangle, domain name, owner badge, entity/projection
  count.
- **EntityNode**: rectangle, model name, model kind indicator (entity/aggregate/
  event/value), version count badge.
- **VersionNode**: compact rectangle, version number, change kind indicator
  (additive/breaking).
- **FieldNode**: minimal row, field name, type, key/optional indicators.
- **ProjectionNode**: rectangle with a distinct accent, projection name, source
  reference.

### Edge components

- **ContainsEdge**: solid, muted stroke.
- **DependsOnEdge**: dashed, colored stroke indicating cross-domain dependency.
- **ProjectsEdge**: dotted stroke linking projection fields to source fields.

### Interaction

- Pan and zoom (React Flow defaults).
- Minimap (React Flow `<MiniMap />`).
- Node selection highlights the source range in the editor.
- A "Focus" action on a node zooms to fit its subgraph.
- Domain-mode nodes are expandable to reveal their entity/projection children
  without switching to entity mode.

## Editor–graph synchronization

Synchronization is event-driven, not polled:

1. **Graph → Editor**: clicking a graph node with a `source_range` calls
   `editor.revealRange()` and selects the range. If the source file differs
   from the active file, the workspace switches to it first.
2. **Editor → Graph**: when the cursor enters a definition span that
   corresponds to a graph node, that node is highlighted (border accent) and
   optionally panned into view. Matching uses the node's `source_range`
   against the cursor position.

Selection state is stored as a React state containing the selected node ID.
It is never persisted.

## Layout and responsive behavior

Desktop layout (≥ 768px): the visualization panel appears to the right of the
editor, consistent with the architecture's three-column layout. Both panels
are resizable.

Mobile layout (< 768px): the visualization panel appears below the editor in
a tabbed view. The tab switches between "Source" and "Graph."

The visualization panel has a minimum width/height to prevent unusable graph
rendering. When collapsed, it renders nothing (React Flow is unmounted to
free resources).

## Performance budgets

- `workspace.graph` (Python, warm worker): ≤ 200 ms median for the
  conformance fixture.
- ELK layout (web worker): ≤ 500 ms median for a 50-node graph.
- React Flow initial render: ≤ 100 ms after layout completes.
- Graph update after workspace revalidation: ≤ 1000 ms end-to-end
  (graph + layout + render).

Budgets are enforced in the Playwright conformance test.

## Accessibility

- Graph nodes are keyboard-navigable (React Flow's built-in keyboard support).
- Node labels are readable by screen readers.
- Color is not the only distinguishing factor between node kinds — shape and
  icon indicators provide redundant cues.
- The minimap has `aria-hidden="true"` since it duplicates the main graph.
- Focus management returns to the editor when the graph panel is dismissed.

## Security

- No new network requests. ELK.js is bundled; React Flow is bundled.
- Graph data is derived from compiler-owned workspace state and never leaves
  the browser.
- Graph DTOs cross the Pyodide structured-clone boundary with the same
  validation as existing protocol results.
- No `eval`, no dynamic script loading, no relaxation of the existing CSP.

## Testing strategy

### Python unit tests

- `test_browser_graph.py`: test `workspace.graph` dispatch, mode filtering,
  source range attachment, DTO serialization, staleness rejection.
- Extend `test_graph_export.py` with browser DTO adapter coverage.

### TypeScript unit tests

- `protocol.test.ts`: type guard tests for `BrowserGraphResult`.
- `client.test.ts`: `graph()` method dispatch and payload shape.
- `GraphPanel.test.tsx`: graph rendering with mock data, node selection,
  mode switching.

### Playwright conformance tests

- `conformance.spec.ts`: extend the existing conformance test to call
  `workspace.graph` with both modes and verify the result shape.
- Budget test: add `workspace.graph` timing to the performance median
  checks.

### Playwright integration tests

- `playground.spec.ts`: verify graph panel renders nodes for the default
  workspace, node click reveals source, editor cursor highlights graph node.

## Dependency additions

### Python

No new Python dependencies. The existing `build_graph_export` and workspace
infrastructure are sufficient.

### TypeScript (web/package.json)

- `@xyflow/react` (React Flow v12+): graph rendering and interaction.
- `elkjs`: hierarchical graph layout.
- Both are MIT-licensed and have no transitive network dependencies.

## Delivery

Implementation proceeds in two batches:

**Batch A — Protocol and graph data:**
1. Python browser DTO and adapter for `build_graph_export`.
2. `workspace.graph` dispatch handler and Python tests.
3. TypeScript protocol types, type guards, and client method.
4. Playwright conformance test extension.

**Batch B — Layout, rendering, and integration:**
5. ELK layout worker.
6. React Flow node and edge components.
7. Graph panel with mode switching.
8. Editor–graph bidirectional synchronization.
9. Responsive layout and accessibility.
10. Performance budget enforcement.
11. Documentation updates and Phase 4 closeout.
