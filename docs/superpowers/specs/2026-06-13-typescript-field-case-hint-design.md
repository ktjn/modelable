# TypeScript Field-Name Case Hint Design

**Date:** 2026-06-13
**Status:** Approved
**Scope:** A new `@wire(json.fieldCase: "<case>")` hint, attachable to a model or projection declaration, that controls the field-name casing the TypeScript emitter uses for that declaration's generated interface.

## Context

Modelable's IDL convention is camelCase field names (e.g. `spanId`, `startTimeUnixNano`). The Rust emitter unconditionally converts these to snake_case Rust struct fields via `_snake_case()` (`cli/src/modelable/emitters/rust.py`), and Rust's `serde` default (no `rename_all`) serializes those snake_case field names verbatim to JSON — so the real wire format for a Rust-backed model is snake_case (`span_id`, `start_time_unix_nano`).

The TypeScript emitter (`cli/src/modelable/emitters/typescript.py`) currently emits `field.name` verbatim from the `.mdl` source — i.e. camelCase. For a model with a Rust backend using default serde casing, this produces TS interfaces whose field names do **not** match the actual JSON the API returns.

This was identified while scoping Observable's adoption of modelable for `apps/frontend/src/api/traces.ts`: `tracing.Span@1`/`tracing.SpanEvent@1` declare camelCase fields, but the real API response (from `libs/domain/src/span.rs`, snake_case structs, default serde) is snake_case.

## Goal

Let a model/projection author declare, in `.mdl`, that the TypeScript emitter should rename all of that declaration's fields to a given case convention — without changing the canonical `.mdl` field names, the Rust output, lineage, or JSON Schema output.

## Non-Goals

- Changing Rust, JSON Schema, SQL, or lineage output — this hint is TypeScript-emitter-only.
- A per-field rename/override escape hatch — not needed for the motivating case (mechanical camelCase→snake_case covers all fields of `tracing.Span@1`/`tracing.SpanEvent@1`). Deferred until a real irregular case appears.
- Reusing or extending `@wire(json.case: ...)` — that hint is already validated as enum-value-casing, field-level-only. The new hint is a distinct name (`json.fieldCase`) at a distinct attachment point (model/projection-level), avoiding semantic overload.
- Automatic inference (e.g. "always snake_case for Rust-backed models") — author-declared, consistent with the existing wire-hint philosophy (`docs/superpowers/specs/2026-06-08-target-serialization-hints-design.md`).

## Design

### 1. Syntax

`@wire(json.fieldCase: "<case>")` may appear immediately before a model declaration (`entity`/`aggregate`/`value`/`event`) or a projection declaration:

```mdl
@wire(json.fieldCase: "snake_case")
entity Span @ 1 (additive) {
  @key spanId: string
  traceId: string
  startTimeUnixNano: int
  attributes: map<string, json>
  ...
}
```

This is a new grammar position — today `@wire` (and all other annotations) only attach to individual fields via `field_decl`.

A projection does not automatically inherit its source model's `json.fieldCase`; if a projection's own TypeScript output also needs renamed fields, it declares the hint itself.

### 2. Closed vocabulary

`json.fieldCase` accepts the same case-name vocabulary already validated for `rust.case` (`_VALID_RUST_CASE_VALUES` in `cli/src/modelable/validation/semantic.py`: `snake_case`, `SCREAMING_SNAKE_CASE`, `camelCase`, `PascalCase`, `kebab-case`, `lowercase`, `UPPERCASE`), but only the subset `_apply_case` (`cli/src/modelable/emitters/typescript.py`) actually implements today: `snake_case`, `SCREAMING_SNAKE_CASE`, `camelCase`, `PascalCase`. Values outside `_apply_case`'s implemented set are a validation error with a "valid values are..." message, matching the existing `rust.case` validation style. Extending `_apply_case` to cover `kebab-case`/`lowercase`/`UPPERCASE` is not part of this change (no current consumer needs them).

### 3. IR changes (`cli/src/modelable/parser/ir.py`)

- `WireTargetHint` gains an optional `field_case: str | None = None`, populated from `json.fieldCase`.
- `ModelVersion` and `ProjectionVersion` gain `annotations: list[Annotation] = []` (mirroring `FieldDef.annotations`), populated by the parser from `@wire(...)` annotations preceding the declaration.

### 4. Grammar / transformer changes

- Extend the grammar rules for `model_decl` and `projection_decl` to accept leading `@wire(...)` annotations (reusing the existing `ann_wire` rule used by `field_decl`), and thread them into `ModelVersion.annotations` / `ProjectionVersion.annotations` in `transformer.py`.

### 5. Validation (`cli/src/modelable/validation/semantic.py`)

- `json.fieldCase` is valid **only** on model/projection-level `@wire` annotations. A field-level `@wire(json.fieldCase: ...)` is a semantic error (mirroring the existing "json.case / json.overrides are valid JSON modifiers but only on enum fields" check, but for attachment-point rather than field-kind).
- `json.fieldCase` value must be in `_apply_case`'s implemented set (see §2); otherwise a semantic error listing valid values.
- `json.case` / `json.overrides` validation is unchanged — still field-level, enum-only. No interaction between the two hints.

### 6. TypeScript emitter changes (`cli/src/modelable/emitters/typescript.py`)

In `_emit_model` and `_emit_projection`:
- Resolve the declaration's own `json.fieldCase` once via `wire_targets_from_annotations(version.annotations)`.
- For each field, the emitted property name is `_apply_case(field.name, field_case)` if `field_case` is set, else `field.name` (current behavior — fully backward compatible for declarations without the annotation).
- `export type X = InterfaceName` aliases and interface/type names (`_stable_interface_name`) are unaffected — only the *property names inside* the interface change.

### 7. JSON Schema / Rust / SQL / lineage

Unaffected. `json.fieldCase` is consumed only by the TypeScript emitter, consistent with the existing precedent that `json.case` (enum-value casing) is also TS-only and not reflected in JSON Schema's `enum` arrays.

## Testing

- `cli/tests/test_emit_typescript.py`:
  - New test: `@wire(json.fieldCase: "snake_case")` on a model renames all interface fields to snake_case.
  - New test: a projection with its own `json.fieldCase`, independent of its source model.
  - New test: a model without the annotation is unchanged (regression coverage alongside the existing four enum-case/json-wire tests).
  - New test: invalid `json.fieldCase` value is rejected (or covered in `test_semantic.py`).
- `cli/tests/test_semantic.py`:
  - Field-level `@wire(json.fieldCase: ...)` is rejected.
  - Model-level `@wire(json.fieldCase: "not-a-real-case")` is rejected with a "valid values are..." message.
  - Model-level `@wire(json.fieldCase: "snake_case")` passes.
- End-to-end: compile a `tracing.Span@1`-shaped fixture (mirroring Observable's actual model) with `@wire(json.fieldCase: "snake_case")` and assert the generated `.ts` interface's field names are the expected snake_case set, matching the real JSON wire format.

## Verification

- `uv run pytest cli/tests/ -q` — full suite passes, including new tests above.
- `uv run modelable validate` / `compile --target typescript` against a fixture using the new hint.
- No changes to Rust/JSON-Schema/SQL golden outputs for existing fixtures (regression check).
