# Graph Export Design

**Date:** 2026-05-31  
**Status:** Draft for review  
**Scope:** Deterministic JSON graph export for models, projections, and field mappings

## Goal

Export the normalized `.mdl` workspace graph as a deterministic JSON artifact that can be used for visualisation, inspection, and later renderers such as DOT, SVG, or HTML.

The first slice should expose a useful graph for demo flows without pulling in the full registry, governance, or runtime surface.

## Non-Goals

- Rendering SVG, PNG, or interactive HTML in the first slice.
- Exporting runtime adapters, subscription state, or deployment metadata.
- Exporting package-index, release, or VS Code extension metadata.
- Replacing the existing `compile`, `resolve`, `lineage`, or `registry graph` commands.
- Introducing a new source of truth outside the normalized workspace graph.

## Context

Modelable already has a normalized workspace graph in the CLI compiler:

- domains own models and projections,
- model versions contain fields and change kinds,
- projection versions contain source references and field mappings,
- registry compilation already derives lineage and compatibility data from the same graph.

That makes graph export a natural compiler-phase artifact, not a runtime feature and not a separate graph model.

The first slice should provide a machine-readable graph that is easy to diff, easy to test, and easy to render later. Human-readable visualization can be layered on top of the same export shape.

## Recommended Approach

Use a canonical JSON graph export as the first slice.

### Why this approach

- It keeps the extraction logic deterministic and renderer-agnostic.
- It gives a useful artifact for demos and tests immediately.
- It can feed DOT/SVG/HTML renderers later without changing the core graph shape.

### Alternatives considered

| Approach | Trade-off | Decision |
|---|---|---|
| Direct DOT export | Fast to visualise, but hard to extend as a canonical artifact. | Rejected for the first slice. |
| JSON graph export | Structured, deterministic, and easy to test. | Chosen. |
| JSON + DOT together | Good UX, but broader than the first slice needs. | Deferred. |

## CLI Shape

The first slice should add a new graph export command family:

```text
modelable graph export SOURCE [--path PATH] [--out FILE] [--focus REF]
```

### Semantics

- `SOURCE` can be a workspace path or a `.mdl` file/directory, matching existing CLI source discovery conventions.
- `--out` writes JSON to disk.
- `--focus` is optional and narrows the exported subgraph around a model or projection reference.
- Without `--focus`, the export includes the whole workspace graph.
- The command prints a concise success message and does not mutate source files.

### Suggested demo flows

```text
modelable graph export ../samples/mvp --out ./dist/mvp-graph.json
modelable graph export ../samples/scenarios/09-auto-projections --focus customer.Customer@1 --out ./dist/customer-graph.json
modelable graph export ./models --focus billing.BillingCustomer@1 --out ./dist/billing-graph.json
```

These flows demonstrate:

- a workspace overview,
- a focused model view,
- a focused projection view.

## Export Shape

The JSON export should have two top-level collections:

- `nodes`
- `edges`

### Node types

The first slice should include these node kinds:

- `domain`
- `model`
- `model_version`
- `projection`
- `projection_version`
- `field`
- `projection_field`

### Edge types

The first slice should include these edge kinds:

- `owns`
- `version_of`
- `contains_field`
- `has_projection`
- `version_of_projection`
- `maps_to`

### Core fields

Every node should include:

- `id`
- `kind`
- `label`

Selected nodes should also include:

- `domain`
- `name`
- `version`
- `change_kind`
- `optional`
- `source_ref`
- `target_ref`

The export should keep enough metadata to reconstruct a useful diagram, but not so much that it duplicates the full registry database.

## Focus Rules

`--focus` should keep the export readable and bounded.

Recommended focus behavior:

- If the focus is a model version, include the model, its version, its fields, and projections that reference it.
- If the focus is a projection version, include the projection, its source model/version, its fields, and the mapped source fields.
- Include one-hop neighbors needed to preserve the graph structure.
- Do not recursively include unrelated workspace data.

This keeps demo exports small enough for visual inspection while still showing useful relationships.

## Determinism

The export must be deterministic for the same workspace inputs.

Requirements:

- stable node ordering,
- stable edge ordering,
- stable identifier generation,
- stable JSON formatting,
- no timestamps,
- no host-specific file paths.

Stable ordering should follow the existing normalized workspace order:

- domains by declaration order,
- models by declaration order,
- versions by version number,
- fields by source order,
- projection mappings by field order.

## Validation and Error Handling

The export command should fail clearly when:

- the source path cannot be loaded as a valid workspace,
- the focus ref does not exist,
- the workspace contains duplicate or unresolved definitions that prevent graph construction,
- the export path cannot be written.

If the source workspace is valid but the focus is too narrow to include useful context, the command should still succeed and export the smallest valid subgraph.

## Relationship to Existing Commands

This slice should stay separate from:

- `compile` — builds the registry and artifact outputs,
- `lineage` — prints lineage for a single ref,
- `registry graph` — prints federation topology,
- `lineage export` — exports lineage as NDJSON for catalog ingestion.

The graph export command is specifically for visual exploration of the normalized model/projection graph.

## Testing Strategy

Add tests that prove:

- the JSON graph export is deterministic,
- the export includes the expected node and edge kinds,
- focused exports include the requested subgraph and immediate context,
- invalid focus refs fail with a clear error,
- the export remains stable across repeated runs.

Suggested test coverage:

```python
def test_graph_export_writes_deterministic_json(tmp_path):
    ...

def test_graph_export_focuses_on_projection_and_source_fields(tmp_path):
    ...

def test_graph_export_rejects_unknown_focus_ref(tmp_path):
    ...
```

## Risks

- Over-expanding the graph can make demo outputs noisy and difficult to interpret.
- A too-loose schema would make later renderers harder to implement consistently.
- Duplicating registry concepts in the export shape would create maintenance drift.

## Open Decisions

- Whether the first renderer should be DOT generation layered on top of this JSON export.
- Whether node IDs should be opaque or human-readable.
- Whether the command should live under `graph export` or a more generic `export graph` family in the final CLI.

## Success Criteria

This design is complete when the repository can:

- export the normalized workspace graph as deterministic JSON,
- focus that export around a specific model or projection,
- and use the exported data as the basis for later graph visualisations.
