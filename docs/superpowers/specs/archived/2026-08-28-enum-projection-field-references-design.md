# Enum Projections as Field Types — Design

Date: 2026-08-28
Status: Implemented in Modelable 1.13.2
Scope: Allow a model or projection field to reference an `enum projection` declaration directly as its type, and make every compiler surface that already understands `EnumRefType`/semantic-enum references treat a projection-typed reference correctly rather than silently mishandling it.

Implementation note: The resolver, validation, compatibility, registry, plan,
and target-capability boundaries now accept projection-typed fields. Targets
without a dedicated subset-enum representation retain the documented
structural-loss boundary.

## 1. Context

The [Model Evolution Slices Roadmap](../plans/archived/2026-08-22-model-evolution-slices-roadmap.md) shipped `enum projection` declarations (E3) with full compatibility, registry, and editor support (E4, E5, E11), plus nominal codegen across every implemented target when a projection is reached through its own declaration or through a *record* projection's field mapping (E6-E10).

At proposal time, what was not built — and was explicitly flagged as a real,
discovered gap rather than an assumption, while shipping A1's `extract-enum`
tool — was using an enum projection as a field's own type:

```mdl
domain orders {
  semantic OrderStatus @ 1 (additive): enum(pending, paid, shipped, cancelled)

  enum projection PublicOrderStatus @ 1
    from OrderStatus @ 1
    pick(pending, paid, shipped)

  entity Order @ 1 {
    @key orderId: uuid
    status: PublicOrderStatus @ 1   // rejected today
  }
}
```

At proposal time this was rejected with `ENUMREF: unknown semantic type
'PublicOrderStatus'` because `registry/resolver.py::resolve_semantic_type_ref`
only searched `domain.semantic_types`.

This was a real gap, not a cosmetic one: the language already let an author
declare a nominal subset with its own compatibility and lineage rules, but
could not use it anywhere a field type was written. The projection was then
reachable only as a *record* projection's field-mapping source, through
separate `EnumProjectionDecl`-specific expansion code rather than the general
field-type path.

## 2. Why this is bigger than a resolver fix

`EnumRefType` (and the bare-`NamedType` enum-reference form) is not read in one place. Grepping the compiler for `EnumRefType` finds 19 files, each written under the assumption that a resolved reference is a `SemanticTypeDecl`:

| Area | File(s) | Current assumption |
| --- | --- | --- |
| Field-type resolution/validation | `compiler/workspace.py` (`_validate_named_field_types`) | resolves to `SemanticTypeDecl` or fails |
| Enum-projection's own source resolution | `compiler/workspace.py` (`_expand_enum_projections`) | must reject a non-semantic-type source — this path must **not** change |
| Canonical rendering/signatures | `compiler/render.py`, `registry/signature.py` | renders `Name @ version`; needs confirmation it stays unambiguous once two declaration kinds share a name-resolution path |
| Registry snapshots | `registry/snapshot.py` | stores resolved declaration identity |
| Compatibility | `compat/diff.py`, `compat/checker.py` (`_refine_enum_version_changes`) | refines `enum_version_changed` via `compare_semantic_enum_versions(SemanticTypeDecl, SemanticTypeDecl)` — has no notion of a projection-typed field changing subset/source |
| CEL expressions | `expressions/cel.py` | enum-vs-string comparison rules keyed on `EnumType`/`EnumRefType` shape, not declaration kind — likely unaffected, needs confirmation |
| Shared typed-SDK resolver | `emitters/named_types.py` (`resolve_named_types`/`resolve_named_ref`) | drives TypeScript/Python/Java/C#/Go; only walks `latest_semantic_types(domain)` |
| Rust | `emitters/rust.py` | already emits a `pub enum` per projection (`_emit_enum_projection`), but only when reached via a record-projection field mapping, not a model field |
| Protobuf/gRPC | `emitters/protobuf.py`, (`emitters/grpc.py` reuses it) | enum-numbers ledger and nominal enum emission keyed on semantic declarations |
| Avro, JSON Schema/OpenAPI, ODCS, OpenMetadata, OpenLineage, FHIR, Markdown | `emitters/avro.py`, `emitters/_schema_mapping.py`, `emitters/odcs.py`, `emitters/openmetadata.py`, `emitters/openlineage.py`, `emitters/fhir.py`, `emitters/markdown.py` | each has its own `EnumRefType` branch added during E9/E10, resolving only against `domain.semantic_types` |
| Refactor tooling | `refactor/extract_enum.py` | already documents this exact gap as a known follow-up |

Extending resolution without touching every consumer would let a projection-typed field parse and validate, then silently misbehave downstream — exactly the class of bug the E-series slices existed to eliminate (see the roadmap's "every semantic consumer receives a complete, exact, reproducible contract" rule). This design exists to scope that work honestly before any code changes, per the roadmap's own delivery discipline (one focused, reviewable slice at a time).

## 3. Decision

### 3.1 Resolver: an explicit, separate resolution path

Do not change `resolve_semantic_type_ref`'s signature or behavior — it has a caller (`_expand_enum_projections`'s own source resolution) that must keep rejecting a non-semantic-type source, and changing its return type would force every existing caller to handle a union it doesn't need.

Add a new function in `registry/resolver.py`:

```python
def resolve_enum_type_ref(
    mdl: MdlFile,
    current_domain: str,
    name: str,
    exact_version: int | None = None,
) -> tuple[str, SemanticTypeDecl | EnumProjectionDecl]:
```

It tries `resolve_semantic_type_ref` first (preserving all existing bare-name/domain-qualified/ambiguity rules), and on `LookupError` falls back to an equivalent lookup against `domain.enum_projections` (same current-domain-first, then unique-workspace-match fallback shape). Ambiguity between a semantic type and a projection of the same name cannot occur — E11 already added a collision check preventing that name from coexisting in one domain — but ambiguity *among projections* across domains must be rejected the same way `resolve_semantic_type_ref` rejects it among semantic types.

Only field-type resolution call sites switch to this new function. The enum-projection-source call site keeps calling `resolve_semantic_type_ref` unchanged.

### 3.2 Validation

`_validate_named_field_types` in `compiler/workspace.py` gains a projection branch alongside its existing `SemanticTypeDecl` branch:

- A bare `NamedType` resolving to a projection gets the same non-blocking `ENUMREF`-style warning pattern as a bare enum-semantic reference (naming the resolved exact version), for the same reason: a later projection version must not silently re-resolve an already-published consumer.
- An `EnumRefType` (exact-version) resolving to a projection is accepted outright, mirroring today's exact-enum-reference acceptance.
- The existing "must target an enum-backed semantic type" `EnumRefType` error becomes "must target an enum-backed semantic type or an enum projection."

### 3.3 Compatibility

`compat/checker.py::_refine_enum_version_changes` must handle the case where either side of an `enum_version_changed` field-type change resolves to a projection instead of a semantic declaration. Reuse the existing enum-projection compatibility vocabulary from E5 (`enum_projection_source_changed`, `_member_added`, `_member_removed`, `_implicit_member_added`) to describe the field-level consequence, rather than inventing a new finding kind. A field whose type is `PublicOrderStatus @ 1` and whose model version bumps to reference `PublicOrderStatus @ 2` must get a causal note describing *why* that projection version differs (member added/removed, source changed), the same depth of explanation semantic-enum-typed fields already get.

### 3.4 Signatures, snapshots, dependency graph

Canonical signature rendering (`compiler/render.py`, `registry/signature.py`) renders an `EnumRefType`/enum-reference field as `Name @ version` today regardless of declaration kind, which is already unambiguous given the shared-namespace collision checks (§3.1) — expected to need no change, but must be verified with a signature-equivalence test once the resolver change lands, not assumed. `dependency_graph.py` must add a projection-reference edge kind if it does not already treat this uniformly with a semantic-type reference edge — needs a direct audit at implementation time, not a prediction here.

### 3.5 Emitters — phased, not all-at-once

Every one of the ~14 emitter files above needs an explicit decision per E9/E10's own precedent ("document rather than conceal structural loss"). Given the breadth, this must ship as a compiler-core slice first, with emitter support following in dependency order — mirroring exactly how E6-E10 sequenced after E1-E5, rather than attempting all targets in one PR.

**Phase 1 — compiler core (the initial implementation slice).**
Resolver, validation, compatibility, signatures/snapshot/dependency-graph
support landed together. Each target now either supports projection-typed
fields through its capability boundary or reports the documented structural
loss explicitly, rather than silently mis-resolving the type.

**Phase 2+ — per-target real support, one reviewable slice each, proposed order:**
1. Rust — lowest marginal cost, since `_emit_enum_projection` already emits the `pub enum`; only the field-type-to-Rust-type wiring and `From`/`TryFrom` reuse need extending.
2. Typed SDKs (TypeScript, Python, Java, C#, Go) via the shared `emitters/named_types.py` resolver, same order E8 used.
3. Schema/API targets (Protobuf/gRPC, Avro, JSON Schema, OpenAPI) — Protobuf needs an enum-numbers ledger decision for projection-local vs. source-inherited allocation (E6 already made this call for projections reached via record-projection mapping; confirm it applies unchanged here).
4. Remaining storage/metadata targets (ODCS, OpenMetadata, OpenLineage, FHIR, Markdown), following E10's survey-then-fix pattern rather than pre-deciding each one now.

Each phase gets its own PR, golden-artifact regeneration, and (where applicable) real-compiler verification (`cargo build`, `tsc`, `javac`, `dotnet run`, `go run`), matching every prior E-slice's verification bar.

## 4. Non-goals

- No new IR node unifying `NamedType`/`EnumRefType` with projection references — the existing two-token field-type grammar already covers this once the resolver understands both declaration kinds.
- No change to `EnumProjectionDecl`'s own source resolution (`_expand_enum_projections`) — it keeps rejecting a non-semantic-type source.
- No automatic conversion or inference between a field's declared projection type and its source semantic type beyond what already exists for record-projection field mappings.
- No requirement that every emitter reach real support — a target may permanently document structural loss for enum-projection-typed fields if the format has no reusable subset-enum concept, the same precedent E9/E10 already set for enum projections in general.

## 5. Acceptance criteria (Phase 1)

1. A model or projection field can declare `Name @ version` or bare `Name` where `Name` resolves to an `enum projection`, with the same exact-version/bare-reference warning policy semantic-enum references already have.
2. `resolve_semantic_type_ref`'s existing callers and behavior are unchanged; no regression in enum-projection-source resolution's rejection of non-semantic-type sources.
3. A field-type change that alters which projection version is referenced, or a projection's own member/source change, produces a compatibility finding with a causal note (not a bare "type changed").
4. Canonical signatures for equivalent semantic-type-typed and projection-typed field fixtures are proven correct via a direct test, not assumed.
5. Every implemented target either has real Phase 2+ support or emits one specific, named diagnostic for a projection-typed field — no target crashes or silently emits a wrong/degraded artifact.
6. New parser/semantic/compatibility/registry tests cover: bare vs. exact reference, cross-domain projection reference, ambiguous same-name projection across domains, and a projection-vs-projection compatibility scenario (member added/removed on the referenced projection).
