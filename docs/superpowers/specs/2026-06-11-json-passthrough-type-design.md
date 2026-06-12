# JSON Passthrough Type Design

**Date:** 2026-06-11
**Status:** Approved
**Scope:** A new `json` primitive type in the IDL/IR, supported by the JSON Schema, TypeScript, and Rust emitters (standalone, in `array<json>`, and in `map<K, json>`); plus generated `map<K, json>` ↔ `String` conversions for projection fields carrying `@wire(clickhouse: "string")`, completing the row in `2026-06-08-target-serialization-hints-design.md` (§2, "Closed encoding vocabulary") that anticipated this exact mapping but was never implemented.

## Goal

Let a model author declare a field whose canonical shape is "arbitrary JSON" — i.e. a value that is opaque to Modelable and passed through unchanged — using a new built-in type `json`. This covers fields like `tracing.Span@1.attributes` (today modelled as `string` containing a JSON-encoded object, which loses the "this is a JSON object" semantic and can't drive a faithful API/TypeScript projection).

Once `json` exists as a real type, `attributes: map<string, json>` can:
- Generate `HashMap<String, serde_json::Value>` in Rust and `Record<string, unknown>` in TypeScript for *canonical*-shaped projections (matching Observable's existing `Span`/`SpanEvent` domain structs and `apps/frontend/src/api/traces.ts`).
- Generate `String` (JSON-encoded) for *storage*-shaped projections (`SpanRow`/`SpanEventRow`, matching ClickHouse's lack of a map-of-json column type) via `@wire(clickhouse: "string")`, with Modelable generating the `serde_json::to_string`/`from_str` conversions in the `From` impl — completing the previously-aspirational row in the serialization-hints spec.

## Non-Goals

- Validating or introspecting the *contents* of a `json`-typed field. It is opaque by definition — no schema, no lineage into its internal structure.
- A general "any" escape hatch for non-JSON-serializable values. `json` specifically means "valid JSON value, represented as `serde_json::Value` / `unknown` / `Record<string,unknown>`".
- Changing how `tracing.Span@1.attributes`/`resourceAttributes`/`SpanEvent@1.attributes` are *used* in Observable — this spec only adds the type and conversion machinery to Modelable. The follow-up Observable-side migration (steps 2.4/2.5 of `docs/superpowers/plans/2026-06-08-modelable-type-mapping-migration-plan.md`, plus 3.1/3.2/3.9) is a separate plan, sequenced after this lands and is released.
- Full semantic support in non-Phase-1-required emitters (Go, Java, C#, Python, SQL DDL, LSP semantic tokens). These only need a "doesn't crash, falls back sanely" check (see "Non-required emitters" below).
- New `@wire` encodings beyond completing the existing `clickhouse: "string"` row. No new hint vocabulary is introduced.

## Context

`docs/superpowers/specs/2026-06-08-target-serialization-hints-design.md` already documents the gap (§Context table, row: `attributes: map<string, json>` | `HashMap<String, serde_json::Value>` | `String` (JSON-encoded) | nested JSON object) and its closed-vocabulary table already lists `clickhouse: "string"` applying to `map<K, json>` with the stated Rust behavior ("field type becomes `String` in the row shape; for maps, generated `From` impls call `serde_json::to_string`/`from_str`"). Neither half of that — the `json` type itself, nor the generated conversion — was implemented; that spec's scope was the hint *mechanism*, not this type.

While scoping Observable's migration plan step 2.4 (replacing `TraceResponse`/`FacetValue`/`TraceListResponse` with generated reply-projection types), this gap turned out to be the actual blocker: `tracing.Span@1.attributes`/`resourceAttributes` and `SpanEvent@1.attributes` are modelled as `string` (JSON-encoded, for the storage projection) in `models/tracing.mdl`, but Observable's canonical `Span`/`SpanEvent` domain structs (`libs/domain/src/span.rs`) and the API/TypeScript wire format (`apps/frontend/src/api/traces.ts`: `attributes?: Record<string, unknown>`) use a JSON *object*, not a JSON-encoded string. There is no way to model "this field is a JSON object on the canonical/API side, but a JSON string on the storage side" without a `json` type plus the `clickhouse: "string"` conversion.

This gap is systemic, not specific to tracing: `LogRecord.body: serde_json::Value`, `LogRecord.attributes`/`resource_attributes: HashMap<String, serde_json::Value>` (Logs, migration plan 3.1), `MetricSeries.resource_attributes: HashMap<String, serde_json::Value>` (Metrics, 3.2), and `VisualizationFrame.data: Vec<serde_json::Value>` (NLQ/Visualization, 3.9) all hit the same wall. Solving it once here unblocks all of those, rather than re-deciding the same question on each domain.

## Recommended Approach

### Part 1 — `json` as a built-in primitive type

Add `json` alongside the existing `string`/`int`/`float`/`bool`/`date`/`time`/`timestamp`/`uuid`/`duration`/`binary` primitives.

**Grammar** (`cli/src/modelable/grammar/modelable.lark`, `primitive_type` rule, lines 86-95): add `| "json" -> pt_json`.

**Transformer** (`cli/src/modelable/parser/transformer.py`): add `pt_json(self, _items): return PrimitiveType(kind="json")`, alongside `pt_binary` (line 342).

**IR** (`cli/src/modelable/parser/ir.py`, `PrimitiveType.kind` Literal, lines 150-162): add `"json"` to the literal union.

**JSON Schema emitter** (`cli/src/modelable/emitters/json_schema.py`, `_primitive_to_json_schema`, lines 410-424): add `"json": {}` (the empty schema — matches "any value" in JSON Schema, and is the natural counterpart to TypeScript's `unknown`).

**TypeScript emitter** (`cli/src/modelable/emitters/typescript.py`, `_type_to_ts` mapping dict, lines 226-237): add `"json": "unknown"`. No special-casing needed beyond the dict entry — `MapType`/`ArrayType` branches (lines 241-244) already recurse via `_type_to_ts`, so `map<string, json>` → `Record<string, unknown>` and `array<json>` → `unknown[]` fall out for free.

**Rust emitter** (`cli/src/modelable/emitters/rust.py`):
- `_primitive_to_rust` mapping dict (lines 473-486): add `"json": "serde_json::Value"`. `HashMap`/`Vec` wrapping for map/array shapes (lines 442-461) already recurses through `_shape_annotation`, so `map<string, json>` → `HashMap<String, serde_json::Value>` and `array<json>` → `Vec<serde_json::Value>` fall out for free, matching `libs/domain/src/span.rs`'s hand-written `HashMap<String, serde_json::Value>`.
- `_header_lines` (lines 278-293): add a `serde_json: bool = False` parameter; when true, insert `"// requires: serde_json (https://docs.rs/serde_json)"`, following the existing pattern for `clickhouse`/`sqlx`/`serde_with`/`uuid`.
- New helper `_any_needs_serde_json(field_specs) -> bool`, mirroring `_any_needs_uuid` (lines 487-489): returns true if any field's annotation contains `serde_json::Value` (covers bare, `Vec<...>`, `HashMap<String, ...>`, and `Option<...>` wrappings since it's a substring check on the rendered annotation). Both `_emit_projection` (around line 144, alongside the existing `needs_serde_with`/`needs_uuid` computation) and `_render_struct_definition`'s caller for entity emission must compute this and pass it through to `_header_lines`.

No changes needed to `_shape_annotation`/`_shape_base_annotation` beyond the `_primitive_to_rust` dict entry — `json` behaves like any other primitive at this layer; the `map<K,json>` → `String` *override* for storage projections is Part 2, driven by the wire hint, not by the primitive type itself.

### Part 2 — Generated `map<K, json>` ↔ `String` conversions for `@wire(clickhouse: "string")`

This completes the `clickhouse: "string"` / `map<K, json>` row in the serialization-hints spec's closed vocabulary table (§2, line 78), which today is documented but not implemented (the only conversion `_emit_from_impl` currently generates is `.into()`).

**Threading the clickhouse wire hint to shape annotation** (`cli/src/modelable/emitters/rust.py`):
- `_emit_projection` (lines 107-163): currently passes only `rust_hint=wire.get("rust")` to `_shape_annotation` (line ~133). Add `clickhouse_hint=wire.get("clickhouse")`, threaded through `_shape_annotation` → `_shape_base_annotation` as a new optional parameter (mirroring how `rust_hint` is threaded today).
- `_shape_base_annotation` (lines 399-472): add a new branch, checked before the existing `map` branch (lines 442-449): if `shape.kind == "map"` and `shape.value` is a `json`-kind primitive shape (i.e. `shape.value.kind == "primitive" and shape.value.ref == "json"`) and `clickhouse_hint is not None and getattr(clickhouse_hint, "encoding", None) == "string"`, return `"String"` instead of recursing into `HashMap<String, ...>`. Also handle the bare-`json`-field case (no map wrapper) the same way for symmetry, though Observable's current usage is always `map<string, json>`.
- `_field_specs_from_model_fields` / `_field_specs_from_object_fields` (lines 358-396) are used for entity/object emission, not projections — they have no `clickhouse_row` context and therefore no `clickhouse_hint` to pass; entities keep emitting `HashMap<String, serde_json::Value>` for `map<K, json>` fields regardless of any `@wire(clickhouse: ...)` annotation present on the *entity* field (the hint is only actionable at the projection layer, where the target row shape is known). This matches existing precedent: `@wire(clickhouse: "uuid")` similarly only changes serde attrs on clickhouse-bound projections, not on the entity struct.

**Generated conversion in `_emit_from_impl`** (lines 166-225): currently, for `DirectMapping` fields, emits `{rust_name}: src.{src_rust_name}.into(),` (or `Default::default()` for object-shaped fields, line ~219). Add a third case, checked first: if the *projection* field's resolved shape (via `_shape_annotation` with the same `clickhouse_hint`) is `"String"` **and** the *source* field's shape (the entity's view of the same field, via `_resolve_projection_field_shape`/`TypeShape.from_field_type` without the clickhouse hint) is `map<K, json>` (or bare `json`), emit:

```rust
{rust_name}: serde_json::to_string(&src.{src_rust_name}).unwrap_or_default(),
```

This mirrors the spec's documented intent ("generated `From` impls call `serde_json::to_string`/`from_str`"). The reverse direction (`String` → `map<K, json>`, i.e. `from_str`) is **not** generated in this pass: `_emit_from_impl` only emits `impl From<Entity> for Projection` (entity → row), not the reverse. If/when a row → entity conversion is needed (not required for Observable's current pilot, which only needs entity → `SpanRow`/`SpanEventRow`), it should reuse the same detection logic with `serde_json::from_str(&src.{field}).unwrap_or_default()` — noted here as a natural follow-up, not implemented now (no current caller needs it, and adding unused codegen would violate YAGNI).

`unwrap_or_default()` (→ `"null".to_string()`... actually `String::default()` = `""`, which is *not* valid JSON) is a known rough edge: `serde_json::to_string` on a `HashMap`/`Value` essentially never fails in practice (the only failure mode is non-UTF-8 map keys or non-finite floats, neither of which arise from `serde_json::Value`-typed map values with `String` keys), so `unwrap_or_default()` is dead-code-in-practice but must still typecheck. This matches the existing codebase's tolerance for `unwrap_or_default()` in comparable spots (e.g. `_serde_attrs_for_field`'s `serde_with::rust::display_fromstr` has analogous never-realistically-fails semantics). No change to this behavior is needed — just documenting it so it isn't mistaken for an oversight during review.

**`_serde_attrs_for_field`** (lines 229-248): no change needed. The `clickhouse: "string"` hint for `map<K,json>` doesn't need a `#[serde(with = ...)]` attribute — the field is just a plain `String` in the generated struct, and the value conversion happens in `_emit_from_impl`, not via serde.

### Non-required emitters — fallback verification only

Per `docs/emitter-spec.md` §2, JSON Schema/TypeScript/Markdown are Phase 1 required; Rust is "implemented extra" (§9); Go/Java/C#/Python/SQL DDL/LSP semantic tokens are out of Phase 1 scope entirely. These do not need explicit `json` support, but adding `"json"` to `PrimitiveType.kind` must not make them crash:

- **`sql.py`**: `_PG_PRIMITIVE.get(field_type.kind, "TEXT")` and `_CH_PRIMITIVE.get(field_type.kind, "String")` (lines ~160-240) already have safe defaults — `json` falls back to `TEXT` (Postgres) / `String` (ClickHouse) with no entry needed. Acceptable as-is, same treatment as any other type these dicts don't special-case.
- **`shapes.py`**: `TypeShape.from_field_type` (lines 61-62) wraps any `PrimitiveType` as `kind="primitive", ref=field_type.kind` — `ref="json"` flows through unchanged; no dispatch on the literal value happens here, so nothing to change.
- **go.py / java.py / csharp.py / python.py**: each dispatches on `shape.kind == "primitive"` and then maps `shape.ref` via its own primitive-to-target dict. Verify (as part of implementation, via existing emitter unit tests) that each of these dicts' `.get(...)` calls has a non-crashing default for an unrecognized key — if any uses direct indexing (`dict[key]`, raising `KeyError`) instead of `.get(key, default)`, that's a pre-existing latent bug for *any* unrecognized primitive (not specific to `json`) and should be fixed as a one-line `.get()` defensive default, consistent with `sql.py`'s existing pattern. This is a correctness fix to existing fallback behavior, not new `json`-specific logic.
- **lsp/semantic_tokens.py**: grep for `PrimitiveType.kind` literal-value dispatch; if it enumerates kinds exhaustively (e.g. a `match`/`if-elif` chain with no `else`), add `json` to whatever bucket `string`/`binary` already fall into (both are "opaque scalar" from a token-highlighting perspective). If it's generic (doesn't switch on the literal at all), no change needed.

## Alternatives Considered

| Approach | Trade-off | Decision |
|---|---|---|
| Add `json` primitive type + complete the `clickhouse: "string"`/`map<K,json>` conversion (this spec) | One new type, additive everywhere (empty JSON Schema, `unknown` in TS, `serde_json::Value` in Rust); completes an already-approved-but-unimplemented hint row. Small, well-scoped. | **Chosen.** |
| Model `attributes` as `map<string, string>` (force values to be JSON-encoded strings even at the canonical/API layer) | No new type needed. But changes Observable's actual wire contract (`Record<string, unknown>` → `Record<string, string>`), which is a breaking API change disguised as a modeling convenience — rejected outright. | Rejected. |
| Per-project escape hatch: let Observable hand-write the `attributes`/`resourceAttributes`/etc. fields and exclude them from generated structs entirely (field-level `@manual`, deferred in the prior spec) | Avoids touching Modelable's type system at all. But `@manual` doesn't exist yet (explicitly deferred in `2026-06-08-target-serialization-hints-design.md` Resolved Design Decision #3), and this is exactly the kind of "recreates the same blocking decision on every domain" case the user wants to avoid — it would need re-deciding for Logs, Metrics, and Visualization too. | Rejected — user chose to solve it once at the type-system level (option B in this session's design discussion). |
| Generic `any`/`unknown`-named type instead of `json` | Same mechanism, different name. `json` is more precise about the actual constraint (must be JSON-serializable; `serde_json::Value`/`unknown` are *representations* of "JSON value", not "anything") and matches the existing `@wire(clickhouse: "string")` row's terminology (`map<K, json>`) already present in the approved hints spec. | Rejected in favor of `json` — naming consistency with already-approved spec language. |

## Dependencies / Sequencing Notes

- This spec builds directly on the **approved** `2026-06-08-target-serialization-hints-design.md` — specifically, it implements the `clickhouse: "string"` / `map<K, json>` row of that spec's closed vocabulary table (line 78), which was specified but explicitly left unimplemented. No new hint syntax or vocabulary entries are introduced; `@wire(clickhouse: "string")` is already valid per that spec.
- Part 1 (the `json` type itself) has no dependency on Part 2 and could theoretically ship alone, but Part 2 is the entire reason Observable needs Part 1 (a `json` type with no conversion path to `String` doesn't unblock `SpanRow`/`SpanEventRow`). Both parts ship together in one implementation pass.
- Rust emitter changes (Part 1's `serde_json::Value` mapping, Part 2's conversion generation) fall under the same "Rust is an implemented extra, not formally Phase 1" posture already accepted for the prior spec's Rust-track items (steps 3-5 in that spec's Dependencies/Sequencing) — no additional scope decision needed beyond what that spec already established.
- **Downstream (not part of this spec's implementation):** once this lands and is released/tagged per `docs/consuming-modelable.md`, and Observable bumps its pinned version, Observable can:
  1. Change `models/tracing.mdl`: `tracing.Span@1.attributes`/`resourceAttributes` and `SpanEvent@1.attributes` from `string` to `map<string, json>` (canonical shape, matching `libs/domain/src/span.rs`'s `HashMap<String, serde_json::Value>`).
  2. Add `@wire(clickhouse: "string")` to those fields in `SpanRow@1`/`SpanEventRow@1` projections, so the generated row types keep `attributes: String` (JSON-encoded) as ClickHouse requires, with the `serde_json::to_string` conversion now generated automatically instead of hand-written.
  3. Resume migration plan steps 2.4/2.5 (TraceResponse/FacetValue/TraceListResponse, traces.ts), now that a faithful reply-projection for `Span`/`SpanEvent.attributes` (as `Record<string, unknown>` / `HashMap<String, serde_json::Value>`) is expressible.
  4. Apply the same pattern to Logs (3.1: `LogRecord.body`, `attributes`, `resource_attributes`), Metrics (3.2: `MetricSeries.resource_attributes`), and Visualization (3.9: `VisualizationFrame.data: array<json>`).

## Resolved Design Decisions

1. **Should `json` be representable bare (not just inside `map`/`array`)?**
   - **Decision:** Yes — `field: json` is valid, mapping to `serde_json::Value` / `unknown` / empty JSON Schema directly. This matches `LogRecord.body: serde_json::Value` (a bare field, not a map), so restricting `json` to map/array contexts would leave that case unaddressed.
2. **Reverse conversion (`String` → `map<K,json>`, row → entity) — generate now or defer?**
   - **Decision:** Defer. `_emit_from_impl` only generates entity → projection (`From<Entity> for Row`) today; no caller needs the reverse for the tracing pilot. Documented as a follow-up in Part 2 rather than spec'd in detail, to avoid speculative codegen (YAGNI).
   - **How to apply:** if a future domain needs row → entity (e.g. a read path that reconstructs `Span` from `SpanRow`), extend `_emit_from_impl` (or add a sibling `_emit_into_impl`) using the same shape-detection logic, with `serde_json::from_str(&src.field).unwrap_or_default()`.
3. **Non-required emitters (Go/Java/C#/Python/SQL/LSP) — block on full `json` support?**
   - **Decision:** No. Only verify non-crashing fallback (existing `.get(key, default)` patterns where present; fix any direct-indexing latent bugs found along the way). Full semantic support for these targets is out of scope, consistent with their existing treatment of other types not in the Phase 1 required table.
