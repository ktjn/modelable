# Emitter Extension Overlays

**Status:** Proposal  
**Scope:** Separate semantic Modelable language concerns from emitter-specific representation configuration.

## 1. Problem

Modelable's `.mdl` language should describe the meaning, structure, lineage, compatibility, and governance of data. It should not accumulate representation details for every emitter.

The current language includes target-specific concepts such as `@wire(...)`, target-specific type overrides, Protobuf reservations, and generation configuration. These create several problems:

- every new emitter expands the language surface;
- canonical model signatures risk depending on backend configuration;
- target-specific changes can appear as semantic model changes;
- emitters become coupled to parser and grammar evolution;
- the core language becomes harder to reason about and harder to keep stable;
- emitter plugins cannot evolve their own configuration independently.

The core design rule is:

> `.mdl` describes data semantics. Emitter extensions describe target representation.

## 2. Goals

1. Keep `.mdl` target-neutral.
2. Move emitter-specific configuration into separate TOML extension files.
3. Let each emitter own and version its configuration schema.
4. Make extension files schema-aware in editors, especially VS Code through Taplo/JSON Schema integration.
5. Keep semantic model identity independent from emitter configuration.
6. Preserve target-specific compatibility checks where required.
7. Allow third-party emitters to add configuration without changing the Modelable grammar.
8. Provide a gradual migration path from existing target-specific DSL constructs.

## 3. Non-goals

- Replace `modelable.toml` as the workspace/compiler configuration file.
- Move semantic constraints, governance, lineage, or lifecycle behavior out of `.mdl`.
- Define one global configuration schema containing every emitter's options.
- Introduce another custom DSL.

## 4. Semantic Boundary

A construct belongs in `.mdl` when independent consumers need it to agree on the meaning of the data.

Examples:

- model and field names;
- entities, aggregates, values, and events;
- field types;
- nullability;
- semantic defaults;
- value constraints;
- identity;
- projections and lineage;
- computed fields;
- domain ownership;
- PII and classification metadata;
- semantic lifecycle/history rules;
- semantic versioning and compatibility.

A construct belongs in an emitter extension when it is only required to produce or consume one target representation.

Examples:

- Rust concrete type overrides;
- Serde attributes;
- Java package names;
- C# namespaces;
- PostgreSQL schemas and table names;
- PostgreSQL type overrides;
- indexes and storage-specific options;
- Protobuf field numbers, reservations, package/options;
- OpenAPI-specific annotations;
- Avro logical representation overrides;
- generated file naming;
- emitter-specific naming conventions.

### 4.1 Semantic versus representation example

This is semantic and belongs in `.mdl`:

```mdl
createdAt: timestamp
```

The semantic contract can define `timestamp` as a UTC instant with the precision guarantees Modelable chooses.

These are representation decisions and belong outside `.mdl`:

- JSON: RFC 3339 string;
- Protobuf: `google.protobuf.Timestamp`;
- PostgreSQL: `timestamptz`;
- Rust: `time::OffsetDateTime` or `chrono::DateTime<Utc>`.

## 5. File Layout

Recommended workspace layout:

```text
modelable.toml
models/
  customer/
    Customer.mdl
modelable.extensions/
  rust.toml
  postgres.toml
  protobuf.toml
  openapi.toml
```

`modelable.toml` remains workspace/compiler configuration.

`modelable.extensions/*.toml` contains structured target overlays.

The extension directory name should be configurable, but `modelable.extensions/` is the default convention.

## 6. Extension File Envelope

Every extension file uses a small common envelope. The rest of the document is emitter-owned.

Example:

```toml
#:schema https://modelable.dev/schemas/extensions/postgres/v1.schema.json

emitter = "postgres"
version = 1

[models."customer.Customer"]
table = "customers"
schema = "customer"

[models."customer.Customer".fields.customerId]
type = "uuid"

[models."customer.Customer".fields.createdAt]
type = "timestamptz"
```

Required common fields:

```text
emitter
version
```

Everything else is interpreted by the selected emitter according to its schema.

The core compiler must not need knowledge of emitter-specific keys such as `table`, `serde`, `package`, or `type`.

## 7. Reference Model

Extension files target semantic objects using stable Modelable references.

Recommended forms:

```text
customer.Customer
customer.Customer@2
customer.Customer.customerId
customer.Customer@2.customerId
billing.BillingCustomer
```

Rules:

1. Unversioned model references apply to all compatible versions unless the emitter schema defines a narrower rule.
2. Versioned references apply only to that model version.
3. Version-specific configuration overrides unversioned configuration.
4. Field references must resolve against the semantic model before emitter execution.
5. Unknown model or field references are errors by default.
6. Emitters may explicitly define opt-in support for unmatched patterns, but silent typos are forbidden.

The compiler should perform reference resolution centrally so emitters do not each reimplement Modelable name resolution.

## 8. Configuration Resolution

Compilation becomes:

```text
.mdl
  -> parse
  -> semantic validation
  -> semantic IR
  -> resolve emitter extension
  -> validate extension schema
  -> resolve extension references
  -> target planning
  -> emitter
  -> artifact
```

The semantic IR must be complete before extensions are applied.

Emitter extensions must not mutate the semantic IR. They produce target-specific configuration or target IR layered on top of it.

Architectural invariant:

> An emitter extension may change representation, but must not change semantic meaning.

If an emitter option would change semantic meaning, it must either become a core Modelable concept or be rejected as invalid emitter configuration.

## 9. Workspace Configuration

`modelable.toml` selects targets and extension files.

Example:

```toml
[[target]]
name = "rust"
extension = "modelable.extensions/rust.toml"
out = "generated/rust"

[[target]]
name = "postgres"
extension = "modelable.extensions/postgres.toml"
out = "generated/sql"
```

The CLI may continue to support explicit target selection:

```bash
modelable compile models --target postgres
```

Resolution order:

1. explicit CLI extension path, if provided;
2. target entry in `modelable.toml`;
3. conventional `modelable.extensions/<target>.toml`;
4. no extension file, using emitter defaults.

Recommended optional CLI override:

```bash
modelable compile models \
  --target postgres \
  --extension ./modelable.extensions/postgres.production.toml
```

## 10. Editor Support

TOML extension files should use JSON Schema for validation and completion.

Taplo supports schema-aware TOML editing in VS Code.

Each emitter should publish a versioned JSON Schema.

Example:

```toml
#:schema https://modelable.dev/schemas/extensions/postgres/v1.schema.json
```

Expected editor capabilities:

- TOML syntax highlighting;
- completion;
- validation;
- enum suggestions;
- hover documentation;
- required-field diagnostics;
- type validation;
- deprecation markers where supported.

Modelable should also support local schema distribution for offline environments.

Recommended built-in schema location:

```text
modelable schemas extension postgres --version 1
```

or a stable package/resource path exposed by the installed CLI.

A generated workspace may use a local schema URI where external network access is unavailable.

## 11. Emitter-Owned Schemas

Each emitter owns:

- its extension schema;
- configuration versioning;
- defaults;
- validation beyond JSON Schema where necessary;
- migration between extension schema versions;
- documentation.

The core owns only:

- extension discovery;
- common envelope validation;
- schema lookup;
- Modelable reference resolution;
- target identity;
- diagnostics plumbing;
- manifest/hash integration.

Third-party emitters must be able to ship their own extension schema without modifying the Modelable parser.

## 12. Identity and Hashing

Emitter configuration must not affect canonical semantic identity.

Define separate identities.

### 12.1 Semantic signature

```text
semantic_signature = hash(normalized semantic IR)
```

Only semantic Modelable content contributes.

Changing PostgreSQL table names, Rust types, or Protobuf numbering does not change `semantic_signature`.

### 12.2 Artifact signature

```text
artifact_signature = hash(
  semantic_signature,
  emitter_identity,
  emitter_version,
  extension_schema_version,
  normalized_extension_configuration,
  resolved_target_profile
)
```

This allows deterministic regeneration and cache invalidation without pretending representation changes are semantic changes.

The artifact manifest should record both signatures.

## 13. Compatibility

Semantic and target compatibility must remain separate concepts.

### 13.1 Semantic compatibility

```bash
modelable diff customer.Customer@1 customer.Customer@2
```

This evaluates the semantic model only.

Emitter extension changes must not appear as semantic compatibility findings.

### 13.2 Target compatibility

```bash
modelable validate-compat \
  --from old \
  --to new \
  --target protobuf
```

This evaluates:

- semantic changes relevant to the target;
- old emitter extension state;
- new emitter extension state;
- target-specific compatibility rules.

This is the correct layer for representation contracts such as Protobuf field numbering.

## 14. Protobuf

Protobuf is the strongest example of configuration that is target-specific but compatibility-critical.

Current DSL constructs such as:

```mdl
reserved protobuf {
  numbers: [3, 7]
  names: ["legacy_status"]
}
```

should move to the Protobuf extension.

Example:

```toml
#:schema https://modelable.dev/schemas/extensions/protobuf/v1.schema.json

emitter = "protobuf"
version = 1

[models."customer.Customer@3"]
reserved_numbers = [3, 7]
reserved_names = ["legacy_status"]

[models."customer.Customer@3".fields.customerId]
number = 1
```

These values do not change the semantic model but do change Protobuf compatibility.

The Protobuf compatibility checker therefore consumes both semantic IR and resolved Protobuf extension state.

## 15. Generation Declarations

Target generation configuration should not live in `.mdl`.

If the language currently allows constructs such as domain/workspace `generate` blocks, deprecate them in favor of `modelable.toml` target configuration.

Rationale:

- generation is a build concern;
- two consumers may generate different targets from the same semantic models;
- model packages should not need editing when downstream build requirements change;
- keeping targets outside `.mdl` improves reuse of canonical models.

Target selection belongs in workspace/tool configuration, not the semantic contract.

## 16. `@wire` Migration

`@wire(...)` should be deprecated.

Example current usage:

```mdl
@wire(rust: { type: "chrono::DateTime<Utc>" })
createdAt: timestamp
```

Equivalent extension:

```toml
[models."customer.Customer".fields.createdAt]
type = "chrono::DateTime<Utc>"
```

Migration tooling should be provided where conversion is deterministic.

Recommended command:

```bash
modelable migrate emitter-extensions models
```

The command should:

1. parse current target-specific annotations;
2. create or merge `modelable.extensions/<target>.toml`;
3. remove migrated target metadata from `.mdl`;
4. preserve semantic content;
5. produce diagnostics for constructs that cannot be migrated automatically.

## 17. Extension Composition

Support layered extension files where useful.

Example use cases:

- organization defaults;
- repository defaults;
- environment-specific overrides;
- local developer overrides.

Recommended resolution:

```text
emitter defaults
  < workspace extension
  < explicit CLI extension
```

Avoid introducing implicit environment-specific files such as `postgres.prod.toml` unless explicitly referenced. Hidden configuration selection makes builds difficult to reproduce.

All resolved layers must contribute to the artifact signature.

## 18. Diagnostics

Diagnostics should identify both the Modelable reference and extension source.

Example:

```text
EXT-PG-004 modelable.extensions/postgres.toml:18
customer.Customer.createdAt: PostgreSQL type "timestamp" loses the core timestamp timezone guarantee; use "timestamptz" or explicitly acknowledge semantic loss.
```

Important classes:

- unknown emitter;
- unsupported extension schema version;
- schema validation failure;
- unresolved model reference;
- unresolved field reference;
- illegal semantic mutation;
- target representation loss;
- target compatibility break.

## 19. Semantic Loss

Some target representations cannot exactly preserve Modelable semantics.

Extensions must not silently redefine semantics to make an emitter happy.

Instead, emitters report semantic loss through the existing artifact/diagnostic mechanism.

Example:

```text
Modelable decimal(38,10)
    -> target cannot preserve precision
    -> emitter diagnostic / semantic-loss fact
```

An extension may select among available representations, but cannot suppress an actual semantic mismatch unless Modelable has an explicit acknowledgement mechanism.

## 20. Plugin API Impact

Emitter/plugin API should receive:

```text
SemanticIR
ResolvedEmitterExtension
EmitterContext
```

Conceptually:

```python
def emit(model, extension, context):
    ...
```

`ResolvedEmitterExtension` should contain:

- emitter id;
- extension schema version;
- normalized configuration;
- resolved Modelable references;
- configuration provenance;
- deterministic configuration hash.

The plugin should not parse workspace TOML itself.

## 21. Schema Versioning

Emitter extension schemas are versioned independently from the Modelable language.

Example:

```toml
emitter = "postgres"
version = 2
```

Rules:

- schema version is mandatory when an extension file exists;
- unsupported versions fail clearly;
- emitter schema changes do not require a new `.mdl` language version;
- migration tooling may upgrade extension files independently;
- artifact manifests record the schema version.

## 22. Security

Extension files are configuration, not executable code.

Do not allow:

- arbitrary code execution;
- shell interpolation;
- environment-variable interpolation inside arbitrary values by default;
- dynamic imports from extension files;
- schema URLs that automatically execute tooling.

If environment substitution is eventually required, define it explicitly in `modelable.toml` and include the resolved values or their safe fingerprints in reproducibility metadata.

External JSON Schemas should not be required at compile time. Built-in/installed schemas are authoritative for compilation; schema URLs primarily support editor tooling.

## 23. Proposed Deprecations

Deprecate target-specific constructs in `.mdl`, including at minimum:

- `@wire(...)`;
- `reserved protobuf`;
- target-specific `generate` blocks;
- future target-specific annotations or keywords.

Before adding any new `.mdl` construct, apply this test:

> Does this describe the meaning of the data independently of any output technology?

If no, it belongs in emitter/workspace configuration.

## 24. Implementation Plan

### Phase 1 — Infrastructure

1. Introduce the emitter extension envelope.
2. Add conventional discovery from `modelable.extensions/<target>.toml`.
3. Add `modelable.toml` target-to-extension mapping.
4. Add TOML parsing and normalization.
5. Add common envelope validation.
6. Add centralized semantic-reference resolution.
7. Include normalized extension hashes in artifact manifests.

### Phase 2 — Schema tooling

1. Define JSON Schema conventions for emitter extensions.
2. Add schemas for built-in emitters.
3. Add Taplo-compatible `#:schema` examples.
4. Ship schemas with the CLI for offline use.
5. Add `modelable schemas` inspection/export command.

### Phase 3 — Migrate `@wire`

1. Inventory every current `@wire` consumer.
2. Add equivalent emitter-extension properties.
3. Make emitters prefer extension configuration.
4. Add migration tooling.
5. Warn on legacy `@wire` use.
6. Remove `@wire` from semantic signatures immediately when safe, even during the deprecation period.

### Phase 4 — Protobuf state

1. Move field-number and reservation configuration into the Protobuf extension schema.
2. Update `validate-compat --target protobuf` to consume extension state.
3. Add migration from `reserved protobuf`.
4. Deprecate DSL syntax.

### Phase 5 — Generation config

1. Move target/generation configuration to `modelable.toml`.
2. Make existing `generate` blocks compatibility aliases during migration.
3. Add migration diagnostics.
4. Remove generation concerns from the grammar in the next planned breaking language revision.

### Phase 6 — Plugin contract

1. Extend emitter API with `ResolvedEmitterExtension`.
2. Publish extension-schema registration API.
3. Ensure third-party emitters can own schemas without core changes.
4. Add plugin contract tests proving unknown target-specific keys never enter semantic IR.

## 25. Acceptance Criteria

The work is complete when:

- a canonical `.mdl` model contains no built-in emitter names or target-specific representation configuration;
- adding a new emitter does not require changing the Modelable grammar;
- Rust/PostgreSQL/Protobuf-specific options can be configured in separate TOML files;
- VS Code + Taplo provides schema-aware completion and validation for extension files;
- semantic signatures are unchanged when only emitter configuration changes;
- artifact signatures change when relevant emitter configuration changes;
- `modelable diff` ignores emitter-only representation changes;
- `modelable validate-compat --target ...` still detects target-specific compatibility breaks;
- Protobuf numbering/reservations work entirely outside the semantic DSL;
- existing target-specific DSL constructs have an explicit migration path;
- extension files work in offline environments without fetching remote schemas.

## 26. Design Principle

The long-term architecture should remain:

```text
MDL
  = canonical semantic contract

modelable.toml
  = workspace/build configuration

modelable.extensions/*.toml
  = emitter-specific representation overlays

emitter
  = semantic IR + resolved overlay -> artifact
```

This separation prevents emitter growth from causing language growth and gives Modelable a stable semantic core while allowing representation targets to evolve independently.
