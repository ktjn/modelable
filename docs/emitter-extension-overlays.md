# Emitter Extension Overlays

**Status:** Accepted stabilization direction  
**Authority:** [`docs/architecture.md`](architecture.md) §14 and [`ROADMAP.md`](https://github.com/ktjn/modelable/blob/main/ROADMAP.md) Phase 4 define the normative direction. This document provides the detailed overlay model.

## 1. Purpose

Modelable `.mdl` describes semantic meaning. Target-specific representation belongs outside the semantic language.

Emitter extension overlays provide deterministic, schema-aware target configuration without turning every framework/database/serializer requirement into new grammar.

The core rule is:

> `.mdl` describes data semantics. Overlays describe target representation.

## 2. Non-goals

Overlays do not:

- change semantic meaning;
- execute code;
- replace `modelable.toml` as workspace/build configuration;
- carry compatibility-critical allocation state that must survive independently of optional configuration;
- become a second source of truth for declaration identity/versioning/lineage.

## 3. File layout

Recommended convention:

```text
modelable.toml
models/
modelable.extensions/
  csharp.toml
  postgres.toml
  protobuf.toml
```

Each target owns a versioned configuration schema.

## 4. Common envelope

Example:

```toml
#:schema ./schemas/modelable/postgres-overlay-v1.schema.json

target = "sql-postgres"
version = 1
```

Required common fields:

```text
target
version
```

Target-owned keys follow the common envelope.

## 5. Canonical identity keys

Overlays use the canonical semantic identity/path grammar from architecture Phase 1.

Examples:

```text
customer.Customer@4
customer.Customer@4#customerId
customer.Customer@4#address.street
customer.Customer@4#orders[]
customer.Customer@4#attributes{}
```

The compiler resolves these centrally before emitter execution. Emitters never parse Modelable identity strings independently.

Unknown or ambiguous references are errors.

## 6. Version inheritance and precedence

Exact-version-only configuration would create maintenance churn on every model version. Overlays therefore support controlled selectors.

Supported selector classes, from least to most specific:

1. target defaults;
2. declaration wildcard: `customer.Customer@*`;
3. compatible version range: `customer.Customer@>=4,<7`;
4. exact declaration version: `customer.Customer@6`;
5. wildcard/range semantic path;
6. exact semantic path.

Example:

```toml
[models."customer.Customer@*"]
table = "customers"

[fields."customer.Customer@>=4,<7#customerId"]
column = "customer_id"

[fields."customer.Customer@6#customerId"]
column = "customer_id_v2"
```

Rules:

- more-specific selectors override less-specific selectors;
- equal-specificity conflicting values are errors;
- file order is not a conflict-resolution mechanism;
- targets may prohibit inheritance for properties that must be exact;
- all resolved layers contribute to artifact fingerprints.

## 7. Suitable overlay data

Examples:

- serialization names;
- C#/Java/Rust framework attributes;
- SQL table/column naming;
- SDK naming conventions;
- ORM hints;
- target package/module names;
- generated file naming;
- Unity-specific C# attributes/serialization hints;
- representation type preferences where semantic meaning is preserved.

## 8. Data that must not be overlays

Compatibility-critical persistent allocation state belongs in deterministic lock state.

### 8.1 Protobuf field numbers

Protobuf field numbers must **not** be optional overlay properties.

They are persistent wire-compatibility identity. Losing or drifting the configuration must never cause silent reassignment.

The allocator/ledger belongs in `modelable.lock/v1`, using the same principle as the existing git-tracked `registry-ids.lock` precedent.

The Protobuf target may expose naming/packaging/options in overlays, while field-number/reservation allocation state is locked independently.

### 8.2 General allocation rule

Any target identifier that cannot be safely recomputed without compatibility risk belongs in lock state rather than an optional overlay.

## 9. Resolution pipeline

```text
.mdl
  ↓ parse/validate
semantic graph
  ↓
normalized plan
  ↓
load + schema-validate overlays
  ↓
resolve canonical selectors
  ↓
target configuration
  ↓
emitter / target compatibility evaluator
```

Overlays cannot mutate the semantic graph.

## 10. Workspace target selection

`modelable.toml` selects targets and overlay files.

Example:

```toml
[[target]]
name = "sql-postgres"
overlay = "modelable.extensions/postgres.toml"
out = "generated/sql"

[[target]]
name = "csharp"
overlay = "modelable.extensions/csharp.toml"
out = "generated/csharp"
```

Resolution order for selecting an overlay file:

1. explicit CLI path;
2. explicit target entry in `modelable.toml`;
3. conventional `modelable.extensions/<target>.toml`;
4. no overlay, target defaults only.

Selection is explicit/deterministic; no hidden environment-specific file discovery.

## 11. Editor/schema support

Each built-in target publishes/ships a versioned JSON Schema for its overlay.

Schemas must be available locally so offline environments do not depend on remote schema URLs.

Expected editor support:

- TOML syntax highlighting;
- completion;
- validation;
- enum suggestions;
- hover documentation;
- deprecation markers;
- unknown selector/key diagnostics.

## 12. Semantic and artifact identity

Overlay changes do not change canonical semantic identity/signatures.

Conceptually:

```text
semantic_signature = hash(normalized semantic meaning)
```

Generated artifact fingerprints include representation state:

```text
artifact_signature = hash(
  semantic_signature,
  target id/version,
  extension id/version/hash,
  normalized overlay,
  locked target allocations
)
```

## 13. Compatibility

Semantic compatibility is computed without overlay representation choices.

Target compatibility consumes:

- semantic change facts;
- old/new resolved target configuration;
- old/new locked target allocation state;
- target-specific compatibility rules.

This keeps representation compatibility out of generic semantic diff code.

## 14. `@wire` migration

`@wire` is existing stable syntax and does not change meaning during stabilization.

Migration policy:

1. implement equivalent overlay capabilities first;
2. new target-specific features prefer overlays;
3. tooling may generate overlay entries from existing `@wire` where deterministic;
4. add deprecation diagnostics only after migration tooling exists;
5. keep at least one full stable release cycle before removal can even be proposed;
6. removal requires a major language-version decision and explicit migration support.

The compiler must never reinterpret an old `@wire` declaration to mean something new.

## 15. Security/trust

Overlay files are non-executable build inputs.

They must not support:

- arbitrary code;
- shell commands;
- dynamic imports;
- implicit plugin loading;
- unrestricted environment interpolation.

Unknown keys/selectors are diagnostics rather than ignored content.

Overlays that affect generated code should be version-controlled or otherwise pinned/fingerprinted for reproducible builds.

Secrets must not be embedded in overlay files that are copied into plan/lock/artifact manifests.

## 16. Extension relationship

Executable emitter extensions and non-executable overlays are separate concepts.

An extension owns:

- target identity/version;
- capability descriptor;
- overlay schema;
- emitter/compatibility implementation.

The compiler owns:

- extension provenance/trust policy;
- common overlay envelope;
- semantic identity/path resolution;
- deterministic precedence;
- diagnostics;
- plan/lock integration.

Third-party extensions may define their own overlay schema without changing the `.mdl` grammar.

## 17. Acceptance criteria

Phase 4 is complete when:

- one canonical selector grammar is used by every target;
- wildcard/range/exact precedence is deterministic and tested;
- equal-specificity conflicts fail clearly;
- built-in targets expose local schemas;
- overlays cannot mutate semantic meaning;
- Protobuf field numbers and similar persistent allocations are kept in lock state;
- `@wire` migration preserves old syntax meaning;
- a framework-specific integration such as Unity can be configured without grammar additions;
- browser/native hosts resolve the same overlay inputs identically where overlay support is available.