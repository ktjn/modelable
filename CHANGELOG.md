# Changelog

Notable user-facing changes are documented here. Modelable follows Semantic
Versioning, with the usual pre-1.0 allowance that minor releases may contain
breaking changes when they are called out explicitly.

## [Unreleased]

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

[Unreleased]: https://github.com/ktjn/modelable/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/ktjn/modelable/compare/v0.5.0...v1.0.0
[0.5.0]: https://github.com/ktjn/modelable/compare/v0.4.0...v0.5.0
