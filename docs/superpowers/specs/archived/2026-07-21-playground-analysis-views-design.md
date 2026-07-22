# 2026-07-21 Playground Analysis Views — Design

## Status

Accepted on 2026-07-21.

Execution is broken into reviewable tasks in the
[Playground Analysis Views implementation plan](../plans/2026-07-21-playground-analysis-views.md).

This specification defines Phase 5 of the
[Modelable Playground Architecture](../../playground-design.md). It builds on
the shipped visualization MVP (domain/entity graph views, ELK layout, React
Flow rendering) and adds field-level lineage visualization, compatibility
visualization, governance views, and SVG/PNG diagram export.

## Context

The Playground renders compiler-owned semantic graphs through `workspace.graph`
with domain and entity visualization modes. The graph panel supports mode
switching, responsive layout, keyboard navigation, and performance budgets.

The Python CLI already has three analysis engines with clean public APIs:

- **Lineage** (`modelable.planner.lineage`): `build_projection_lineage` traces
  each projection field to its source model field(s), distinguishing direct
  mappings from computed (CEL) expressions.
- **Compatibility** (`modelable.compat`): `check_model_version_compatibility`
  diffs two model versions and classifies changes as breaking or compatible.
  `find_projection_dependents` and `analyze_impact` trace downstream effects.
- **Governance** (`modelable.governance`): `build_projection_governance_findings`
  checks access grants, derivation policies, PII preservation, and
  classification metadata.

None of these are wired to the browser compiler protocol. The browser has no
DTO counterparts, no dispatch methods, and no visualization components for
analysis data.

## Goals

- Add `workspace.lineage`, `workspace.compatibility`, and
  `workspace.governance` browser compiler protocol methods.
- Create browser DTOs that serialize analysis results for structured-clone
  transfer across the Pyodide boundary.
- Render three new visualization modes in the graph panel: lineage,
  compatibility, and governance.
- Add SVG and PNG export for all graph visualization modes.
- Reuse the existing ELK layout worker and React Flow infrastructure.
- Preserve the static, local-only, same-origin deployment and existing
  conformance, performance, and security gates.

## Non-goals

This phase does not include:

- cross-workspace or cross-file-system lineage stitching;
- target-specific compatibility visualization (Protobuf/gRPC wire compat);
- interactive governance policy editing;
- WebLLM, model downloads, or AI-generated analysis (Phase 6);
- service-worker installation or offline caching (Phase 7);
- plugin contracts or additional visualization modes (Phase 8);
- persisting analysis results or graph layouts in IndexedDB; or
- changing Modelable parsing, validation, formatting, compilation, registry,
  or compatibility semantics.

## Chosen approach

Wire the three existing Python analysis engines to the browser compiler
protocol as new methods. Each method returns a self-contained result DTO that
the TypeScript layer converts to React Flow nodes and edges for rendering in
the existing graph panel. Graph export uses `html2canvas` or React Flow's
built-in viewport utilities for PNG, and SVG serialization of the React Flow
viewport for SVG.

This approach was selected over:

- building TypeScript-side analysis from parsed AST, which would duplicate
  semantic inference that the Python compiler already owns; and
- returning raw analysis data and rendering outside React Flow, which would
  fragment the visualization UX.

## Architecture decision scope

No ADR change is required. The
[Playground Architecture](../../playground-design.md#10-visualization-architecture)
already names field lineage, compatibility, and governance as visualization
modes, assigns analysis to the Python compiler, layout to ELK.js, and
rendering to React Flow. This specification makes the Phase 5 protocol, DTO,
and rendering contracts executable.

## Protocol extensions

### `workspace.lineage` method

Request payload:

```json
{
  "workspaceRevision": 100
}
```

Response payload:

```json
{
  "ok": true,
  "result": {
    "workspace_revision": 100,
    "projections": [
      {
        "domain": "billing",
        "projection": "BillingCustomer",
        "version": 1,
        "fields": [
          {
            "field_name": "billingCustomerId",
            "kind": "direct",
            "lineage": ["customer.Customer@2.customerId"],
            "expression": null
          },
          {
            "field_name": "isBillable",
            "kind": "computed",
            "lineage": ["customer.Customer@2.status"],
            "expression": "c.status == \"active\""
          }
        ]
      }
    ]
  }
}
```

The compiler iterates all projection versions in the workspace and builds
lineage for each. The result is a flat list — no graph structure — because
lineage is a per-field derivation chain, not a navigable graph.

### `workspace.compatibility` method

Request payload:

```json
{
  "workspaceRevision": 100
}
```

Response payload:

```json
{
  "ok": true,
  "result": {
    "workspace_revision": 100,
    "reports": [
      {
        "domain_name": "customer",
        "model_name": "Customer",
        "from_version": 1,
        "to_version": 2,
        "status": "compatible",
        "findings": ["added_field email", "added_field status"],
        "changes": [
          {
            "kind": "added_field",
            "field_name": "email",
            "to_optional": true,
            "to_type": "\"string\""
          }
        ]
      }
    ],
    "impacts": [
      {
        "domain_name": "billing",
        "projection_name": "BillingCustomer",
        "version": 1,
        "status": "compatible",
        "reason": null
      }
    ]
  }
}
```

The compiler generates compatibility reports for every pair of consecutive
published versions of every model in the workspace. For each breaking report,
it also computes projection impact for all downstream dependents.

### `workspace.governance` method

Request payload:

```json
{
  "workspaceRevision": 100
}
```

Response payload:

```json
{
  "ok": true,
  "result": {
    "workspace_revision": 100,
    "findings": [
      {
        "code": "missing_project_grant",
        "subject": "billing.BillingCustomer@1",
        "message": "billing.BillingCustomer@1 has no documented project grant"
      }
    ]
  }
}
```

The compiler iterates all projection versions and aggregates governance
findings into a flat list.

## Browser DTOs

### Lineage DTOs

```python
@dataclass(frozen=True)
class BrowserFieldLineage:
    field_name: str
    kind: str  # "direct" | "computed"
    lineage: tuple[str, ...]
    expression: str | None = None

@dataclass(frozen=True)
class BrowserProjectionLineage:
    domain: str
    projection: str
    version: int
    fields: tuple[BrowserFieldLineage, ...]

@dataclass(frozen=True)
class BrowserLineageResult:
    workspace_revision: int
    projections: tuple[BrowserProjectionLineage, ...]
```

### Compatibility DTOs

```python
@dataclass(frozen=True)
class BrowserFieldChange:
    kind: str
    field_name: str
    previous_name: str | None = None
    replacement: str | None = None
    from_optional: bool | None = None
    to_optional: bool | None = None
    from_type: str | None = None
    to_type: str | None = None

@dataclass(frozen=True)
class BrowserCompatibilityReport:
    domain_name: str
    model_name: str
    from_version: int
    to_version: int
    status: str  # "breaking" | "compatible"
    findings: tuple[str, ...]
    changes: tuple[BrowserFieldChange, ...]

@dataclass(frozen=True)
class BrowserProjectionImpact:
    domain_name: str
    projection_name: str
    version: int
    status: str  # "broken" | "affected" | "compatible"
    reason: str | None = None

@dataclass(frozen=True)
class BrowserCompatibilityResult:
    workspace_revision: int
    reports: tuple[BrowserCompatibilityReport, ...]
    impacts: tuple[BrowserProjectionImpact, ...]
```

### Governance DTOs

```python
@dataclass(frozen=True)
class BrowserGovernanceFinding:
    code: str
    subject: str
    message: str

@dataclass(frozen=True)
class BrowserGovernanceResult:
    workspace_revision: int
    findings: tuple[BrowserGovernanceFinding, ...]
```

## TypeScript types

```ts
// Lineage
interface BrowserFieldLineage {
  field_name: string;
  kind: 'direct' | 'computed';
  lineage: string[];
  expression: string | null;
}

interface BrowserProjectionLineage {
  domain: string;
  projection: string;
  version: number;
  fields: BrowserFieldLineage[];
}

interface BrowserLineageResult {
  workspace_revision: number;
  projections: BrowserProjectionLineage[];
}

// Compatibility
interface BrowserFieldChange {
  kind: string;
  field_name: string;
  previous_name: string | null;
  replacement: string | null;
  from_optional: boolean | null;
  to_optional: boolean | null;
  from_type: string | null;
  to_type: string | null;
}

interface BrowserCompatibilityReport {
  domain_name: string;
  model_name: string;
  from_version: number;
  to_version: number;
  status: string;
  findings: string[];
  changes: BrowserFieldChange[];
}

interface BrowserProjectionImpact {
  domain_name: string;
  projection_name: string;
  version: number;
  status: string;
  reason: string | null;
}

interface BrowserCompatibilityResult {
  workspace_revision: number;
  reports: BrowserCompatibilityReport[];
  impacts: BrowserProjectionImpact[];
}

// Governance
interface BrowserGovernanceFinding {
  code: string;
  subject: string;
  message: string;
}

interface BrowserGovernanceResult {
  workspace_revision: number;
  findings: BrowserGovernanceFinding[];
}
```

Type guards follow the same structural validation pattern as existing protocol
results.

## Visualization rendering

### Lineage mode

Renders field-level derivation chains as a directed graph:

- **Source field nodes** (left): model fields referenced in lineage chains,
  grouped by model version. Node kind: `field`.
- **Projection field nodes** (right): projection output fields. Node kind:
  `field`.
- **Edges**: `derived-from` edges from projection fields to source fields.
  Direct mappings use solid edges; computed mappings use dashed edges with the
  CEL expression as edge label.
- **Layout**: ELK `layered` algorithm with `LEFT_TO_RIGHT` direction.

Lineage data is not a graph DTO — it is a flat per-projection result. The
TypeScript visualization layer converts `BrowserLineageResult` to React Flow
nodes and edges for rendering.

### Compatibility mode

Renders version-to-version field changes as a visual diff:

- **Version pair header**: `Model@V1 → Model@V2` with status badge
  (compatible/breaking).
- **Field change nodes**: one node per `FieldChange`, colored by change kind
  (green = added, red = removed, yellow = changed, blue = renamed).
- **Impact nodes**: downstream projection impacts shown as connected nodes
  with status badges (broken/affected/compatible).
- **Layout**: ELK `layered` algorithm with `DOWN` direction.

When the workspace has no consecutive published versions, the compatibility
mode shows an empty state.

### Governance mode

Renders governance findings as a list-style view within the graph panel:

- **Finding nodes**: one node per `GovernanceFinding`, grouped by subject
  (projection version). Each node shows the finding code as a badge and the
  full message.
- **Subject group nodes**: collapsible containers grouping findings by
  projection version.
- **Layout**: ELK `layered` algorithm with `DOWN` direction.

When the workspace has no projections or no findings, the governance mode
shows an empty state.

### Empty states

All three analysis modes show a descriptive empty state when the workspace
lacks the data they need:

- Lineage: "No projections in workspace. Add a projection to see field
  lineage."
- Compatibility: "No consecutive model versions. Add multiple versions of a
  model to see compatibility analysis."
- Governance: "No governance findings. Add projections with access or
  classification metadata to see governance analysis."

## SVG and PNG export

Export is available for all visualization modes (domain, entity, lineage,
compatibility, governance).

### SVG export

Uses React Flow's `toSVG()` viewport utility to serialize the current graph
view. The exported SVG includes:

- All visible nodes and edges with their current styles.
- A generated timestamp comment (only when explicitly enabled via UI toggle).
- No workspace source content embedded.

### PNG export

Uses React Flow's `toSVG()` followed by rendering the SVG to a canvas via
`Image` + `canvas.toDataURL('image/png')`. This avoids external dependencies.

### Export UI

An export button group in the graph panel toolbar offers "Export SVG" and
"Export PNG". Both trigger an immediate browser download using a generated
filename: `modelable-{mode}-{timestamp}.{svg|png}`.

## Conformance fixture extension

The existing `single-valid.mdl` conformance fixture has one domain, one entity,
one version, no projections, and no governance metadata. Analysis views require
richer fixtures.

Add a new conformance scenario `analysis-views` with a multi-file workspace
that includes:

- Two domains with cross-domain references.
- At least one model with two consecutive published versions (for
  compatibility analysis).
- At least one projection with direct and computed field mappings (for lineage
  analysis).
- Fields with `@pii` and `@classification` metadata (for governance analysis).

This fixture is used by both the Python conformance tests and the Playwright
browser tests.

## Performance budgets

- `workspace.lineage` (Python, warm worker): ≤ 200 ms median for the
  analysis-views fixture.
- `workspace.compatibility` (Python, warm worker): ≤ 200 ms median.
- `workspace.governance` (Python, warm worker): ≤ 200 ms median.
- Analysis view ELK layout: ≤ 500 ms median for a 50-node graph.
- Analysis view React Flow render: ≤ 100 ms after layout completes.
- SVG export: ≤ 500 ms for the analysis-views fixture.
- PNG export: ≤ 1000 ms for the analysis-views fixture.

Budgets are enforced in the Playwright conformance test.

## Accessibility

- All analysis view nodes are keyboard-navigable.
- Node labels and finding messages are readable by screen readers.
- Color is not the only distinguishing factor between change kinds or finding
  severities — text labels, icons, and border styles provide redundant cues.
- Empty states are announced to screen readers.
- Export buttons have descriptive labels.
- `prefers-reduced-motion` support carries forward from the visualization MVP.

## Security

- No new network requests. All analysis runs locally in the compiler worker.
- Analysis data is derived from compiler-owned workspace state and never
  leaves the browser.
- SVG and PNG exports contain only rendered graph content — no source text,
  credentials, or workspace metadata are embedded.
- No `eval`, no dynamic script loading, no relaxation of the existing CSP.

## Testing strategy

### Python unit tests

- `test_browser_lineage.py`: test `workspace.lineage` dispatch, DTO
  serialization, direct/computed field lineage, empty workspace.
- `test_browser_compatibility.py`: test `workspace.compatibility` dispatch,
  report generation, impact analysis, empty workspace.
- `test_browser_governance.py`: test `workspace.governance` dispatch,
  finding aggregation, empty workspace.

### TypeScript unit tests

- `protocol.test.ts`: type guard tests for lineage, compatibility, and
  governance results.
- `client.test.ts`: new method dispatch and payload shape tests.
- Visualization component tests for new node types and analysis renderers.

### Playwright conformance tests

- `conformance.spec.ts`: extend with `workspace.lineage`,
  `workspace.compatibility`, and `workspace.governance` calls on the
  analysis-views fixture; verify result shapes.
- Budget tests: add timing assertions for all three analysis methods.

### Playwright integration tests

- `playground.spec.ts`: verify analysis mode tabs render, mode switching
  works, export buttons produce downloads, empty states appear for minimal
  workspaces.

## Dependency additions

### Python

No new Python dependencies.

### TypeScript (web/package.json)

No new TypeScript dependencies. SVG/PNG export uses React Flow's built-in
`toSVG()` and the browser Canvas API.

## Delivery

Implementation proceeds in three batches:

**Batch A — Protocol and analysis data (lineage, compatibility, governance):**
1. Python browser DTOs for all three analysis results.
2. Python browser adapters calling existing analysis engines.
3. Dispatch handlers and `BrowserCompiler` API methods.
4. Python unit tests for all three analysis methods.
5. TypeScript protocol types, type guards, and client methods.
6. Conformance fixture and test extension.

**Batch B — Visualization rendering:**
7. Lineage view: TypeScript converter and React Flow rendering.
8. Compatibility view: TypeScript converter and React Flow rendering.
9. Governance view: TypeScript converter and React Flow rendering.
10. Mode tab extension in graph panel.
11. Empty states and accessibility.

**Batch C — Export and integration:**
12. SVG and PNG export implementation.
13. Export UI in graph panel toolbar.
14. Playwright integration tests.
15. Performance budget enforcement.
16. Documentation updates and Phase 5 closeout.
