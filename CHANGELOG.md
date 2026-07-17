# Changelog

Notable user-facing changes are documented here. Modelable follows Semantic
Versioning. Historical 0.x releases used the usual pre-1.0 allowance that minor
releases could contain breaking changes when called out explicitly.

## [Unreleased]

### Added

- Generated Rust registry-backed semantic newtypes now expose their allocated
  ID as `REGISTRY_ID`. Generated Rust models and projections expose
  `SCHEMA_VERSION` and the canonical Modelable signature as a dependency-free
  `[u8; 32]` `SCHEMA_CONTENT_SIGNATURE`.

## [1.2.1] - 2026-07-12

### Fixed

- Rust emitter: projection fields referencing a named, value, or semantic
  type now compile with the correct generated type name and a matching
  `use` import. Previously such fields kept the raw `.mdl` type name and no
  import was ever emitted, so any projection with a field of this shape
  failed to compile.
- Rust emitter: generated `use` statement order for named-type imports is
  now deterministic across processes. It previously depended on Python
  `set` iteration order (hash-randomization-dependent), so two clean builds
  of the same model could produce byte-different output.
- Rust emitter: `std::collections::HashMap` is only imported in generated
  files that actually use it, instead of unconditionally in every file,
  avoiding an `unused_imports` warning under `-D warnings`.
- Rust emitter: generated projection `From` impls now silence
  `clippy::useless_conversion` on their direct-mapped fields, which always
  call `.into()` even when the source and target field share a type.

## [1.2.0] - 2026-07-11

### Added

- `compile --domain <name>` (repeatable), a filter that scopes emitter
  output to the requested domain(s) instead of always emitting the whole
  workspace. Any in-scope model, projection, or field that references a
  dependency outside the requested domain set now fails compilation with
  a clear error naming the dangling reference, rather than silently
  degrading to a lossy fallback type (e.g. `uuid` -> `String`) with only
  an `EMIT002` warning.

### Fixed

- Rust emitter: all-caps enum values (e.g. `USD`) are now pascalized
  (`Usd`) instead of being left as `SCREAMING_CASE`, matching Rust enum
  naming conventions.
- C# emitter: all-caps tokens are now pascalized instead of being left
  as `SCREAMING_CASE`, matching C# naming conventions.

## [1.1.0] - 2026-07-10

### Added

- `index <Model> @ <version> { primary ...; secondary ... }`, a
  domain-level declaration parallel in shape to `auto projections`:
  `primary` must exactly match the model version's `@key` field(s), and
  each `secondary` block declares a `key` (required), `sort` (optional,
  with `asc`/`desc` direction), and `unique` (optional, default `false`).
  Validated at compile time (model/version existence, entity/aggregate-only,
  primary-matches-@key, secondary field references, duplicate names).
  Index changes between two published model versions are surfaced as an
  `index_changed` entry in that model's compatibility report — visible,
  not yet classified as breaking or additive. The Postgres SQL emitter
  generates `CREATE INDEX`/`CREATE UNIQUE INDEX` statements from
  `secondary` blocks. This is Scalable's feature-gaps request gap #7, the
  last of the seven concretely-scheduled gaps; see
  `docs/superpowers/specs/2026-07-07-modelable-feature-gaps-response-design.md`.
  ClickHouse index DDL and the protobuf/gRPC read-replica index model
  consuming this declaration directly are deferred.
- `docs/wire-format-contract.md`, pinning the Rust and Protobuf emitters'
  field-ordering, per-type encoding, and enum-discriminant rules, plus a
  golden-fixture regression suite (`cli/tests/fixtures/wire_golden/`,
  `cli/tests/test_wire_golden.py`) that fails CI on any byte-level drift
  in generated output. No emitter behavior changes — this is
  documentation and regression-test infrastructure only. Documents two
  previously-undocumented gaps found while writing it: `map<K,V>` has no
  Protobuf mapping (falls through to an opaque `bytes`), and Protobuf has
  no semantic-type reference resolution at all. This is Scalable's
  feature-gaps request gap #5, landing independently of the other five
  shipped gaps; see
  `docs/superpowers/specs/2026-07-07-modelable-feature-gaps-response-design.md`.
- `uuid(7)`, a UUIDv7 (timestamp-ordered) variant of the existing `uuid`
  primitive — `uuid` with no argument is unchanged and still defaults to
  v4. The transformer rejects any version argument other than `4`/`7` as
  a parse-time error. No emitter's underlying type mapping changes (every
  target still emits its existing `uuid` representation for both
  versions); JSON Schema gains an `x-modelable-uuid-version: 7` extension
  key and Markdown renders `uuid(7)` explicitly. This is Scalable's
  feature-gaps request gap #2, landing independently of the other four
  shipped gaps; see
  `docs/superpowers/specs/2026-07-07-modelable-feature-gaps-response-design.md`.
  SQL Postgres `DEFAULT uuidv7()` generation and prose-style
  descriptions in Markdown/LSP hover are deferred — neither has an
  existing mechanism to extend.
- `registry-ids.lock`, a git-tracked JSON ledger at the workspace root that
  `modelable compile` reads and updates: every `semantic ...
  { registry: true }` declaration gets a small, monotonically-increasing
  integer id, allocated in deterministic (domain, then declaration name)
  order and never reassigned or reused, even after the declaration is
  removed. Removing a declaration leaves an "orphaned" ledger entry that
  `compile` errors on by default; pass `--allow-orphaned-registry-ids` to
  keep it reserved instead. `registry.db` gained a `registry_ids` table,
  populated as a read-through cache of the lock file for ad hoc SQL
  queries — the lock file remains the source of truth. The Rust emitter
  surfaces the allocated id as a `/// registry id: N` doc comment on the
  generated newtype struct. This is the first slice of Modelable 1.4, part
  of Modelable's response to Scalable's feature-gaps request; see
  `docs/superpowers/specs/2026-07-07-modelable-feature-gaps-response-design.md`.
  Exposing the id in the protobuf schema manifest (blocked on protobuf
  gaining semantic-type support at all) and a `modelable inspect`
  id-lookup surface are deferred follow-ups.
- `semantic Name: Underlying`, a domain-level type-alias declaration whose
  underlying type is a primitive, `decimal(p,s)`, `binary(N)`, or another
  semantic type (chains are validated for cycles and dangling references, up
  to 32 levels deep). An optional `registry: true` marker is parsed and
  validated but not yet consumed by any emitter — it is a forward-compatible
  hook for Modelable 1.4's deterministic registry id allocation. Field
  declarations reference a semantic type by its bare name, resolved
  workspace-wide the same way model references already are. The Rust
  emitter generates a `#[serde(transparent)]` newtype struct with
  `From`/`Deref` impls for each declaration; all other emitters resolve a
  semantic type reference to its underlying type unchanged (extending
  semantic-type support to those targets is deferred follow-up work). This
  is the first slice of Modelable 1.3, part of Modelable's response to
  Scalable's feature-gaps request; see
  `docs/superpowers/specs/2026-07-07-modelable-feature-gaps-response-design.md`.
- `binary(N)`, a fixed-length variant of the existing variable-length
  `binary` primitive, bounded to `1..=4096` bytes, with a defined mapping
  in every currently implemented emitter (Rust and Go map to native
  fixed-size arrays; Java and C# map to `byte[]` with a warning noting the
  length isn't enforced by the type system; Python maps to bare `bytes`;
  TypeScript, SQL Postgres/ClickHouse, JSON Schema, and Protobuf all gained
  a mapping too). `binary` is unchanged. This is the second slice of
  Modelable's response to Scalable's feature-gaps request; see
  `docs/superpowers/specs/2026-07-07-modelable-feature-gaps-response-design.md`.
- Ten fixed-width integer primitives — `u8, u16, u32, u64, u128, i8, i16,
  i32, i64, i128` — as siblings to the existing `int`, with default-value
  range validation and a defined mapping in every currently implemented
  emitter (Rust, Go, Java, C#, Python, TypeScript, SQL Postgres/ClickHouse,
  JSON Schema, Protobuf, FHIR profile). `int` is unchanged. This is the
  first slice of Modelable's response to Scalable's feature-gaps request;
  see `docs/superpowers/specs/2026-07-07-modelable-feature-gaps-response-design.md`.
- Hosted documentation is published with MkDocs on GitHub Pages and linked from
  package metadata and GitHub releases (#108).
- `modelable sync --lineage marquez` posts generated OpenLineage events to a
  Marquez-compatible `/api/v1/lineage` endpoint, with `--dry-run` support for
  reviewing events before publishing (#105).
- Validate CI now has a path-gated OpenLineage live-smoke job that posts
  generated events to a Marquez Testcontainers stack (#105).

## [1.0.2] - 2026-06-28

### Fixed

- Rust emitter now emits enum-typed fields in `#[derive(clickhouse::Row)]`
  projection structs as `String`, and generates explicit `match` arms in the
  corresponding `From` impl converting each variant to its raw wire string.
  Fixes a clickhouse-rs 0.15 panic on `serialize_unit_variant` for String
  columns (#119).
- Rust emitter no longer emits `EMIT003` for `NamedType` fields whose types
  exist in the same workspace; it resolves them to `use super::...` imports
  and stable Rust type names instead. `EMIT003` still fires for genuinely
  unresolvable types (#120).
- TypeScript emitter now places auto-generated `import type` statements after
  the `@modelable` JSDoc meta block instead of before it (#123).
- Rust emitter now omits `#[serde(skip_serializing_if = "Option::is_none")]`
  from `#[derive(clickhouse::Row)]` projection structs; ClickHouse expects all
  columns present so nullable fields must serialize as NULL, not be absent
  (#124).
- Rust emitter now places bidirectional enum `From` impls only in projection
  (Row) files, not in domain model files, eliminating domain→storage coupling
  (#125).

## [1.0.1] - 2026-06-28

### Fixed

- Rust emitter now emits `#[serde(skip_serializing_if = "Option::is_none")]` on
  omittable (`?`) fields and bare `Option<T>` on nullable fields, correctly
  distinguishing the two semantics (#91).
- Grammar now accepts numeric-prefixed enum member names such as `3gpp`; the
  Rust emitter sanitises them to `_3gpp` with a `#[serde(rename)]` attribute
  (#95).
- TypeScript emitter now generates `import type` statements for `NamedType`
  field references that resolve within the same workspace (#118).
- Rust emitter now generates `impl From<A> for B` between enum types with
  identical variant sets across records in the same domain (#119).
- Rust emitter now emits an `EMIT003` warning when a field references a
  `NamedType` that cannot be resolved, matching TypeScript emitter behaviour
  (#120).

## [1.0.0] - 2026-06-28

### Added

- Rust emitter generates `pub enum` types with serde derives for enum fields
  instead of falling back to `String`. Each enum field produces a named nested
  type (e.g. `CatalogProductV1Status`) with `#[serde(rename)]` applied when
  the Rust member name differs from the wire value.
- TypeScript emitter resolves `ref<X>` to the stable interface name
  (e.g. `AddressAddressV1`) when the referenced model is in the same workspace,
  and emits a corresponding `import type` statement. Unresolvable cross-domain
  references fall back to `string`.
- TypeScript emitter wraps `array<enum(...)>` union types in parentheses:
  `('A' | 'B' | 'C')[]` instead of the previously invalid `'A' | 'B' | 'C'[]`.
- Rust emitter: optional `array<T>` fields now emit `pub field: Vec<T>` with
  `#[serde(default)]` instead of `Option<Vec<T>>`, matching standard Rust
  collection idioms.
- Rust emitter: `@wire(rust.type: "u64")` on an array field now applies to the
  element type inside `Vec<>`.
- Workspace loader deduplicates identical connector binding declarations across
  `.mdl` files. Conflicting definitions (same binding name, different adapter)
  produce a `SEM` diagnostic instead of silently dropping one definition.
- Docker-dependent tests gated behind `MODELABLE_DOCKER_TESTS=1` env var.
- 1.0 stable-surface definition added to `README.md` and `ROADMAP.md`.

### Changed

- `README.md` install instructions updated to the published PyPI package.
- Dropped public-alpha qualifier from repository documentation and policies.

### Stability

- Modelable 1.0 defines a stable surface. See [README § 1.0 stable
  surface](README.md#10-stable-surface) for what is supported and what is
  deferred.
- The `.mdl` language, CLI, and listed artifact formats are stable from 1.0.
  Breaking changes will be documented here and require a major version bump.

## [0.5.0] - 2026-06-14

### Added

- Apache-2.0 licensing and public contribution, conduct, and security policies.
- Public PyPI packaging metadata and trusted-publishing release automation.
- Verified GitHub release assets for the CLI and VS Code extension.
- A public-alpha quick start, roadmap, and maintainer release checklist.
- `modelable --version`.

### Changed

- Reworked documentation around user workflows and current capabilities.
- Removed completed internal implementation plans from the public release tree.

### Stability

- Modelable remains a public alpha. The `.mdl` language, CLI, and generated
  output may change before 1.0; breaking changes will be documented here.

[Unreleased]: https://github.com/ktjn/modelable/compare/v1.0.2...HEAD
[1.0.2]: https://github.com/ktjn/modelable/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/ktjn/modelable/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/ktjn/modelable/compare/v0.5.0...v1.0.0
[0.5.0]: https://github.com/ktjn/modelable/compare/v0.4.0...v0.5.0
