# Modelable Feature Gaps — Response Design

Date: 2026-07-07

## 1. Purpose

Scalable, a sibling project developed by the same team, filed a concrete
feature request against Modelable:
[`docs/analysis/2026-07-07-modelable-feature-gaps.md`](https://github.com/ktjn/scalable/blob/main/docs/analysis/2026-07-07-modelable-feature-gaps.md)
in the `ktjn/scalable` repository. That document deliberately does not
propose `.mdl` grammar — per `language-reference.md` section 11, exact
syntax for any accepted feature request is Modelable's decision, not the
requester's.

This document is that decision. For each of the 8 gaps it records: the
accepted `.mdl` syntax and semantics (or, for gap 8, why no syntax is
accepted yet), the IR and validator shape, the per-target emitter impact,
and where the work sits in the implementation sequence. It is an accepted
design target, not a step-by-step implementation plan — see
[`docs/superpowers/plans/2026-07-07-fixed-width-integer-primitives-first-slice.md`](../plans/2026-07-07-fixed-width-integer-primitives-first-slice.md)
for the first implementation slice this design unlocks.

Two gaps (5 and 7) already have most of their capability set accepted in
[`docs/superpowers/specs/2026-07-04-scalable-protobuf-grpc-support-design.md`](2026-07-04-scalable-protobuf-grpc-support-design.md).
This document narrows those two down to concrete `.mdl` syntax and a
completion definition; it does not re-litigate that design.

## 2. Design Principles

- Every accepted gap is additive to the existing `.mdl` grammar and IR.
  Nothing here changes the meaning of an existing `.mdl` file.
- New primitive-shaped gaps (1, 2, 6) reuse the existing pattern for
  parameterized primitives established by `decimal(p, s)`: a dedicated IR
  node next to `PrimitiveType`, not an overloaded string enum.
- Every new type must have a defined mapping (exact, lossy-with-diagnostic,
  or metadata-only) in every currently implemented emitter before the
  gap is considered shippable for that target. Silent gaps are not
  acceptable — see `emitters/diagnostics.py` (`type_loss`,
  `missing_metadata`) for the existing mechanism.
- Registry-derived state (`registry.db`) stays a disposable, rebuildable
  artifact (`architecture.md` line 830). Any gap that needs allocation to
  survive a rebuild (gap 4) must persist its source of truth outside
  `registry.db`, in git-tracked `.mdl`-adjacent state.
- Where a gap's target audience is Scalable specifically but the
  mechanism is generally useful (index syntax feeding SQL DDL, UUIDv7
  feeding a native Postgres default), take the general win, not just the
  narrow one.

## 3. Sequencing Summary

Priority order in the source document doesn't match a safe build order —
several gaps depend on ones ranked lower. This is the accepted build
order, expressed as Modelable version lines:

| Order | Gap | Version | Depends on |
|---|---|---|---|
| 1 | UUIDv7-compatible identifier (#2) | 1.1 | none — independent, small |
| 2 | Wire-format contract completion (#5) | 1.1 | already-in-flight protobuf/grpc work |
| 3 | Primary key / secondary index / sort-key syntax (#7) | 1.1 | already-in-flight protobuf/grpc work |
| 4 | Fixed-width integer primitives (#1) | 1.2 | none, but large blast radius — own version line |
| 5 | Fixed-length binary primitive (#6) | 1.2 | reuses the parameterized-primitive pattern gap 2 lands first |
| 6 | Semantic-type / type-alias mechanism (#3) | 1.3 | gap 1 (wraps fixed-width ints) |
| 7 | Deterministic registry id allocation (#4) | 1.4 | gap 3 (`registry: true` marker) |
| — | Third compatibility signal (#8) | not scheduled | open question, see section 11 |

Rationale for the reordering: gap 4's "per registry-backed name" only has
a place to attach to once gap 3 exists to declare a name as
registry-backed. Gap 3's main value (`ModuleId : u32`) is hollow until
gap 1 supplies `u32`. Gaps 2 and 5/7 have no such dependency and are
cheap, so they ship first as the 1.1 line, alongside the protobuf/gRPC
work already under way per `ROADMAP.md`.

## 4. Gap 1 — Fixed-Width Integer Primitives

**Decision:** add ten new primitive kinds — `u8, u16, u32, u64, u128, i8,
i16, i32, i64, i128` — as sibling keywords to the existing `int`. `int`
is unchanged and remains the untyped 64-bit signed default; it is not
deprecated. This is purely additive.

**Grammar** (`modelable.lark`, extends `primitive_type`):

```
primitive_type: ...
              | "u8"   -> pt_u8
              | "u16"  -> pt_u16
              | "u32"  -> pt_u32
              | "u64"  -> pt_u64
              | "u128" -> pt_u128
              | "i8"   -> pt_i8
              | "i16"  -> pt_i16
              | "i32"  -> pt_i32
              | "i64"  -> pt_i64
              | "i128" -> pt_i128
```

**IR:** extend `PrimitiveType.kind`'s `Literal[...]` in `parser/ir.py`
with the ten new strings. Extend `shapes.py`'s `_PRIMITIVE_NAMES`
correspondingly.

**Validation:** default-value literals (`field_default`) must be checked
against the declared width's numeric range (a `u8` default of `300` is a
compile error). `validation/semantic.py`'s existing `int`/`DecimalType`
special-casing (lines 501, 536) generalizes to "any integer-kind
primitive."

**Target mapping.** `emitters/targets.py`'s `CODEGEN_TARGETS` currently
implements `sql-postgres` and `sql-clickhouse` for SQL (no `sql-mysql`,
`sql-sqlite`), and has no `avro` target — those three rows are recorded
below as forward guidance for whenever those targets are built, not as
work items in the first implementation slice (see the plan doc's Task 4
scope note):

| Target | u8/u16/u32/u64/u128 | i8/i16/i32/i64/i128 | Notes |
|---|---|---|---|
| Rust | `u8/u16/u32/u64/u128` | `i8/i16/i32/i64/i128` | Exact native match — this is the whole point of the gap. |
| Go | `uint8/16/32/64`, u128 → `[16]byte` + `type_loss` | `int8/16/32/64`, i128 → `[16]byte` + `type_loss` | Go has no native 128-bit integer. |
| Java | next-widest signed (`byte/short/int/long`) + `type_loss` for unsigned widths, u128/i128 → `BigInteger` | `byte/short/int/long`, i128 → `BigInteger` | Java has no unsigned integer types. |
| C# | `byte/ushort/uint/ulong`, `System.UInt128` | `sbyte/short/int/long`, `System.Int128` | .NET 7+ has native 128-bit — exact match, no loss. |
| Python | `int` with `Annotated[int, Field(ge=.., le=..)]` bounds | same | Python ints are unbounded; bounds are enforced at the Pydantic boundary. |
| TypeScript | `number` for ≤32-bit, `bigint` for 64/128-bit | same | Matches JS's safe-integer ceiling (2^53). |
| SQL (Postgres) | `SMALLINT/INTEGER/BIGINT` + `CHECK (col >= 0)` for unsigned, `NUMERIC(20,0)`/`NUMERIC(39,0)` for u64/u128 | `SMALLINT/INTEGER/BIGINT`, `NUMERIC(39,0)` for i128 | Postgres has no unsigned or 128-bit integer type. |
| SQL (ClickHouse) | `UInt8/16/32/64/128` | `Int8/16/32/64/128` | Exact native match. (`_VALID_CLICKHOUSE_ENCODINGS` already anticipates `"u8"`.) |
| SQL (MySQL) | `TINYINT/SMALLINT/INT/BIGINT UNSIGNED`, u128 → `DECIMAL(39,0)` + `type_loss` | `TINYINT/SMALLINT/INT/BIGINT`, i128 → `DECIMAL(39,0)` + `type_loss` | MySQL has no 128-bit integer. |
| SQL (SQLite) | `INTEGER` for ≤64-bit (dynamic typing), 128-bit → `BLOB`/`TEXT` + `type_loss` | same | SQLite integers are max 8 bytes. |
| JSON Schema | `{"type":"integer","minimum":..,"maximum":..}` | same | Bounds encode width; no unsigned keyword needed. |
| Protobuf | `uint32`/`uint64`, u128 → `bytes` (16-byte BE) + manifest metadata | `int32`/`int64`, i128 → `bytes` + manifest metadata | proto3 has no 8/16-bit or 128-bit scalar. |
| Avro | `"int"`/`"long"`, 128-bit → `{"type":"fixed","size":16}` | same | Avro's `fixed` type is an exact match for 128-bit. |
| FHIR R4 | `integer` for `u8`/`u16`, `string` for `u32`/`u64`/`u128` | `integer` for `i8`/`i16`/`i32`, `string` for `i64`/`i128` | FHIR `integer` is 32-bit **signed** (no `integer64` until R5); `u32`'s range exceeds it, so `u32` maps to `string` like the wider unsigned kinds — only `i8`/`i16`/`i32` and `u8`/`u16` safely fit. |
| dbt/OpenLineage/OpenMetadata/ODCS/Markdown | nearest declared numeric type name + width as extension metadata | same | Metadata/catalog formats; width is documented, not enforced. |

## 5. Gap 2 — UUIDv7-Compatible Identifier

**Decision:** do not add a new primitive kind. `uuid` becomes a
parameterized primitive with an optional version argument, following the
same shape as `decimal(p, s)`:

```mdl
@key commandId: uuid(7)
     legacyId:  uuid       // unchanged — defaults to v4
```

**Grammar:**

```
primitive_type: ...
              | "uuid" ( "(" INT ")" )?  -> pt_uuid
```

The transformer validates the argument is `4` or `7` (any other integer
is a parse-time error, not silently accepted).

**IR:** `PrimitiveType(kind="uuid")` gains an optional `version: Literal[4, 7] = 4`
field. This is a smaller change than gap 1 because representation does not
change — v4 and v7 are both 128-bit values with the same string form —
only generation and sort semantics differ.

**Target mapping:** no emitter's *type* mapping changes (`uuid` still
emits `uuid::Uuid`, `Guid`, `UUID`, `string`, etc., in every target). Two
targeted improvements:

- **SQL (Postgres):** `@server`-annotated `uuid(7)` key fields emit
  `DEFAULT uuidv7()` instead of `DEFAULT gen_random_uuid()` (Postgres 18+
  ships `uuidv7()` natively — no extension required).
- **Docs/Markdown, JSON Schema, LSP hover:** render "UUIDv7
  (timestamp-ordered)" instead of bare "UUID"; JSON Schema adds
  `"x-modelable-uuid-version": 7`.

This gap establishes the parameterized-primitive-with-validated-argument
pattern that gap 6 (`binary(N)`) reuses, so it should land first even
though gap 1 is higher priority — it's the cheapest gap and de-risks the
grammar/transformer plumbing the bigger gaps depend on.

**Correction (found during implementation):** gap 6 (`binary(N)`) shipped
in Modelable 1.2 as a **separate top-level `type_expr` alternative**
(`fixed_binary_type: "binary" "(" INT ")"`, producing a distinct
`FixedBinaryType` IR node), the same way `decimal(p, s)` already worked —
not as a parameterized variant of an existing `primitive_type`
alternative. This gap doesn't follow that shape: `uuid(7)` stays a
`PrimitiveType(kind="uuid")` with an added `version` field, matching this
section's original grammar sketch (`"uuid" ("(" INT ")")? -> pt_uuid`,
inline in the `primitive_type` rule) rather than gap 6's actual shipped
pattern. In other words, gap 6 didn't end up reusing a pattern gap 2
established, because gap 2 hadn't landed yet when gap 6 shipped — the two
gaps turned out to be independent, not sequenced by a shared mechanism.

The SQL Postgres `DEFAULT uuidv7()` improvement described above does not
have an existing mechanism to hook into: `sql.py` has no `@server`-driven
`DEFAULT`-clause generation for *any* type today (grepped the whole file —
no `DEFAULT` keyword appears in `_pg_col_type`/`_pg_base_type` at all).
Adding one is a new emitter capability, not an extension of an existing
per-type mapping, and is out of scope for this slice; deferred as a
follow-up once/if `@server`-driven column defaults become a real emitter
feature for reasons beyond `uuid(7)` alone.

Similarly, "render as prose" for Markdown and LSP hover doesn't fit the
existing rendering conventions: `markdown.py`'s `_type_str` renders every
parameterized type as its `.mdl` declaration syntax (`decimal(10,2)`,
`array<string>`), never as an English description, and `hover.py` renders
every field's type as the bare `field.type.kind` discriminator string
uniformly across all `FieldType` variants (including `decimal` and
`fixed_binary`, which don't show their precision/scale/length in hover
either). Singling out `uuid(7)` for a prose description in Markdown or a
detail-bearing hover would be inconsistent with how every other
parameterized type is already rendered in both places. This slice renders
`uuid(7)` as `uuid(7)` in Markdown (matching `decimal`/`binary`
precedent) and leaves hover unchanged (`type: uuid`, matching
`decimal`/`fixed_binary` precedent) rather than adding a
uuid-specific carve-out to either.

## 6. Gap 3 — Semantic-Type / Type-Alias Mechanism

**Decision:** a new top-level declaration inside `domain`, named
`semantic` (not `platform`, to avoid colliding with existing "target
platform" vocabulary in the docs, and to match ADR-011's own term
"semantic platform types"):

```mdl
domain platform {
  owner: "platform-team"

  semantic ModuleId : u32 {
    registry: true
  }

  semantic Identity128 : u128

  semantic FixedDecimalValue : i128
}
```

Fields reference a semantic type with a bare `IDENT`:

```mdl
entity Schema @ 1 (additive) {
  @key moduleId: ModuleId
}
```

**Correction (found during implementation of the first slice):** the
original text of this section said fields would reference a semantic
type "the same way they reference another domain's model — bare `IDENT`
for same-domain, `Domain.Name` for cross-domain — reusing the existing
dotted-ref resolution path used by `ref<Domain.Model>`." Neither half of
that holds up against the actual codebase:

- `type_expr`'s existing bare-`IDENT` alternative already resolves as a
  **workspace-wide flat search**, not a domain-scoped one — every
  existing consumer (e.g. `rust.py`'s `_resolve_named_type_map`) searches
  `mdl.domains` in full and takes the first match, with no domain
  qualification at all. There is no existing "same-domain vs.
  cross-domain" distinction to reuse for semantic types either, so a bare
  `ModuleId` reference already resolves correctly regardless of which
  domain declares it or which domain references it, with zero grammar
  changes beyond the `semantic` declaration itself.
- There is no existing dotted (`Domain.Name`) bare-type-reference
  grammar or resolution path to reuse. `ref<Domain.Model>` is a distinct
  mechanism — it resolves through `resolve_model_ref`, which requires a
  version spec that a `semantic` declaration (unversioned) doesn't have,
  and reusing it would incorrectly imply semantic types carry the
  versioning semantics of models. Dotted qualification for semantic-type
  references is deferred; the flat-search behavior above already covers
  the common case this gap exists for (unique, workspace-recognizable
  names like `ModuleId`, `SchemaId`), and a real namespacing mechanism
  for `NamedType` in general is a bigger, separate language decision that
  affects every `NamedType` consumer, not just semantic types.
- `BOOL` is not an existing terminal. The grammar has no boolean-literal
  production anywhere (`= false` on a `bool` field is captured as raw,
  untyped `EXPRESSION` text). `semantic_item`'s `registry: BOOL` needs a
  new `bool_literal: "true" -> bl_true | "false" -> bl_false` production,
  mirroring the existing `change_kind`/`model_kind` keyword-alternative
  pattern in this grammar.
- "Reuse the existing dependency-graph pass that already prevents `ref<>`
  cycles" — no such pass exists anywhere in the codebase (`ref<>` cycles
  are not currently detected at all). Chain-depth bounding and cycle
  detection for `semantic` underlying-type chains is new code, not reuse.

**Grammar:**

```
domain_item: ... | semantic_decl
semantic_decl: "semantic" IDENT ":" type_expr semantic_body?
semantic_body: "{" semantic_item* "}"
semantic_item: "registry" ":" bool_literal
bool_literal: "true" -> bl_true | "false" -> bl_false
```

**IR:** `SemanticTypeDecl(name: str, underlying: FieldType, registry: bool = False)`
added to `DomainDef` as `semantic_types: list[SemanticTypeDecl]` —
a plain list, not a dict, mirroring the existing `auto_projections: list[AutoProjectionDecl]`
field (semantic types are unversioned, so there's no natural
version-keyed dict shape the way `models`/`projections` have; a list also
lets validation catch duplicate names explicitly instead of a dict
silently overwriting one declaration with another). A field's `NamedType`
resolves against declared `semantic` names using the same flat,
workspace-wide search every other `NamedType` consumer already performs,
extended to also scan `domain.semantic_types` alongside `domain.models`.

**Validation:**

- The underlying type must be a `PrimitiveType`, `DecimalType`,
  `FixedBinaryType`, or a `NamedType` referencing another declared
  `semantic` type — `ArrayType`, `MapType`, `RefType`, `EnumType`, and
  `ObjectType` are rejected (semantic types wrap scalars, not
  collections or composites).
- A `NamedType` underlying reference must resolve to a real `semantic`
  declaration somewhere in the workspace; a dangling reference is an
  error.
- Chain depth is bounded (32 levels) and cycles are detected by walking
  the underlying chain with a visited-name set — new code, per the
  correction above.
- Semantic type names must be unique within a domain, and must not
  collide with a model name in the same domain (both participate in the
  same flat `NamedType` search space, so a collision would make
  resolution ambiguous).
- Two `semantic` types wrapping the same primitive are non-interchangeable:
  CEL expressions that compare or assign across distinct semantic types
  are validator errors (`expressions/cel.py`) — this nominal-typing check
  in CEL is the one piece of this gap that is *not* in the first slice;
  it ships as an explicit follow-up once the declaration and Rust
  emission are proven.

**Target mapping (first slice: Rust only, matching the interim
workaround this gap is meant to retire):**

- **Rust:** `pub struct ModuleId(pub u32);` with `From<u32> for ModuleId`,
  `From<ModuleId> for u32`, and `Deref<Target = u32>` derived — not
  `TryFrom`, which the original text of this section listed alongside
  them. A pure newtype wrapper with no additional constraints has no
  fallible conversion path to justify `TryFrom` yet; it can be added once
  a real validated-construction use case exists. Emitted as one file per
  `semantic` declaration (`<domain>/<snake_name>.rs`, no version suffix,
  since the declaration itself is unversioned), alongside the domain's
  model files. Referencing fields resolve to the semantic type's struct
  name and a `use super::<module>::<Name>;` import through the exact
  same `_resolve_named_type_map`-style mechanism `rust.py` already uses
  for plain `NamedType` object references — extended to also recognize
  semantic-type names, not a new mechanism. This directly replaces the
  handwritten adapter layer described in the Rust target design doc
  section 7 — once this ships, that adapter layer is deleted, not kept
  as a permanent shim.
- **Go** (follow-up): `type ModuleId uint32` — Go's named-type system is
  a near-exact fit, low additional cost once Rust proves the shape.
- **Java/C#** (follow-up): `record ModuleId(int value) {}` / `readonly record struct ModuleId(int Value)`.
- **Python** (follow-up): `typing.NewType("ModuleId", int)`.
- **TypeScript** (follow-up): branded type — `type ModuleId = number & { readonly __brand: "ModuleId" }`.
- **Protobuf/JSON Schema/SQL/Avro/etc.:** semantic types are a
  compile-time-only distinction in Modelable's model; these targets stay
  structural and emit the underlying primitive's wire representation
  unchanged, tagged with `x-modelable-semantic-type: "platform.ModuleId"`
  vendor metadata so downstream generators (including Scalable's own,
  for languages Modelable doesn't emit) can regenerate the wrapper.

## 7. Gap 4 — Deterministic Small-Integer Registry ID Allocation

**Decision:** allocation state cannot live only in `registry.db`, because
`registry.db` is a disposable, rebuild-from-scratch artifact
(`architecture.md` line 830: "Deleting it and re-running `compile` must
produce an identical result"). A monotonic counter recomputed from
declaration order would silently renumber existing ids the moment a new
`semantic ... registry: true` declaration is added earlier in file order
than an existing one. That violates "never reassigned or reused."

Instead, add a new git-tracked ledger file at the workspace root,
`registry-ids.lock` (JSON, one entry per registry-backed semantic type,
sorted by id for a stable diff):

```json
{
  "platform.ModuleId": 1,
  "platform.SchemaId": 2,
  "platform.CommandId": 3
}
```

`modelable compile`:

1. Reads `registry-ids.lock` if present (empty map if absent).
2. For every `semantic ... { registry: true }` declaration not already
   in the lock file, allocates `max(existing ids, 0) + 1`, assigning in a
   deterministic order (domain name, then declaration name,
   alphabetically) among the newly-added names in a single compile.
3. Writes the (possibly updated) lock file back, sorted by allocated id.
4. Errors if a name in the lock file no longer resolves to a declared
   `registry: true` semantic type, unless `--allow-orphaned-registry-ids`
   is passed — orphaned ids are never reused for a different name even
   after removal, matching the "never reassigned" requirement.

`registry.db` gains a `registry_ids(name TEXT PRIMARY KEY, allocated_id INTEGER UNIQUE, first_registered_at TEXT)`
table, populated as a **read-through cache** of the lock file — this
keeps `registry.db` queryable (`modelable inspect`) without making it the
source of truth. Generated manifests (Rust struct doc comments, protobuf
schema manifest) expose the allocated id.

This is the one gap in the set that adds a new *file kind* to a `.mdl`
workspace, not just grammar — call this out explicitly in the CLI
reference and `getting-started.md` when it ships, and add it to
`.gitignore`'s companion "commit this" documentation (it must **not** be
gitignored, unlike `registry.db`).

## 8. Gap 5 — Rust / Protobuf Wire-Format Contracts

The capability set here (descriptor sets, richer index metadata, protobuf
compatibility validation) is already accepted in
`2026-07-04-scalable-protobuf-grpc-support-design.md` and already
in-flight per `ROADMAP.md`. What that design does not yet define is a
completion bar for "byte-exact and reproducible across compiler
versions" — this document adds that:

- A new `docs/wire-format-contract.md` documents, per emitted Rust type
  and per generated `.proto` message, the exact encoding rules: field
  ordering (declaration order, pinned by `#[serde]`/prost field-number
  attributes, not struct layout), canonical decimal-as-string form,
  timestamp truncation precision, and enum discriminant stability rules.
- A golden-fixture regression suite,
  `cli/tests/fixtures/wire_golden/`, encodes representative model
  versions with a pinned toolchain and asserts byte-identical output
  across compiler versions in CI. This is the actual mechanism that
  makes "byte-exact and reproducible" a tested guarantee instead of an
  aspiration.

This slice is scoped as a follow-up task under the existing protobuf/gRPC
initiative, not a new plan — see that design doc's own task sequencing.

## 9. Gap 6 — Fixed-Length Binary Primitive

**Decision:** parameterize `binary` the same way gap 2 parameterizes
`uuid`, but as a distinct IR node (mirroring `decimal(p,s)`, which is
already a sibling of `PrimitiveType` rather than a variant inside it):

```mdl
keyHash: binary(32)
avatar:  binary          // unchanged — variable length
```

**Grammar:**

```
type_expr: ... | fixed_binary_type
fixed_binary_type: "binary" "(" INT ")"
```

**IR:** `FixedBinaryType(kind="fixed_binary", length: int)` next to
`DecimalType` in `parser/ir.py`'s `FieldType` union. Validation bounds
`length` to `1..=4096` (catches typos; revisit the ceiling if a real use
case needs more).

**Target mapping** (MySQL, SQLite, and Avro rows are forward guidance —
none are implemented emitter targets as of this writing):

| Target | Mapping |
|---|---|
| Rust | `[u8; N]` — exact native fixed-size array. Retires the `FixedBytes<N>` interim wrapper described in the Rust target design doc section 6. |
| Go | `[N]byte` — exact native array. |
| Java | `byte[]` + Javadoc noting required length; length enforced only via constructor check (`type_loss`, partial). |
| C# | `byte[]` + XML doc; same partial-enforcement tier as Java. |
| Python | `Annotated[bytes, Field(min_length=N, max_length=N)]` — fully enforced. |
| TypeScript | `string`, same as plain `binary` (this emitter already represents all `binary` fields as base64-flavored `string`, never `Uint8Array` — `binary(N)` follows that existing convention rather than introducing an inconsistent representation). |
| SQL (Postgres) | `BYTEA` + `CHECK (octet_length(col) = N)`. |
| SQL (MySQL) | `BINARY(N)` — exact native match. |
| SQL (ClickHouse) | `FixedString(N)` — exact native match. |
| SQL (SQLite) | `BLOB` + `CHECK (length(col) = N)`. |
| JSON Schema | existing `binary` schema plus `"x-modelable-fixed-length": N` vendor extension (base64-length min/maxLength math is a known follow-up nicety, not required for the first slice). |
| Protobuf | `bytes` + `"fixed_length": N` manifest metadata (proto3 has no fixed-length byte type). |
| Avro | `{"type":"fixed","size":N,"name":...}` — exact native match. |

## 10. Gap 7 — Primary Key, Secondary Index, and Sort-Key Syntax

**Decision:** a new declaration bound to one model version, parallel in
shape to `auto projections`:

```mdl
entity Order @ 3 (additive) {
  @key       orderId:    uuid
             customerId: uuid
             status:     enum(pending, shipped, delivered)
             createdAt:  timestamp
}

index Order @ 3 {
  primary orderId

  secondary byCustomer {
    key:    [customerId]
    sort:   [createdAt desc]
    unique: false
  }

  secondary byStatus {
    key: [status, createdAt]
  }
}
```

**Grammar:**

```
domain_item: ... | index_decl
index_decl: "index" IDENT "@" INT "{" index_item* "}"
index_item: primary_index | secondary_index
primary_index: "primary" IDENT ("," IDENT)*
secondary_index: "secondary" IDENT "{" secondary_index_item* "}"
secondary_index_item: "key" ":" "[" IDENT ("," IDENT)* "]"
                    | "sort" ":" "[" sort_field ("," sort_field)* "]"
                    | "unique" ":" BOOL
sort_field: IDENT sort_dir?
sort_dir: "asc" | "desc"
```

**IR:** `IndexDecl(model: str, version: int, primary: list[str], secondary: list[SecondaryIndexDecl])`
added to `DomainDef`, alongside `auto_projections`. `primary` must
exactly match the model version's `@key` field set (validation
cross-check — restating it explicitly, rather than inferring it, is
required so composite keys have an explicit declared order).

**Change visibility:** an `index_changed` `FieldChange`-equivalent kind
is added to `compat/diff.py`, feeding `registry.db`'s existing
`compatibility_reports` table — this satisfies the source requirement
that index changes be "visible as a schema and rebuild event," reusing
the compatibility/lineage machinery rather than adding a parallel one.

**Emission:** this is not just a Scalable-facing gap. Two immediate
consumers:

- The protobuf/gRPC emitter's read-replica and index model (already
  accepted in the grpc design doc) reads this declaration directly.
- The existing `sql.py` emitter gains `CREATE INDEX`/`CREATE UNIQUE INDEX`
  DDL statements generated from `secondary` blocks — a concrete
  improvement independent of Scalable.

**Correction (found during implementation planning):** the rationale
above for restating `primary` explicitly ("composite keys have an
explicit declared order") assumes composite `@key` sets are
representable. They aren't — `validation/semantic.py`'s existing
`_validate_models` already requires `entity`/`aggregate` model versions
to carry **exactly one** `@key` field; anything else is a compile error.
The set-equality validation between `primary` and the model's `@key`
field names is still implemented as designed (forward-compatible if
composite keys are ever added, and it still catches a typo'd or stale
field name), but in practice every `primary` clause this validates today
will be a single-name list — the "explicit declared order" benefit
doesn't apply yet.

Also, `sql.py`'s `CREATE TABLE` DDL is generated per-*projection*, not
per-model — a `binding` maps a fully-qualified model name to a table, and
DDL is emitted for whichever projection's `source.model` matches that
binding. `index`'s `secondary` field references (which name fields on
the *model*, not a projection) are resolved through to the emitting
projection's own field names via its `DirectMapping`s; a referenced field
that the projection doesn't include is skipped with a warning rather than
emitted as a broken column reference. `grpc.py` consuming `index_decl`
directly and ClickHouse index DDL are deferred to follow-up slices — see
the implementation plan's Scope section for the reasoning on each.

## 11. Gap 8 — Third Compatibility Signal (Open Question)

No grammar is accepted here. The source document itself frames this as
"an open question, not yet a firm request," and Modelable's language
authority principle (`language-reference.md` section 11) means an
unproven signal should not be committed to the grammar speculatively —
a wrong shape here is expensive because `changeKind` is validated at
every published version.

Two candidate shapes are recorded for a future decision, not accepted:

- **(a)** widen `changeKind` to a three-value enum:
  `additive | breaking | breakingNoMigration`.
- **(b)** keep `changeKind` binary and add an orthogonal, optional
  `migration: required | not-required` attribute alongside it.

**(b)** is the better fit if this is ever accepted: it doesn't reinterpret
the meaning of already-validated `changeKind` values on existing
published versions, and it's purely additive to the grammar. No plan
exists for this gap. Revisit once Scalable's ADR-018
migration-function-presence checks produce concrete evidence that the
Scalable-side judgment call is actually costly in practice — the interim
workaround (require a migration function for every `breaking` version
unconditionally) is explicitly called "workable" in the source document.

## 12. Non-Goals

- This document does not implement anything. See
  `docs/superpowers/plans/2026-07-07-fixed-width-integer-primitives-first-slice.md`
  for the first concrete implementation slice.
- This document does not revisit the protobuf/gRPC capability set already
  accepted in `2026-07-04-scalable-protobuf-grpc-support-design.md`; gaps
  5 and 7 narrow that design to concrete `.mdl` syntax, they don't replace
  it.
- This document does not commit to CEL-level nominal typing for `semantic`
  types (gap 3) in the first slice, or to base64-aware JSON Schema length
  bounds for `binary(N)` (gap 6) — both are named follow-ups.

## 13. Related Documents

- `https://github.com/ktjn/scalable/blob/main/docs/analysis/2026-07-07-modelable-feature-gaps.md` — the source request.
- `docs/superpowers/specs/2026-07-04-scalable-protobuf-grpc-support-design.md`
- `docs/superpowers/plans/2026-07-04-protobuf-target-first-slice.md`
- `docs/superpowers/plans/2026-07-07-fixed-width-integer-primitives-first-slice.md`
- `docs/language-reference.md`
- `docs/architecture.md`
- `ROADMAP.md`
