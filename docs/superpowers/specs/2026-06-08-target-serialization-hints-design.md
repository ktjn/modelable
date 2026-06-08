# Target Serialization Hints Design

**Date:** 2026-06-08  
**Status:** Draft for review  
**Scope:** Per-field/per-type annotations that let the **JSON Schema emitter** (and, where the consuming project's needs extend beyond approved Phase 1 scope, the Rust emitter — see the scope note in Dependencies/Sequencing) produce wire-compatible artifacts for an adopting project's existing contracts, plus the minimal projection-mapping support those contracts require. TypeScript output follows automatically because it is generated *from* JSON Schema (`docs/emitter-spec.md` §7) — there is no independent "TypeScript emitter" decision to make for these hints.

## Goal

Let a model author declare, in `.mdl`, how a field's *canonical* shape should be represented on the wire for a given target/layer (JSON transport, ClickHouse storage, Postgres storage), so the JSON Schema emitter — and, for targets outside today's approved scope, a Rust emitter — can generate wire-compatible artifacts (`serde`/`sqlx`/`clickhouse`-compatible code on the Rust side) without the consuming project hand-writing any of it. The projection layer expresses the conversions between those representations.

This was identified as a hard blocker while scoping adoption of Modelable in an external Rust + TypeScript project ("Observable"). Two separate gaps exist, with two different scope statuses:
- **In approved Phase 1 scope:** the JSON Schema emitter has no way to say "represent this `int` field as a JSON string" — needed for Observable's nanosecond-timestamp convention (ADR-030) — and IDL decorators (`docs/idl-design-spec.md`) are governance-only (`@key`, `@pii`, `@owner`, …), with no per-field wire-encoding mechanism at all.
- **Outside approved Phase 1 scope (needs a scope decision first):** Observable also needs `sqlx::FromRow`/`clickhouse::Row`-compatible Rust output and SQL DDL — today's Rust emitter only emits bare `#[derive(Debug, Clone, PartialEq)] pub struct` shapes (`cli/src/modelable/emitters/rust.py`), Rust isn't in the Phase 1 required-target table (`docs/emitter-spec.md` §2), and SQL DDL is explicitly deferred to Phase 5 there.

This spec proposes a hint mechanism that covers both; which parts of it get implemented now versus after a scope decision is addressed in Dependencies/Sequencing below.

## Non-Goals

- A general-purpose transformation/scripting language beyond what CEL (`docs/cel-integration-spec.md`) already provides for projection `ComputedMapping`.
- Automatic inference of wire formats from usage (e.g. scanning a consumer's existing structs). Hints are author-declared.
- Solving every possible custom encoding. Some conversions are project-specific enough that the right answer is an escape hatch, not a built-in.
- Changing how governance decorators (`@pii`, `@key`, etc.) work.

## Context: concrete requirements pulled from a real adopting codebase

Observable's `libs/domain/src/span.rs` and `metric.rs` show that "type mapping" between a canonical domain type and its storage row is **not** a 1:1 shape mapping — the same logical field has up to three different wire representations:

| Field (canonical) | Domain (Rust) | ClickHouse row | JSON API response |
|---|---|---|---|
| `tenant_id: uuid` | `Uuid` | `Uuid` with `#[serde(with = "clickhouse::serde::uuid")]` | plain JSON string (serde default) |
| `start_time_unix_nano: int` (nanosecond timestamp; the IDL's only integer type is the 64-bit `int` — Rust represents it as `u64` because nanosecond-since-epoch values are always non-negative, which is itself a target-specific representation choice, not a canonical-type distinction) | `u64` | `u64` (`UInt64` column) | **JSON string** `"1746274719123456789"` — a bare 64-bit integer would lose precision past 2^53 (see ADR-030, `spec/adr/ADR-030-timestamp-representation.md`) |
| `span_kind: enum(internal, server, client, producer, consumer)` | Rust enum | plain `String`, encoded as `"INTERNAL"` / `"SERVER"` / … (**SCREAMING_SNAKE_CASE**, irregular relative to the enum's own member names) | Rust enum, serde default (its own casing rule) |
| `metric_type: enum(gauge, sum, histogram, exponentialHistogram, summary)` | Rust enum | plain `String`, `snake_case` (the valid `serde(rename_all)` value — not `lower_snake_case`, which is not a real serde case style), with the *member name* `exponential_histogram` spelled out (not derivable from `format!("{:?}", …)`-style mechanical casing of `ExponentialHistogram` → `exponentialhistogram`) | Rust enum |
| `is_monotonic: bool?` | `Option<bool>` | `Option<u8>` (0/1) | `Option<bool>` |
| `attributes: map<string, json>` | `HashMap<String, serde_json::Value>` | `String` (JSON-encoded blob, because ClickHouse has no native map-of-json column type Observable uses here) | nested JSON object |

Two distinct kinds of gap fall out of this table:

1. **Mechanical, declarable wire-format switches** — same logical value, different physical encoding, expressible as a fixed rule once you know the target: UUID-as-string-via-clickhouse-serde, 64-bit-integer-as-JSON-string, bool-as-u8, regular enum case conversion (`SCREAMING_SNAKE_CASE`, `snake_case` — using serde's actual `rename_all` vocabulary, not invented case names). These are exactly what *hints* should cover.
2. **Irregular, value-specific transforms** — `exponential_histogram` not following the mechanical casing rule, JSON-blob encode/decode of a whole map. These cannot be captured by a static per-field hint; they need either an explicit lookup table in the hint, or to be left to projection-level `ComputedMapping` (CEL) / a named escape hatch to hand-written conversion code.

Any design that only solves case 1 will still leave adopting projects hand-writing `From`/`Into` impls for case 2 — which is most of the actual mapping logic in Observable's domain layer today. The design must say, explicitly, which case each mechanism covers, and name the escape hatch for case 2 rather than silently failing to generate correct code.

## Recommended Approach

Introduce a small, closed set of **wire-format hints**, namespaced by target, attached at the field level (with type-level defaults where it makes sense, e.g. "all `uuid` fields in this projection use clickhouse uuid encoding"). Keep them declarative and validated, not arbitrary code.

### 1. Hint annotation syntax (IDL)

Extend the existing `@decorator` grammar (it already supports arguments, e.g. `@classification("restricted")`) with a reserved, target-namespaced family that the validator recognizes as wire-format hints rather than governance metadata:

```mdl
entity Span @ 1 (additive) {
  @key spanId: string
  @wire(json: "string", rust.type: "u64") startTimeUnixNano: int
  @wire(clickhouse: "uuid") tenantId: uuid
  @wire(clickhouse: "string", rust.case: "SCREAMING_SNAKE_CASE") spanKind: enum(internal, server, client, producer, consumer)
  @wire(clickhouse: "string", rust.case: "snake_case", rust.overrides: { exponentialHistogram: "exponential_histogram" })
  metricType: enum(gauge, sum, histogram, exponentialHistogram, summary)
  @wire(clickhouse: "u8") isMonotonic?: bool
}
```

Note: the IDL's only integer type is the 64-bit `int` (`docs/idl-design-spec.md` §built-in types — there is no separate `int64`/`uint64`). Rust's signedness choice (`u64` vs `i64`) is therefore *itself* a target-representation detail, not a canonical-type one — hence `rust.type` as a hint, not a new IDL type. This keeps the IDL platform-neutral while still letting the Rust emitter match an existing non-negative-by-convention field like a nanosecond timestamp.

Rules:
- `@wire(<target>: <encoding>, …)` — one annotation, multiple target/encoding pairs; unknown `<target>` or `<encoding>` values are a validation error (closed vocabulary, see table below), keeping output deterministic and type-checkable — consistent with "Validate definitions before runtime where feasible" in `AGENTS.md`.
- `rust.case` / `rust.overrides` / `rust.type` (and equivalent `typescript.*`, etc.) are **emitter-direction modifiers** scoped to a `@wire` target, not free-form code. `overrides` is a closed map from canonical member name to literal string — this is how case 2's `exponential_histogram` gets covered *declaratively* (an explicit table beats a clever-but-wrong mechanical rule). Case-style values must match the target serializer's **actual** vocabulary (e.g. serde's `rename_all` accepts `"snake_case"`, `"SCREAMING_SNAKE_CASE"`, `"camelCase"`, `"PascalCase"`, `"kebab-case"`, `"lowercase"`, `"UPPERCASE"` — not invented names like `lower_snake_case`); the validator should reject anything outside that set per target.
- Hints are additive metadata on top of the existing platform-neutral `FieldType` — they do not change a field's canonical type or its compatibility/lineage semantics. A hint change is therefore not a breaking change to the canonical model (it may still be breaking to a *generated artifact*, which `modelable diff`/compatibility tooling should be able to flag — see Open Questions).

### 2. Closed encoding vocabulary (initial set, extensible later)

| Target | Encoding values | Applies to | Emitter behavior |
|---|---|---|---|
| `json` | `"string"` | `int` (and `decimal`) | **Must be honored by the JSON Schema emitter first** (emit `{"type": "string"}` plus an `x-modelable-wire` extension for the field, per `docs/emitter-spec.md` §6's existing `x-modelable-*` convention), since TypeScript is generated *from* JSON Schema via `json-schema-to-typescript` (`docs/emitter-spec.md` §7, "Do not hand-roll a separate TypeScript type mapper in Phase 1") — a TypeScript-only fix would not survive that pipeline. Rust: `#[serde(with = "…::int_as_string")]` (new helper module, see Open Questions) |
| `rust.type` | `"u64"`, `"i64"`, `"u32"`, … | `int` | Overrides the emitter's default signed 64-bit mapping for this field only; purely a Rust-side primitive choice, invisible to JSON Schema/TypeScript |
| `clickhouse` | `"uuid"` | `uuid` | Rust: `#[serde(with = "clickhouse::serde::uuid")]` |
| `clickhouse` | `"string"` | `enum`, `map<K, json>` | Rust: field type becomes `String` in the row shape; for enums, combine with `rust.case`/`rust.overrides`; for maps, generated `From` impls call `serde_json::to_string`/`from_str` |
| `clickhouse` | `"u8"` | `bool` | Rust: field type becomes `u8`/`Option<u8>` in the row shape; generated `From` impls map `true/false` ↔ `1/0` |
| `rust.case` | `"SCREAMING_SNAKE_CASE"`, `"snake_case"`, `"camelCase"`, `"PascalCase"`, `"kebab-case"`, … (serde `rename_all` values only) | `enum` members, paired with a string encoding | Drives both `serde(rename_all = …)` *and* the generated `From`/`Into` match arms when the target representation is a plain string rather than a serde-tagged enum |
| `rust.overrides` | map of canonical-member → literal | `enum` members | Per-member exceptions to `rust.case`, applied first |

This table is the seed; extending it (e.g. adding `postgres: "jsonb"`, `typescript.case`) is additive and should follow the same closed-vocabulary-plus-validation pattern rather than opening up arbitrary strings.

**Why the JSON Schema emitter is the load-bearing piece for `json` hints:** Modelable's Phase 1 TypeScript path is explicitly JSON-Schema-first — TS types are derived output, not an independently-generated target (`docs/emitter-spec.md` §7). So `@wire(json: "string")` cannot be implemented as a TypeScript-emitter-local change; it must change the JSON Schema this field compiles to (`type: integer` → `type: string`, with lineage/governance metadata preserved via `x-modelable-*` extensions as already done for other fields). Once the schema says `string`, `json-schema-to-typescript` naturally emits `string` — no separate TS-side type mapper needed, consistent with the existing "do not hand-roll" rule. This reframes step 7 in Dependencies/Sequencing below: it is fundamentally a **JSON Schema emitter** change with a TypeScript verification pass, not a TypeScript emitter change.

### 3. Escape hatch for anything outside the closed vocabulary

For conversions that are genuinely bespoke (a one-off computed transform that doesn't fit any encoding rule), do **not** add a special-case hint. Instead:
- If it's a *value derivation* (e.g. compute one field from others), it already belongs in a `projection … { field = <CEL expr> }` `ComputedMapping` — no IDL change needed, just emitter support for compiling CEL into the target language (flagged as a dependency below).
- If it's a *whole-type* conversion that can't be expressed field-by-field (rare, but plan for it), document that the consumer is expected to hand-write the `From`/`Into` for that one projection and exclude it from codegen via an explicit `@manual` marker — keeping the gap visible and lineage-tracked rather than silently wrong.

### Why this approach

- Keeps the hint vocabulary closed and validated (matches `AGENTS.md` "Validate definitions before runtime where feasible" and "Make lineage and compatibility behavior deterministic and testable").
- Separates "this is a different physical encoding of the same canonical value" (hints) from "this is a derived/computed value" (projections + CEL), which mirrors the spec's existing model/projection separation instead of inventing a parallel mechanism.
- Names the escape hatch explicitly (`@manual`) so unsupported conversions fail loudly at validation time instead of producing silently-wrong generated code — "Clarity above all" per the consuming project's own AGENTS.md, and good practice generally.
- The `overrides` map solves the irregular-enum-naming problem (`exponential_histogram`) without resorting to arbitrary code in `.mdl`.

### Alternatives considered

| Approach | Trade-off | Decision |
|---|---|---|
| Closed, namespaced `@wire` hints + CEL for derived values + `@manual` escape hatch | Small closed vocabulary, validated, explicit about its own limits. | Chosen. |
| Free-form per-target "raw attribute" strings (e.g. `@rustAttr("serde(with = \"...\")")`) | Maximally flexible, but reintroduces exactly the un-validated, untracked, drift-prone hand-written mapping that adoption is meant to remove; breaks the platform-neutral IDL principle. | Rejected. |
| Infer encodings from canonical type + target automatically (no hints) | Zero authoring overhead, but cannot represent the irregular cases (case 2) at all, and silently picks a representation the adopting project may not match — worse than today's explicit hand-written code. | Rejected as sole mechanism; may still be a sensible *default* layered under explicit hints for the mechanical cases (e.g. always encode `uuid` as `clickhouse::serde::uuid` when the target is a clickhouse-bound projection) — worth revisiting once hints exist and real usage shows which defaults are safe. |
| Let consumers post-process generated code with their own codemods | No Modelable change at all. | Rejected — defeats "single source of truth," and the whole point raised by the adopting project is to eliminate hand-maintained mapping code. |

## Dependencies / Sequencing Notes

**Scope note — read before sequencing any of this:** `docs/emitter-spec.md` §2 is the *approved* phase scope, and it lists only **JSON Schema, TypeScript (via JSON Schema), and Markdown as Phase 1 required targets**; SQL DDL is explicitly "Phase 5, Deferred", and Rust does not appear in that table at all (it's mentioned separately, in §9, as one of several "generated-language targets… implemented in the local codegen boundary"). Concretely:
- The `json`/`@wire` work (steps 1–2 below) lands inside the **already-approved** Phase 1 scope (JSON Schema + TypeScript) and can proceed without a scope change.
- Extending the **Rust** emitter (steps 3–5) and adding a **SQL DDL** emitter are *not* currently in approved scope. Either get an explicit scope-table update merged first (promoting Rust from "implemented extra" to a supported/required target, and pulling SQL DDL forward from Phase 5), or treat this whole Rust/SQL-DDL track as an out-of-band addition the adopting project sponsors — but say so explicitly in whatever plan depends on it, rather than presenting it as already-scoped Phase 1 work.

With that scope question resolved, the slices are (in priority order):
1. IDL/IR support to parse, validate, and carry `@wire`/`@manual` through to the emitters (`cli/src/modelable/parser/ir.py`). *(In approved scope.)*
2. **JSON Schema emitter**: honor `@wire(json: "string")` by emitting `{"type": "string", "x-modelable-wire": {...}}` instead of `{"type": "integer"}`, so `json-schema-to-typescript` naturally produces `string` — this is the actual mechanism by which the TypeScript path gets fixed (see "Why the JSON Schema emitter is the load-bearing piece" above). *(In approved scope; this is what makes the TypeScript path correct — there is no separate "TypeScript emitter" step needed for `json` hints given the "do not hand-roll a separate TypeScript type mapper" rule.)*
3. *(Requires the scope decision above)* Rust emitter: `serde` derives + per-field attributes driven by `@wire(json: …)`, `@wire(clickhouse: …)`, and `rust.type`/`rust.case`/`rust.overrides`.
4. *(Requires the scope decision above)* Rust emitter: `sqlx::FromRow` / `clickhouse::Row` derive variants for storage-bound projections.
5. *(Requires the scope decision above)* Rust emitter: generated `From`/`Into` between a model's auto-projections, using the hint table to drive both directions of the conversion.

CEL-in-projections-for-Rust (needed for the `ComputedMapping` half of "derived values", *if* the Rust track proceeds) is a separate, possibly pre-existing capability — confirm current emitter support for compiling `ComputedMapping` expressions to Rust before relying on it in step 5; if it only exists for the planner/runtime today, that's an additional dependency to size. The JSON Schema/TypeScript track (steps 1-2) does not need this, since `json-schema-to-typescript` handles derived-field representation via the schema itself.

## Open Questions

1. **Where do generated `#[serde(with = "…")]` helper modules for non-stdlib encodings (e.g. `int_as_string` for `@wire(json: "string")`) live?** Options: (a) Modelable ships a small companion Rust crate with these helpers and generated code depends on it, (b) the emitter inlines the helper module's source into generated output (no new dependency, more generated bytes), (c) the consumer is expected to provide it and the emitter just references a configurable path. (b) keeps Modelable dependency-free for consumers (matches "no runtime materialization" Phase 1 posture); (a) is more idiomatic but adds a dependency surface. Needs a decision before step 2 above is implemented.
2. **Should a hint change be flagged by `modelable diff`/compatibility checks even though it doesn't change the canonical type?** It changes the *generated artifact's* wire shape, which is exactly the kind of silent-break the compatibility engine exists to catch. Likely yes, but as an "artifact compatibility" concern layered on top of (not inside) the existing model-version compatibility engine (`cli/src/modelable/compat/`) — needs its own scoping.
3. **Is `@manual` needed at MVP, or can the first slice simply not support whole-type custom conversions and document that as a known gap?** Given the adopting project's own plan treats one domain (NLQ/Visualization, with CEL-computed/union-typed fields) as a "deliberate exception" candidate, starting without `@manual` and revisiting once real friction appears may be the leaner first slice — avoids speculative design for a case that may turn out to be rare.
4. **`typescript.*` modifiers** — the table above only sketches `rust.*`; once the Rust side is validated against Observable's real `.mdl` definitions, mirror the needed subset for TypeScript (likely just `@wire(json: "string")` → `string` and enum case/overrides for string-literal unions).
