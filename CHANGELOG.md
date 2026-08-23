# Changelog

Notable user-facing changes are documented here. Modelable follows Semantic
Versioning. Historical 0.x releases used the usual pre-1.0 allowance that minor
releases could contain breaking changes when called out explicitly.

## [Unreleased]

### Added

- Go-to-definition, find-all-references, and rename now work for enum-backed
  `semantic` declarations and `enum projection` declarations, matching the
  support already in place for models and projections (#458, #459, #460).
- The compiler now warns (`POSTCARD` diagnostic) when a domain binds some of
  its models to the `postcard` adapter but leaves a sibling model with
  optional fields unbound, since that model silently keeps the JSON-shaped
  `skip_serializing_if` behavior that postcard cannot decode across
  presence/absence (#439).

### Changed

### Fixed

- Documented that a `postcard` adapter binding's `@ version` only selects
  which field shape resolves `fields:` mappings; the serialization
  suppression itself applies to every version of the bound model, and this
  behavior is now pinned by a regression test (#440).

## [1.10.1] - 2026-08-23

### Added

### Changed

### Fixed

- Rust package manifests no longer enable UUID v4 generation when emitted
  contracts only store and serialize UUID values, allowing generated packages
  to compile for `wasm32-unknown-unknown` without a browser randomness feature.

## [1.10.0] - 2026-08-22

### Added

- Enum contracts are now first-class registry citizens: semantic types and
  enum projections are written as immutable, content-addressed snapshot
  objects with their own canonical signatures; changing an enum's canonical
  content under the same logical version is reported as a changed diff entry,
  and exact enum references (including from semantic declarations) are recorded
  as dependency edges.
- Enum evolution is classified through the owning declaration: `modelable
  diff` reports an enum version bump as `enum_version_changed` with
  member-level detail from the referenced declaration — additions are
  compatible with an exhaustive-consumer note, removals break with the
  removed member named. Switching a field to a different nominal enum is
  `enum_reference_changed` and breaking even when member sets match.
  Anonymous `enum(...)` changes keep their conservative `enum_changed`
  classification. Declaration-level helpers also distinguish explicit pick
  growth from implicit omit growth on enum projections.
- Enum projections: derive a nominal subset from an enum-backed semantic
  declaration at an exact version via `enum projection Name @ 1 (additive)
  from Source @ 1 pick(a, b)` or `omit(...)`. Both forms normalize into the
  exact resulting member identities of the referenced source version; missing
  members, repeated selections, empty results, non-enum sources, unknown
  sources, and name collisions in the shared nominal enum namespace are
  rejected. Projections pinned to an older source version never grow when the
  source gains members.
- Exact versioned semantic-enum references: a field can reference an
  enum-backed `semantic` declaration at an exact version with same-domain
  (`status: OrderStatus @ 1`) or qualified (`status: orders.OrderStatus @ 1`)
  syntax. References validate against the resolved declaration — unknown,
  ambiguous, wrong-version, and non-enum targets are rejected with `ENUMREF`
  diagnostics; enum-backed semantic declarations reject duplicate and empty
  member sets. Anonymous `enum(...)` and unversioned semantic types remain
  source-compatible.
- Exact versioned semantic-enum references resolve exactly: a later declared
  version never re-resolves an earlier published consumer, and requesting a
  missing version is rejected with the known versions listed. Bare semantic
  enum references remain valid authoring syntax but now produce a
  non-blocking `ENUMREF` warning naming the resolved version.
- `modelable diff` documentation now lists the discriminated-union change
  kinds (`union_discriminator_changed`, `union_variant_added`,
  `union_variant_removed`, `union_variant_changed`), and the language
  reference documents how union versions are compatibility-classified.

### Changed

- The normalization boundary is now explicit: `parser.parse_text_to_ir` /
  `parse_file_to_ir` and `compiler.compile_text` / `compile_file` are
  documented as parsing-level APIs returning unresolved per-source
  declarations; canonical normalized contracts come only from
  `compiler.workspace.load_workspace_from_sources`. `modelable attach`
  now reads referenced model versions from the normalized workspace instead of
  re-parsing a single file.
- README's capabilities and playground sections reflect the currently shipped
  artifact targets (OpenAPI, Avro, event-sink) and playground features.
- The release process now reminds maintainers to update ROADMAP.md's "latest
  published release" baseline line, which the automated release flow does not
  touch.

### Fixed

- Generated Rust for a model bound with `adapter: postcard` (and projections
  sourced from it) no longer emits `#[serde(skip_serializing_if =
  "Option::is_none")]` on optional fields. Omittability has no encoding in
  non-self-describing binary formats, so skipping `None` fields silently
  corrupted the stream exactly when an option was absent; `#[serde(default)]`
  is retained and JSON output for unbound models is unchanged.
- Anonymous enum members that collapse to one generated identifier or wire
  value are now caught before emission: Rust and Avro report an `EMIT006`
  diagnostic naming the target, owner, and colliding canonical members;
  Protobuf rejects the collision with a precise error. `@wire(json.case /
  json.overrides)` mappings that map two members onto the same wire value are
  rejected by semantic validation.
- Anonymous `enum(...)` members are now validated centrally before any
  emitter runs: duplicate canonical members are rejected with a diagnostic
  naming the owning field and the conflicting member, recursively through
  arrays, maps, inline objects, and union variants. Empty member sets remain
  a parse error and are now also rejected at the IR level.
- `compile --target rust` no longer generates implicit `From` conversions
  between unrelated enums that merely share the same member set. Enum
  conversions are now generated only from explicit projection lineage (a
  direct mapping from a source model's field), so equal-shaped domain concepts
  can no longer be converted interchangeably. Cross-domain flat-mode lineage
  conversions also now emit valid `super::{domain}::` import paths.
- `compile --target avro` now resolves multi-field named-type references
  (value or entity, same-domain or cross-domain) to their own Avro record
  instead of degrading to a lossy `string`; unresolvable names keep their
  explicit `EMIT002` loss warning.
- `compile --target fhir-profile` now constrains composite direct fields onto
  supported base resources with their real base FHIR type from a per-resource
  element table (for example `Observation.code` → `CodeableConcept`,
  `Patient.address` → `Address`, `Encounter.reasonCode` → `CodeableConcept`)
  instead of the generic `BackboneElement` fallback, so such profiles pass the
  official HL7 FHIR validator. Elements whose real base type genuinely is
  `BackboneElement` are unchanged.
- ROADMAP.md no longer claims 1.9.4 is the latest published release (1.9.5
  shipped on 2026-08-19), and Slice D4 no longer lists union compatibility
  classification as pending work — it shipped in PR #386.

## [1.9.5] - 2026-08-19

### Added

- OpenAPI compilation now validates the complete generated document, including
  paths and operations, against the OpenAPI 3.1 specification.

- `modelable validate-compat --target openapi` now reports breaking changes to
  emitted API schemas, operations, path parameters, request bindings, and
  responses.

- Added deterministic Avro record export with logical types, optional unions,
  arrays, maps, enums, model identity metadata, and explicit loss warnings for
  unsupported shapes.

### Changed

- Reconciled compiler, architecture, and integration documentation with the
  authoritative capability manifest, including model lifecycle status,
  ClickHouse indexes, and Protobuf/gRPC descriptor and compatibility support.

### Fixed

- FHIR Extension StructureDefinitions now declare `Extension.url` as a `uri`,
  including nested object-extension URLs, and resolve named value types to
  valid `value[x]` datatypes so generated snapshots pass the HL7 validator.

- FHIR profile generation now emits extension-slicing elements before
  resource-specific fields (matching every base resource's own structural
  element order), assigns a real `type`/`base`/`definition` to every
  snapshot element (the base `Extension`/`Extension.value[x]` elements
  included), and no longer lets a repeating field's cardinality leak into
  its own `Extension.value[x]` (which is always 0..1 in base FHIR - the
  repetition belongs to the slice that references it). Previously,
  profiles with a composite direct field (e.g. `Patient.contact`) failed
  official HL7 validation with `BackboneElement`-narrowing, missing-type,
  missing-cardinality, and differential/snapshot ordering-mismatch errors.

- Python output now imports referenced value types from sibling modules,
  including same-domain model modules, so resolved annotations are usable.

- ClickHouse secondary indexes containing `DateTime64` columns now use
  `minmax` indexes, avoiding insert-time bloom filter failures.

- `@custom(...)` annotations now parse and round-trip through the canonical
  Modelable renderer.

- FHIR output now emits valid constrained Extension StructureDefinitions,
  including shared `pii` and `classification` extension artifacts.

- Avro defaults for decimal and other structured logical schemas no longer
  fail with an unhashable-schema error.

- OpenAPI imports now emit deterministic, location-specific loss warnings for
  dropped path, operation, root, and reusable component metadata.

- Concurrent compilations now serialize registry ID allocation and atomically
  replace the registry ID ledger, preventing lost allocations and partial lock
  files.

## [1.9.4] - 2026-08-18

### Added

- ClickHouse SQL generation now emits declared secondary indexes as inline
  `bloom_filter` data-skipping indexes on the generated `MergeTree` table,
  matching PostgreSQL's existing secondary-index support. A `unique: true`
  secondary index still emits the index but adds a diagnostic warning since
  ClickHouse `MergeTree` tables cannot enforce uniqueness.

### Changed

- Documented `modelable compile --target openapi` and `--target event-sink`
  in `docs/cli-reference.md` — both were shipped, `implemented` codegen
  targets missing from the CLI reference's `--target` option list, default
  output directory table, and (for `openapi`) any dedicated command section.

### Fixed

- Fixed generated OpenAPI references for `ref<>` fields, aligned Rust JSON
  field names with the canonical source spelling, preserved optional fields in
  TypeScript projections, and made PostgreSQL foreign keys honor bound table
  names.
- Fixed browser and Playground wheel builds failing after the Hatchling
  dependency update due to mismatched build constraints.
- Fixed the browser/Playground compiler silently dropping every emitter's
  generation warnings (type-loss, missing-metadata, and similar) — the
  `compile` request now carries each generated artifact's warnings through to
  the client instead of discarding `EmittedArtifact.warnings`, matching what
  the CLI already prints.
- Compatibility validation now flags changed compiled Protobuf and gRPC
  descriptor hashes for review instead of silently ignoring descriptor drift.

## [1.9.3] - 2026-08-17

### Added

### Changed

### Fixed

- The Go, Java, Python, and C# emitters no longer blanket-import every other
  domain's types into every generated file; cross-domain imports are now
  reference-scoped to only the domains a file actually references, so a pure
  value type compiles standalone.
- Cross-domain semantic-type references (e.g. `patient.PatientId`) are now
  emitted inline as their underlying primitive (UUID/string/Guid/etc.) instead
  of a bogus pascalized type name that never exists, across all four emitters.
- The Go emitter now emits a `go.mod` (module derived from the workspace name,
  e.g. `modelable/modelable_clinic`) so cross-domain imports resolve, and the
  shared `named_types` dict is no longer mutated in place across artifacts
  (which previously produced double-qualified names like
  `scheduling.scheduling.SchedulingTimeRangeV0`).

## [1.9.2] - 2026-08-16

### Added

### Changed

### Fixed

- Fixed cross-domain status-enum `From` impls in package-mode Rust emission
  importing via `super::{domain}::` (invalid for sibling top-level modules in
  the same crate) instead of `crate::{domain}::`.

## [1.9.1] - 2026-08-16

### Added

- Added discriminated-union compatibility findings for discriminator, variant,
  and variant-shape changes.

### Changed

### Fixed

- Fixed duplicate `#[serde(default)]` attributes in generated Rust value types.

## [1.9.0] - 2026-08-16

### Added

- Added discriminated union field types with JSON Schema and OpenAPI `oneOf`/`discriminator` output.

- Added first-class field value constraints for numeric bounds, string lengths,
  patterns, formats, array item counts, and uniqueness, with JSON Schema output.

- Added explicit offline registry snapshots with deterministic content-addressed
  objects and `modelable registry resolve`, `verify`, `status`, and `prune`.
- Added `modelable registry usage` for application-facing usage graphs and compact exact
  contract manifests.
- Added offline `modelable registry diff` and staged `registry update` commands
  with candidate validation and atomic lock replacement.
- Added `modelable impact` consequence reports with machine-readable actions
  and causal paths for model changes.
- Added `modelable config explain` and opt-in `modelable.toml` defaults for
  inherited auto-projections with provenance reporting.
- Added target-neutral `conversions` proof reports and non-executable
  `migration plan` facts for model evolution.
- Added offline `modelable doctor` diagnostics for workspace, configuration,
  snapshot, and capability integrity.
- Added a deterministic machine-readable artifact manifest to every compilation
  output, including input, snapshot, target, artifact, and loss metadata.

### Changed

- Propagated field constraints through generated and direct projection views so
  JSON Schema output preserves source validation semantics.
- Added reusable semantic enum types that resolve to enum-valued JSON Schema
  properties while retaining their domain-qualified identity in the IR.
- Added versioned semantic declarations with additive enum evolution checks and
  latest-version resolution for generated targets.

- Extended `modelable doctor` to verify the derived registry index and detect
  stale or tampered generated artifacts from their manifests.

### Fixed

- Fixed cross-domain generated-language imports, Rust projection enum
  conversions, Rust optional-field deserialization defaults, and JSON Schema /
  ODCS round-trip handling for referenced declarations.

## [1.8.0] - 2026-08-16

### Added

- The registry manifest now enumerates each model with its schema version,
  canonical content signature, and registry-backed key identity when one is
  allocated, so health and drift contracts can consume one generated artifact.
- `modelable compile --target event-sink` now emits a deterministic,
  adapter-neutral change-event envelope, payload schemas, operation coverage,
  and transactional outbox contract for event projections.
- Model fields now distinguish legacy presence (`field?`) from explicit
  nullability (`field: type?` and `field?: type?`), and JSON Schema/OpenAPI
  artifacts preserve both dimensions.
- OpenAPI imports now accept JSON and YAML documents, traverse all component
  schemas deterministically, preserve `x-modelable` metadata, and resolve
  versioned component references. Multi-schema imports require an explicit
  schema selection instead of silently importing the first entry.
- OpenAPI imports now report explicit warnings when unsupported unions,
  composition, nullability, or value constraints are dropped during import.
- OpenAPI imports now also report dropped operation, request/response, and
  security metadata instead of silently discarding API-level contract details.
- `modelable compile --target openapi` emits a deterministic OpenAPI 3.1
  document with `components.schemas` and explicit `paths`/operations
  from `request`/`reply`/`event` auto-projections and hand-authored
  projections. API declarations support versioned operations, key-based path
  parameters, JSON request bodies, and projection-backed responses.
- OpenAPI export now orders schemas and operations by stable contract identity,
  so equivalent workspaces produce reproducible artifact ordering.

### Changed

- OpenAPI API-version compatibility now reports operation additions/removals,
  renames, method/path and path-key changes, request-contract changes, and
  response status/projection changes from normalized Modelable IR.

### Fixed

- Fixed validation and compilation gaps across parser diagnostics, semantic-type
  resolution, CEL operand checks, versioned auto-projections, governance diffs,
  protobuf reservations, and TypeScript imports for semantic and projection
  fields.
- Fixed Rust compilation output for optional arrays whose elements are named
  types, preserving the generated type name and import.
- Generated PostgreSQL DDL now includes model keys, value-object `JSONB`
  columns, and foreign-key constraints for resolvable `ref<>` fields.
- Rust option fields now use symmetric serde defaults, and registry-id ledgers
  default beside the source workspace when invoked through the CLI.
- Added the `registry` target for a deterministic contract inventory containing
  schema versions, signatures, and allocated semantic registry IDs.
- Added canonical temporal defaults: Rust emits chrono-backed date/time types,
  PostgreSQL preserves ISO-8601 durations as text, and `rust.type`/
  `postgres.type` wire hints provide explicit overrides.
- Fixed C#, Java, Python, and Go emitters so named model references resolve to
  emitted versioned names and semantic-typed fields never reference undefined
  generated types.
- Fixed gRPC service package collisions, PostgreSQL secondary-index name
  collisions, and invalid nullable ClickHouse arrays.

## [1.7.0] - 2026-08-14

### Added

- Added a host-registered Playground plugin contract for deterministic custom
  artifact viewers, with API-version, identity, and file-extension validation.

### Changed

- Upgraded the documentation index and retrieval integration to Searchable
  2.0.1, the consolidated lexical-only Python package. The browser runtime now
  ships one `searchable` wheel instead of the retired split packages.

### Fixed

## [1.6.0] - 2026-08-10

### Added

### Changed

### Fixed

- Fixed `modelable compile` emitting Rust semantic types with `uuid(N)` or
  `json` underlying types without the required `// requires:` comment, so the
  multi-package code generator now includes the `uuid`/`serde_json`
  dependencies in the generated package's `Cargo.toml`.

## [1.5.1] - 2026-08-10

### Added

### Changed

### Fixed

- Fixed the one-click release workflow (added in 1.5.0) failing to complete
  a release end-to-end: `prepare_release.py` now also bumps
  `cli/browser/pyproject.toml` in lockstep with `cli/pyproject.toml` (the
  browser wheel build previously refused to proceed on a mismatch), the
  tag-release job configures a git identity before creating the annotated
  tag, and the tag push now authenticates with a dedicated `RELEASE_TAG_TOKEN`
  so `release.yml`'s publish trigger actually fires instead of silently
  never running under the default `GITHUB_TOKEN` (GitHub does not let
  workflow runs cascade from events triggered by that token).

## [1.5.0] - 2026-08-10

### Added

- Added multi-package code generation for the Rust emitter: a `package {}`
  block inside `workspace {}` maps domains to named output packages, and the
  Rust emitter auto-switches to a multi-crate layout
  (`out/{pkg}/src/{domain}/`, generated `Cargo.toml`, `lib.rs`, per-domain
  `mod.rs`) with correct cross-package import paths and cycle detection on
  inter-package dependencies. `modelable compile --package NAME` scopes
  generation to a single package. Single-crate output is unchanged when no
  packages are defined.
- Added a one-click manual release workflow (`Prepare release` GitHub Actions
  dispatch) that bumps the CLI/extension versions, moves the `Unreleased`
  changelog entries into a dated section, regenerates the CLI lockfile, and
  opens a `Release <version>` PR; a companion workflow tags the release once
  that PR merges, so the normal publish pipeline runs without hand-editing
  version files or the changelog.

### Changed

- Bumped the pinned `searchable-*` dependencies to their current releases:
  `searchable-analysis` to `0.2.3`, `searchable-binary` to `0.1.1` (new),
  `searchable-client` to `0.4.2`, and `searchable-indexer` to `0.2.3`. The
  CLI/LSP (`cli/uv.lock`) and the Playground browser wheel
  (`cli/browser/browser-lock.json`) were both updated, keeping the two
  lockfiles in sync.
- The language reference now documents that a projection `pick(...)`/`omit(...)`
  clause may be combined with additional body fields, and its `omit(...)`
  example no longer redeclares retained source fields.

### Fixed

- `@classification("level")` annotation selectors (in `pick(...)`, `omit(...)`,
  and `auto projections ... exclude [...]`) now match only fields carrying the
  exact requested classification level instead of any classification annotation,
  so e.g. `omit(@classification("secret"))` no longer drops fields classified
  `internal`/`confidential`/`restricted`/`open`.

## [1.4.0] - 2026-08-08

### Added

- Added `modelable.llm.provider`, `modelable.llm.model`, and
  `modelable.llm.baseUrl` settings to the VS Code extension so the `@modelable`
  chat participant's LLM can be picked from the extension Settings UI (provider
  and common model drop-downs) instead of environment variables only. Non-empty
  values are forwarded to the language server as
  `MODELABLE_LLM_PROVIDER`/`MODELABLE_LLM_MODEL`/`MODELABLE_LLM_BASE_URL`.
- Added `modelable models` to list models installed on a local Ollama server,
  resolving the base URL from `--base-url`, `MODELABLE_LLM_BASE_URL`, or
  `OLLAMA_HOST` the same way other provider-backed commands do.
- Added an Ollama provider option to the Playground assistant, alongside
  WebLLM, for users running a local Ollama server.
- Added a "Reload demo data" button to the Playground toolbar. Previously the
  built-in example workspace could only be restored by way of the recovery
  screen shown for corrupted local storage; the new button discards local
  changes and reloads it on demand, behind the same confirmation prompt used
  for other destructive workspace actions.

### Fixed

- Fixed automatic documentation routing failing to ground natural-language
  questions like "what does additive mean" in chat, causing the assistant to
  answer from the ordinary conversational path instead of the documentation
  index (the explicit `/docs` command already worked correctly). The
  deterministic intent classifier's automatic-routing signals now recognize
  definitional phrasing ("what is X", "what does X mean", "define X"), and
  "make" was added to the mutation-verb list so workspace-editing requests
  like "how do I make email optional" still route to the update planner
  instead of documentation retrieval. Also bumped `searchable-client` to
  `0.4.0` and `searchable-indexer` to `0.2.1`, which pull in a
  `searchable-analysis` fix for English stopword filtering — the underlying
  cause of the routed query still returning no relevant results.
- Fixed the VS Code extension and web Playground syntax highlighting dropping
  the `pick`/`omit` projection keywords (added with the Slice H1 feature) and
  the `replacedBy` keyword used inside `@deprecated`. The TextMate and Monarch
  keyword lists are now generated from the canonical `modelable.lark` grammar
  (`cli/scripts/render_editor_grammars.py`) so editor highlighting can no
  longer drift from the parser, and a drift test enforces that in CI.

## [1.3.0] - 2026-08-02

### Added

- Bundled a documentation search index directly into the CLI and LSP. Users no longer
  need to provide an explicit index path for documentation questions in `chat`
  or IDE contexts; the bundled index is used by default.
- Enabled automated service worker updates for the browser Playground. The
  application now detects and applies new versions in the background, ensuring
  users always run the latest release without manual refresh prompts.
- Added multi-language support to the browser Playground, enabling generation of
  TypeScript, SQL (Postgres/ClickHouse), Protobuf, Rust, Java, Go, C#, Markdown,
  and Python artifacts directly in the browser.
- Updated the default Playground example to a more complex three-file workspace
  (`customer.mdl`, `sales.mdl`, `billing.mdl`) demonstrating cross-file
  references and multi-domain organization.
- Added syntax highlighting for the `modelable` language in both the web Playground
  and the VS Code extension. The Monarch tokenizer (web) and TextMate grammar (vscode)
  now support all keywords, types, operators, and comments from the core grammar,
  enabling rich code display in the editor and AI previews.
- Added local conversational compilation to `modelable chat` and the native
  VS Code `@modelable` participant. Deterministic `/compile` and typed
  natural-language plans now stage the real compiler output without workspace
  writes, explain affected definitions and exact text/binary file evidence,
  require literal or native Apply authorization, reject stale or dirty
  destinations, promote the captured bytes with rollback, and write
  privacy-preserving compilation audit records. Direct `modelable compile`
  remains available for previews above the 2 MiB conversation limit.
- Added a static browser compiler proof at `/modelable/playground/`. The
  same-origin Pyodide worker uses the existing Modelable compiler to validate
  and format in-memory sources and generate JSON Schema through protocol v1,
  with native/browser conformance, performance, and asset-size budgets enforced
  by the browser validation gate.
- Added a durable multi-file workspace to the browser Playground. Users can
  create, import, rename, delete, select, and edit `.mdl` files; validate and
  generate JSON Schema from the complete workspace; restore the workspace
  automatically from IndexedDB; continue in memory when storage is
  unavailable; and explicitly export or reset invalid stored state. Source
  remains local, while compiler output is not persisted.
- Added visualization MVP to the browser Playground. The compiler exposes
  `workspace.graph` through the browser protocol with domain and entity
  visualization modes. ELK.js lays out the semantic graph in a dedicated web
  worker. React Flow renders positioned nodes with custom components carrying
  non-color-only kind indicators (D/E/V/F/P badges). The graph panel supports
  desktop collapse/expand with CSS resize, mobile tabbed Source/Graph
  switching, keyboard navigation, screen-reader labels, and
  `prefers-reduced-motion` support. Performance budgets enforce ≤ 200 ms
  median graph operations.
- Completed browser-native language services in the Playground.
  Protocol v2 synchronizes the complete workspace after a 300 ms edit debounce,
  publishes exact-revision live diagnostics without requiring Validate, and
  provides Monaco completion, hover, go-to-definition, find-all-references,
  and rename using current text plus the last parseable semantic snapshot.
  Stale provider results are discarded, hover Markdown is rendered as untrusted
  non-HTML content, rename validates identifiers and carries optimistic
  concurrency metadata, and all derived language results remain memory-only.
- Added safe conversational workspace management to `modelable chat`:
  grounded ownership, lineage, dependency, index, compatibility, and
  validation questions; complete entity and projection proposals through
  closed typed plans; compatibility-aware textual diffs with affected
  definitions; refinement and discard; and explicit fingerprint-protected
  application with rollback and workspace reload. Deterministic questions
  remain available offline, while mutation synthesis requires a configured
  provider.
- Added the native VS Code `@modelable` chat participant for grounded
  workspace questions and safe entity, projection, and contract management
  through the Python language-server service. It includes active-editor focus,
  saved-source enforcement, affected-definition anchors, exact virtual
  before/after diffs, apply/discard follow-ups, reset, bounded session cleanup,
  restart recovery, and privacy-safe lifecycle logging.
- Added source-level Protobuf field reservations and
  `validate-compat --target protobuf|grpc` compatibility validation.
- Added opt-in Protobuf and gRPC descriptor artifact generation via
  `compile --target protobuf|grpc --descriptor-set`.
- Protobuf and gRPC generation now preserve semantic types as stable
  declaring-domain wrapper messages and expose semantic refs, registry IDs,
  canonical Modelable signatures, and target-specific wire fingerprints in
  schema manifests.
- Added native Protobuf map emission for supported `map<K,V>` fields and
  clear failures for unsupported map shapes.
- Added declared primary/secondary index metadata to Protobuf schema manifests
  and gRPC service manifests.
- Generated Rust registry-backed semantic newtypes now expose their allocated
  ID as `REGISTRY_ID`. Generated Rust models and projections expose
  `SCHEMA_VERSION` and the canonical Modelable signature as a dependency-free
  `[u8; 32]` `SCHEMA_CONTENT_SIGNATURE`.

### Fixed

- Playground graph panel: the graph now renders. Layout ran ELK from inside a
  dedicated web worker, where `elk.bundled.js` cannot construct its in-thread
  worker, so the worker crashed on load and every mode sat on
  "Laying out graph…" forever. ELK is now driven from the panel and runs the
  layout in its own worker.
- Playground graph panel: the graph follows the source. It was fetched once
  after startup and never again, so it kept showing the model as it was when
  the page loaded. It is now refetched whenever the compiler finishes
  synchronizing a new workspace revision.
- Playground graph panel: the view now zooms to fit each new layout instead of
  fitting an empty canvas before the nodes arrive, and node handles sit on the
  sides the layout flows between rather than always top/bottom.
- Playground graph panel: failed graph requests and failed layouts now report
  the failure in the panel instead of leaving a silently blank canvas.
- Playground graph panel: graph nodes no longer claim `role="treeitem"`
  outside any tree, and edge labels no longer sit on a bare SVG path where
  they are not exposed. Node and edge names now go on the wrappers React Flow
  renders, which carry a valid role.
- Playground chat: a change request that the AI model gets wrong (e.g.
  referencing a model/version that doesn't exist) now gets two automatic
  corrective retries instead of one, and if it still fails, the chat shows
  a clear explanation instead of the raw internal error text.

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
