# Roadmap

Modelable's current release is a local compiler and language-server toolchain
for versioned, domain-owned model contracts. The roadmap is directional; an
item is not committed until it has an issue and an accepted design.

## 1.0 — shipped 2026-06-28

Modelable 1.0 stabilizes the local compiler and language-server toolchain.

**Stable at 1.0:** `.mdl` language, CLI commands (`validate`, `compile`,
`check`, `generate`, `attach`, `spec`, language server), all current generated
artifact formats (JSON Schema, TypeScript, C#, Java, Python, Rust, Go, SQL
DDL, dbt `schema.yml`, Markdown, FHIR R4 profile, OpenMetadata JSON,
OpenLineage event, ODCS), compatibility and lineage reports, governance findings,
Apicurio JSON Schema push/pull, and the VS Code extension as a VSIX companion
artifact.

**Deferred from 1.0:** VS Code Marketplace distribution, remote tracked-spec
polling, distributed registry synchronization, live OpenMetadata catalog
synchronization, and runtime subscriptions and materialization. These remain
future candidates until a fresh issue and accepted design define a concrete
implementation slice.

## Next

Recently shipped, still hardening:

- Hosted documentation is published at
  [ktjn.github.io/modelable](https://ktjn.github.io/modelable/) from `main`;
  continue treating broken docs builds and links as release-blocking issues.
- The public conformance fixture under `samples/conformance/` mirrors the
  formerly private release checks for contributor-facing smoke coverage.
- `modelable generate --from` now bootstraps `.mdl` models from dbt
  `manifest.json`/`schema.yml`, FHIR R4 `StructureDefinition`, and ODCS
  documents; continue hardening edge cases (complex FHIR types, dbt
  model-version selection, ODCS field-level nuance) as real usage surfaces
  gaps.
- `modelable attach`/`modelable spec` now track dbt/FHIR/ODCS drift with
  additive/breaking diffs; continue hardening beyond direct-element mapping
  (e.g. complex FHIR types, dbt semantic-layer constructs).
- FHIR R4 profile mapping covers Patient/Observation/Encounter with
  extension/slice mapping for Modelable-only fields and an HL7 FHIR
  Validator smoke; continue hardening deep/recursive structure coverage.
- OpenMetadata and OpenLineage local export are implemented, and
  `modelable sync --lineage marquez` can post OpenLineage events to a
  Marquez-compatible endpoint with a live Testcontainers smoke; continue
  validating OpenMetadata output and hardening live catalog synchronization
  against real consumers.
- Protobuf and Scalable gRPC generation have started as Modelable 1.1 work.
  The current `compile --target protobuf` slice emits deterministic `.proto`
  files and schema manifests for models and projections. The current
  `compile --target grpc` slice emits Protobuf payload schemas, generic
  Scalable command/read services, and service manifests. Deleted-field
  reservations, descriptor sets, richer index metadata, Scalable registration
  fixtures, and protobuf/gRPC compatibility validation remain follow-up work
  before long-lived wire or transport contracts are stable. The accepted design
  target is documented in
  [docs/superpowers/specs/2026-07-04-scalable-protobuf-grpc-support-design.md](docs/superpowers/specs/2026-07-04-scalable-protobuf-grpc-support-design.md).
- Scalable filed a concrete feature-gaps request against Modelable
  (`ktjn/scalable` `docs/analysis/2026-07-07-modelable-feature-gaps.md`,
  8 items). The accepted response — `.mdl` syntax, IR shape, and per-target
  emitter mapping for each item, plus a build order that differs from the
  source document's priority order because several items depend on ones
  ranked lower — is documented in
  [docs/superpowers/specs/2026-07-07-modelable-feature-gaps-response-design.md](docs/superpowers/specs/2026-07-07-modelable-feature-gaps-response-design.md).
  Build order: UUIDv7-compatible `uuid(7)` and wire-format-contract/index-syntax
  completion land in 1.1 alongside the protobuf/gRPC work above; fixed-width
  integer primitives (`u8`..`i128`) and fixed-length `binary(N)` land in 1.2;
  the `semantic` type-alias mechanism lands in 1.3 (depends on 1.2's
  fixed-width integers); deterministic small-integer registry id allocation
  lands in 1.4 (depends on 1.3's `registry: true` marker). The first
  implementation slice — fixed-width integer primitives (`u8`..`i128`) — has
  shipped: grammar, IR, default-value range validation, and a mapping in
  every currently implemented emitter (Rust, Go, Java, C#, Python,
  TypeScript, SQL Postgres/ClickHouse, JSON Schema, Protobuf, FHIR profile),
  per the task-by-task plan at
  [docs/superpowers/plans/2026-07-07-fixed-width-integer-primitives-first-slice.md](docs/superpowers/plans/2026-07-07-fixed-width-integer-primitives-first-slice.md).
  The second slice — fixed-length `binary(N)`, bounded to `1..=4096` bytes —
  has also shipped: grammar, a new `FixedBinaryType` IR node, the length
  bound, and a mapping in Rust, Go, Java, C#, Python, TypeScript, SQL
  Postgres/ClickHouse, JSON Schema, and Protobuf, per the task-by-task plan
  at
  [docs/superpowers/plans/2026-07-08-fixed-length-binary-primitive-first-slice.md](docs/superpowers/plans/2026-07-08-fixed-length-binary-primitive-first-slice.md).
  Modelable 1.2 (both its slices) is now complete. The `semantic` type-alias
  mechanism (1.3) has shipped its first slice: a `semantic Name: Underlying`
  domain-level declaration (grammar, `SemanticTypeDecl` IR node, an optional
  `registry: true` marker for 1.4 to consume), validation of the underlying
  type, chained semantic-type references, and cycle/dangling-reference
  detection, plus a Rust newtype emitter (`#[serde(transparent)]` tuple
  struct with `From`/`Deref` impls). Extending semantic-type support to the
  other emitters (Go, Java, C#, Python, TypeScript, SQL, JSON Schema,
  Protobuf, FHIR, and the rest) is deferred follow-up work — they currently
  resolve a semantic type reference to its underlying type unchanged, per
  the task-by-task plan at
  [docs/superpowers/plans/2026-07-08-semantic-type-alias-mechanism-first-slice.md](docs/superpowers/plans/2026-07-08-semantic-type-alias-mechanism-first-slice.md).
  Modelable 1.4 (deterministic small-integer registry id allocation) has not
  started. A third compatibility signal for state-migration necessity (gap 8
  of that request) remains an open question with no accepted grammar; see
  the response design section 11.

Deferred candidates, not yet started:

- Live OpenMetadata catalog synchronization once local export has enough
  validation evidence for a specific deployment target and a follow-up issue.
- Remote tracked-spec polling and authenticated source access for dbt, FHIR,
  ODCS, and future external specifications (current support is local-file
  only).
- Embedded Modelable authoring for code-first domain models. This future idea
  would let teams declare Modelable-compatible contracts inside a host language
  and compile them into the same normalized graph as `.mdl`. It should remain a
  complement to `.mdl`, not a replacement: embedded declarations should be able
  to render deterministic `.mdl` snapshots for review, source control,
  migration, and long-term portability.

  Possible first slice:

  - Start with Python because the compiler is implemented in Python and can
    statically inspect source with `ast`.
  - Support model/entity/value definitions, fields, versions, optionality,
    keys, PII, classification, owners, and server-assigned fields.
  - Defer projections until the model authoring shape is proven.
  - Avoid importing or executing user modules; extraction should be static.
  - Compile embedded definitions into the existing `MdlFile` IR rather than
    creating a second semantic model.
  - Add a CLI path such as
    `modelable generate --from ./models.py --format embedded-python --output generated.mdl`.

  Pros:

  - Lowers adoption friction for application developers.
  - Lets teams colocate contract metadata with domain classes.
  - Provides an incremental bridge from code-first models to `.mdl`.
  - Reuses existing validation, compatibility, lineage, and emitter pipelines
    if it targets the current IR.
  - Gives Modelable a stronger migration story for Python services and
    frameworks.

  Cons and risks:

  - Host-language syntax can hide Modelable semantics behind framework
    conventions.
  - Multiple host languages could fragment the authoring experience.
  - Runtime reflection would be unsafe and non-deterministic; static extraction
    is required.
  - Some `.mdl` concepts, especially projections and explicit lineage, may map
    awkwardly into ordinary classes.
  - If host-language code becomes the only source of truth, Modelable loses the
    neutral, reviewable, language-independent contract that `.mdl` provides.
  - Versioning can become unclear if class evolution is not explicitly modeled.
  - Tooling burden grows: docs, diagnostics, examples, and editor support may
    need language-specific variants.

  Open design questions:

  - Should embedded definitions be compile-only, or should they always generate
    a canonical `.mdl` file?
  - Is the embedded source allowed to be authoritative, or must generated
    `.mdl` remain the reviewed contract?
  - What minimal annotation/decorator vocabulary maps cleanly to existing
    Modelable IR?
  - How should embedded declarations express versions without relying on git
    history or class names?
  - Should unsupported host-language constructs fail loudly or be ignored with
    warnings?

  Recommendation: treat embedded Modelable as a migration and
  developer-experience bridge. The first accepted design should prove that a
  small embedded Python subset can produce byte-for-byte stable `.mdl` output
  and pass the same compiler and validation path as handwritten `.mdl`.
- VS Code Marketplace distribution.
- Distributed registry synchronization beyond the current file-first model.
- Runtime subscriptions, adapters, replay, and materialization.
- Additional artifact formats driven by concrete consumers.

## Later

- Advanced runtime adapters, materializers, and distributed registry services
  after the deferred candidates above have accepted designs.

See [docs/architecture.md](docs/architecture.md) for the
product model and [GitHub issues](https://github.com/ktjn/modelable/issues) for
work that is ready for discussion or implementation.
