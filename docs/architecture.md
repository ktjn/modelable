# Modelable Architecture and System Specification

> **Authority:** This document is the product source of truth for Modelable concepts, invariants, trust boundaries, and current/deferred implementation boundaries. It also defines the intended stabilization architecture. Where an architectural target is not yet implemented, that status is stated explicitly.

## 1. Product thesis

Modelable is a **semantic and consequence compiler for versioned, domain-owned data contracts**.

Its core responsibility is to answer four questions:

1. What does a data contract mean?
2. Where did every field and declaration come from?
3. What changes when that contract evolves?
4. What must downstream systems do as a consequence?

Modelable is not primarily a code generator, schema registry, runtime, integration platform, database abstraction, or catalog. Those are consumers of the semantic model and consequence analysis.

The target architecture is:

```text
.mdl sources
   ↓
syntax AST
   ↓
semantic graph
   ↓
resolved workspace graph
   ↓
usage graph
   ↓
change graph
   ↓
consequence graph
   ↓
normalized plan
   ↓
emitters / analyzers / policies / integrations
```

The semantic graph and consequence graph are the durable product boundary. Everything around them should remain replaceable.

## 2. Design principles

### 2.1 Domain ownership

Every canonical declaration belongs to one domain. The owning domain controls its meaning, versions, compatibility policy, and deprecation policy.

Cross-domain use must preserve the identity of the owning declaration rather than copying its structure into a second source of truth.

### 2.2 Property-level traceability

Every derived field must be traceable to its source declarations and source fields.

Selection, rename, computation, join, filtering, aggregation, conversion, projection chaining, and generated auto projections must produce inspectable derivation edges.

### 2.3 Immutable contracts

Published declaration versions are immutable semantic contracts. Incompatible change creates a new version rather than silently changing the meaning of an existing version.

The current stable grammar **does not represent a model lifecycle status** such as `draft`, `published`, `deprecated`, or `retired`. Lifecycle status remains deferred; field-level deprecation is supported separately.

### 2.4 Platform-neutral definitions

The `.mdl` language describes semantics, not the representation choices of a particular database, broker, framework, serializer, SDK, or programming language.

Target-specific behavior belongs in emitters, target compatibility evaluators, overlays, policies, adapters, or generated artifacts.

### 2.5 Explicit derivation

All derived data must be declared or compiler-generated from deterministic authoring sugar that normalizes to explicit derivation semantics.

### 2.6 One semantic implementation

CLI, browser, LSP, CI, build plugins, agents, and future server surfaces must reuse the same semantic engine. A host may differ in transport and persistence but must not reimplement Modelable semantics.

### 2.7 Stable meaning before feature breadth

New grammar constructs are expensive because they affect parsing, validation, compatibility, lineage, language tooling, documentation, browser support, and many emitters.

A new requirement should first be expressed using existing semantics plus one of:

- projection
- semantic/value type
- policy
- target overlay
- emitter
- analyzer
- importer
- adapter

The grammar changes only when the requirement cannot be represented correctly through those mechanisms.

### 2.8 Nominal identity over structural copying

Reusable semantic declarations preserve declaring identity and version. Enums, semantic types, values, entities, events, aggregates, and projections should not be duplicated structurally when a nominal reference can represent the same contract.

### 2.9 Compatibility is layered

Semantic compatibility and target compatibility are separate concerns.

Semantic analysis identifies target-neutral facts such as field removal, requiredness change, enum narrowing, type change, identity change, or projection-source change. Target evaluators interpret those facts for Protobuf, OpenAPI, Avro, SQL, generated SDKs, or other consumers.

### 2.10 Offline and deterministic by default

Normal compilation must not require a network service. Exact dependency state, source provenance, semantic identity, extension provenance, and usage evidence must be reproducible from version-controlled inputs and deterministic snapshots.

### 2.11 Runtime is outside the core

Modelable may generate runtime contracts and validation packages, but it should not become a broker abstraction, streaming engine, database synchronization runtime, materializer, retry engine, or distributed registry.

## 3. Core semantic concepts

### 3.1 Domain

A domain is an ownership boundary for declarations.

A domain owns canonical names and versions. Domain identity is part of the canonical semantic identity of every declaration it contains.

### 3.2 Declaration

Modelable converges on one declaration family:

```text
Declaration
├── Entity
├── Aggregate
├── Event
├── Value
├── Enum
├── SemanticType
└── Projection
```

Shared declaration behavior should be modeled once:

- canonical identity
- exact version
- ownership
- documentation
- compatibility policy
- members or fields
- references
- lineage
- semantic annotations

Declaration kinds may impose different constraints but should not create parallel resolution, identity, versioning, or compatibility systems. The resolver's `ResolvedDeclarationView` is the shared identity surface for model versions, projections, semantic types, and enum projections; a private candidate boundary supplies those concrete declarations to generic lookup logic. Compatibility-specific properties remain on the legacy result wrappers while consumers migrate to the common `name`, `declaration`, `kind`, and `version_number` fields.

### 3.3 Model version

A declaration version is an immutable semantic contract identified by domain, declaration name, kind, and version.

Entities and aggregates currently require exactly one `@key` field. Composite keys are **not implemented** and declaring multiple key fields is rejected by semantic validation.

Model lifecycle status is also not represented in the current grammar or IR. The compiler therefore must not imply a draft/published/deprecated/retired lifecycle that it cannot encode.

### 3.4 Projection

A projection is a named, versioned derivation of one or more semantic declarations.

Projection is the universal derivation mechanism, not merely a DTO feature. Valid uses include:

- API request contracts
- API reply contracts
- persistence shapes
- event payloads
- analytics datasets
- read-model contracts
- consumer-specific subsets
- enum subsets
- public compatibility views
- cross-domain composite views

Projection-of-projection remains a derivation chain and must preserve lineage to original sources.

### 3.5 Auto projections

Auto projections are authoring sugar. They must normalize into ordinary explicit projection semantics before later compiler phases.

Generated request, reply, database, and event projections therefore use the same identity, lineage, compatibility, planning, and emitter paths as hand-authored projections. Workspace expansion materializes them into the ordinary projection collections and sorts each named version sequence before downstream consumers run.

## 4. Canonical semantic identity

Canonical identity is load-bearing infrastructure for overlays, lock state, plans, lineage, usage, diagnostics, and consequences. It must be specified before those protocols stabilize.

### 4.1 Declaration identity

Canonical declaration identity is:

```text
<domain>.<declaration>@<version>
```

Examples:

```text
customer.Customer@4
customer.CustomerStatus@2
customer.CustomerId@1
billing.BillingCustomer@3
```

Identity is independent of file location and emitter output naming.

### 4.2 Semantic path grammar

Field/member addressing uses a typed semantic path rooted in an exact declaration identity.

Canonical textual form:

```text
<declaration-id>#<path-segment>(.<path-segment>)*
```

Examples:

```text
customer.Customer@4#email
customer.Customer@4#address.street
customer.Customer@4#orders[]
customer.Customer@4#attributes{}
customer.Customer@4#attributes{}.value
```

The path grammar is semantic, not source-syntax based:

- `name` addresses a named field/member.
- `[]` addresses the element type of an array.
- `{}` addresses the value type of a map; map keys are addressed as `{key}` only if a future semantic consumer needs them.
- nested value/object fields continue with `.`.
- a projection has its own declaration identity; projection-of-projection lineage points to both the immediate source path and the ultimate canonical source path.

Identifiers use the canonical normalized spelling accepted by the language. Characters that cannot appear in language identifiers never require escaping in canonical paths. If the language later permits escaped identifiers, the identity grammar must define one reversible percent-encoding before such syntax ships.

Canonical path parsing must reject ambiguity; tools must never treat an unparseable overlay key as an opaque string and silently continue.

### 4.3 Identity invariants

The compiler must guarantee:

- one canonical serialization for one semantic identity;
- case handling identical to language identifier semantics;
- no alias based on file path, import spelling, or emitter name;
- exact version in persisted plan/lock/usage identities;
- deterministic round-trip parse/render tests;
- collision tests for nested paths, arrays, maps, enum members, and projections.

These invariants are a prerequisite for stable plan and lock protocols.

## 5. Projection semantics

### 5.1 Field selection

A projection may select a subset of source fields. The compiler records direct source lineage.

### 5.2 Field rename

A target field with a different name remains linked to its source semantic path. Rename is representation in the derived declaration, not a new source identity.

### 5.3 Computed fields

Computed fields use deterministic side-effect-free expressions. Every referenced semantic path is recorded as a dependency edge.

### 5.4 Filters

Filters affect derivation and therefore belong in the dependency graph even when they do not create output fields.

### 5.5 Joins

Join predicates produce dependency edges for all participating source paths. Join semantics must not be reimplemented separately by lineage and compatibility code.

### 5.6 Aggregations

Grouping and aggregation expressions participate in the same dependency graph and semantic validation pipeline as direct mappings and computed fields.

## 6. Event and delivery contracts

These sections describe **generated contract semantics**, not a Modelable execution runtime.

### 6.1 Change event envelope

Modelable may generate event envelopes and event projections from semantic declarations. Event identity, payload lineage, operation metadata, and compatibility are compiler concerns.

### 6.2 Delivery modes

Delivery guarantees such as at-least-once or exactly-once are runtime concerns. Modelable may preserve or generate configuration metadata where an external runtime contract requires it, but Modelable does not execute delivery.

### 6.3 Ordering

Ordering keys and sequence metadata may be represented in generated runtime contracts. Enforcement belongs to the runtime system.

### 6.4 Replay and backfill

Replay/backfill requirements may appear as consequences of a contract change, but Modelable does not execute replay or backfill jobs.

## 7. Components and current implementation boundary

### 7.1 Model registry

The authoritative registry direction is an offline deterministic lock/snapshot, not a mandatory mutation service.

The existing SQLite registry remains a derived local index/cache. It is not the semantic authority.

Remote schema registries and catalogs are adapters around generated artifacts and deterministic snapshots.

### 7.2 Compiler and planner

The compiler owns parsing, semantic validation, normalization, resolution, dependency/lineage analysis, compatibility facts, usage evidence, consequence analysis, and plan production.

Parser-specific Python classes are internal implementation details, not an extension API.

### 7.3 Runtime engine

**Deferred and outside core.** Modelable has no general streaming/runtime engine and should not grow one as part of stabilization.

### 7.4 Materializer

**Deferred and outside core.** Modelable may generate persistence mappings or migration plans but does not own continuous materialization execution.

### 7.5 Adapter layer

Compile-time import/export, registry, catalog, and target adapters are valid extension points. Runtime adapters that perform transport or synchronization are outside the compiler core.

Current shipped syntax includes runtime-adjacent constructs with limited behavior:

- `subscription` parses but is reported as deferred and is discarded before semantic IR/runtime execution.
- projection `materialisation` parses but is reported as deferred and is discarded before runtime execution.
- workspace `registry {}` and `peers` parse but are reported as deferred where they have no compiler effect.
- `consumer {}` parses but is deferred; future impact analysis should prefer derived usage evidence.
- `binding {}` currently honors only the implemented compile-time subset such as adapter/model/table; unrecognized opaque content is reported as deferred.

**Disposition during stabilization:** retain these forms for language compatibility, keep explicit `DEFERRED` diagnostics, do not silently ignore them, and do not implement a runtime behind them. Removal or replacement requires a separately versioned language change and migration path.

## 8. Evolution and compatibility

### 8.1 Model versioning

Exact declaration versions are immutable. Evolution creates a new version and compatibility compares semantic facts between versions.

### 8.2 Projection versioning

Projections are independently versioned contracts. A projection change may be affected by both its own shape/derivation changes and source-version changes.

### 8.3 Deprecation

Field/declaration deprecation metadata that is represented by the language is semantic. A broader lifecycle state machine is not currently represented and remains deferred.

## 9. Governance and access control

Core semantics may carry facts such as PII, classification, ownership, and lineage.

Organization- or regulation-specific policy belongs in policy evaluators rather than permanent grammar growth.

Preferred shape:

```text
semantic facts
   ↓
policy evaluator
   ↓
diagnostics / consequences
```

Modelable does not become an authorization runtime. It may generate or validate access-control-related contract metadata for external systems.

## 10. Lineage

Lineage is represented as semantic identity/path edges, not copied display names.

Every derivation should retain enough information to answer:

- immediate source declaration/path;
- ultimate source declaration/path;
- transformation/expression involved;
- projection chain;
- governance facts inherited or changed.

One compiler-owned dependency graph should feed lineage, compatibility, governance, plan generation, editor tooling, and consequences.

Projection-derived field lineage resolves recursively through projection sources
to the ultimate model declaration and canonical semantic path. The immediate
projection remains available from the projection declaration and plan relation
metadata; lineage consumers should not need to infer the ultimate source from
display names.

## 11. Generated artifacts

Generated artifacts are replaceable views of semantic meaning. Current and future outputs may include schemas, SDK/code types, database DDL, catalog/lineage formats, event contracts, migrations, documentation, and runtime-validation packages.

An emitter must not become an alternate semantic authority.

## 12. Normalized plan protocol

A stable plan protocol is required so emitters and analyzers do not import parser/internal Python objects.

### 12.1 `modelable.plan/v0`

During declaration unification and capability-boundary work, the normalized plan is explicitly **unstable** as `modelable.plan/v0`.

It should already be deterministic, JSON-compatible, schema-tagged, and suitable for migration experiments, but compatibility is not promised across stabilization changes.

### 12.2 `modelable.plan/v1`

`modelable.plan/v1` is the stable protocol for the current release. Its
stabilization exit criteria were:

1. canonical identity/path grammar is complete;
2. declaration/projection normalization is unified;
3. extension capabilities are defined sufficiently to know what target-neutral facts emitters require.

The v1 plan contains normalized declarations, resolved nominal references, projections, derivation/lineage, compatibility-relevant semantic facts, and target-neutral generation facts.

The current protocol implementation accepts the stable v1 envelope and retains
the compatible v0 envelope for migration and older integrations. The standalone
protocol boundary can deterministically migrate a v0 document to v1 and records
`modelable.plan/v0` in `planner_metadata.migrated_from`. Unknown plan schema
versions are rejected rather than guessed.

The normative v1 JSON Schema is checked in at
`cli/src/modelable/schemas/plan-v1.schema.json` and is included in published
Python distributions for non-Python consumers. The imperative validator remains
the source of cross-field and semantic invariants. The current v1 envelope is
strict about unknown keys, so an additive field requires a coordinated schema
and validator update plus compatibility review. Changing the meaning or type
of an existing field requires a new plan protocol version; v0 remains the only
legacy migration source.

## 13. Extension protocol

Extensions depend on versioned protocols rather than compiler implementation classes.

An extension descriptor contains at least:

```text
id
version
accepted plan versions
capabilities
configuration schema
output kinds
compatibility support
```

The long-term boundary may support in-process extensions, subprocesses, and WASM.

### 13.1 Capability negotiation

A target advertises support for capabilities such as records, enums, semantic
types, enum-projection field types, unions, maps, constraints, lineage, or
compatibility. The current target descriptors own these capability declarations;
third-party discovery and subprocess/WASM execution remain outside the shipped
boundary.

The compiler validates normalized semantic input against advertised capabilities before emission.

### 13.2 Extension provenance

Executable extensions introduce a trust boundary. Every non-built-in extension used for reproducible compilation must be pinned by:

- extension id;
- exact version;
- implementation/distribution hash;
- source/provenance where available;
- accepted protocol versions.

These pins belong in deterministic lock state.

### 13.3 Execution isolation

Built-in extensions run with the trust level of Modelable itself. Third-party subprocess/WASM extensions must be treated as untrusted by default.

The host should minimize filesystem/network/process capabilities, pass only declared inputs, and collect only declared outputs. WASM is preferred where it provides a practical capability sandbox; subprocess execution requires an explicit trust/allow policy.

A plugin protocol must not imply that arbitrary downloaded code is safe to execute during compilation.

## 14. Target-specific overlays

Emitter/platform configuration must not expand the semantic language indefinitely.

Target-specific configuration belongs in per-target external TOML overlays keyed by canonical semantic identity/path.

Example:

```toml
target = "typescript"
version = 1

[fields."customer.Customer@4#customerId"]
type_name = "CustomerId"

[models."customer.Customer@4"]
table = "customers"
```

The common `target`/`version` envelope and `[models]`/`[fields]` tables are
the canonical topology for one overlay file. `modelable.toml` selects the
file for a target; the target name is not repeated as a TOML table namespace.

### 14.1 What belongs in overlays

Suitable overlay data includes:

- serialization names;
- framework attributes;
- SQL table/column naming;
- SDK naming;
- ORM hints;
- Unity/framework-specific generation hints;
- environment/deployment representation details that do not define semantic or wire identity.

### 14.2 What does not belong in overlays

Compatibility-critical allocation state must not be optional target configuration.

**Protobuf field numbers are not overlay configuration.** They are persistent wire-compatibility state and must be allocated/pinned in deterministic lock state, following the same principle as the existing git-tracked `registry-ids.lock` ledger.

The same rule applies to future target identifiers where accidental reallocation would silently break compatibility.

### 14.3 Version-scoped overlay matching

Exact-version keys are supported, but overlays also need controlled inheritance so version bumps do not require blind copying.

Selectors are evaluated from least to most specific:

1. target defaults;
2. declaration wildcard, e.g. `customer.Customer@*`;
3. compatible version range, e.g. `customer.Customer@>=4,<7`;
4. exact declaration version, e.g. `customer.Customer@6`;
5. wildcard/range semantic path;
6. exact semantic path.

Later/more-specific matches override earlier values. Equal-specificity conflicting values are errors, not last-writer-wins behavior.

A target may restrict which selector forms are valid for a property. For example, a representation name may inherit while a compatibility-critical value must be exact/pinned in lock state.

### 14.4 Overlay trust

Overlays are trusted build inputs in the same sense as source and build configuration: they may change generated code and therefore must be version controlled or otherwise pinned for reproducible builds.

Overlays must never execute code. Unknown keys or selectors are diagnostics according to the target schema; they are not silently ignored.

### 14.5 `@wire` migration

`@wire` is existing stable syntax. It is therefore not reinterpreted or silently removed.

During stabilization:

1. existing `@wire` keeps its current meaning;
2. new target-specific capabilities prefer overlays;
3. tooling may offer migration to equivalent overlay entries;
4. deprecation requires at least one full stable release cycle with diagnostics before removal is even considered;
5. removal requires a major language-version decision and explicit migration support.

## 15. Registry, usage, change, and consequence graphs

### 15.1 Usage graph

Actual compilation usage is stronger evidence than handwritten consumer declarations.

A consuming workspace/package should produce usage evidence identifying the exact declarations, projections, and fields it compiled against.

### 15.2 Lock protocol

`modelable.lock/v1` freezes only after usage-evidence semantics are defined.

It captures enough state to reproduce resolution and prove compilation inputs, including:

- exact declaration versions;
- content hashes;
- source provenance;
- transitive dependencies;
- canonical semantic identities;
- actual declaration/field/projection usage where observable;
- extension id/version/hash/provenance;
- compatibility-critical target allocations such as Protobuf field numbers;
- optional plan/generation fingerprints.

The SQLite registry/index remains reconstructable and disposable.

### 15.3 Change graph

Semantic diff produces structured target-neutral change facts rather than target-specific breakage conclusions.

### 15.4 Consequence graph

Modelable derives explainable causal paths:

```text
semantic change
  ↓ impacts
projection
  ↓ changes
artifact
  ↓ affects
known consumer
  ↓ requires
consumer action
```

Terminal actions may include no action, recompile, regenerate, migrate data, update consumer, replay/backfill, governance review, or manual breaking intervention.

Every reported consequence retains its causal path.

Registry updates pass the complete staged `SnapshotDiff` through a
`RegistryPolicyEvaluator`. Evaluators return structured policy findings with
status, reason, and causal path, together with the actions that block
installation. The built-in blocked-action policy preserves the current
configuration behavior, while host integrations can add policy evaluators over
semantic, usage, and consequence facts without changing the language grammar
or semantic IR.

## 16. Security requirements

Stabilization adds explicit extension and overlay trust boundaries. Security requirements therefore remain first-class architecture, not deferred implementation detail.

1. **Offline by default.** Normal compile/validate/diff/impact does not implicitly contact registries, package services, or extension sources.
2. **Pinned dependencies.** External semantic dependencies and executable extensions are resolved intentionally and pinned by immutable identity/hash.
3. **No silent executable discovery.** Merely finding an extension on PATH or in a workspace must not execute it.
4. **Explicit extension allow policy.** Third-party subprocess extensions require explicit trust/enablement; sandboxed WASM may use a narrower policy but remains pinned.
5. **Least capability.** Extension hosts expose only required files/configuration and no network by default.
6. **Deterministic overlays.** Overlay files are non-executable, schema-validated build inputs. Unknown/ambiguous selectors fail clearly.
7. **Secrets stay outside semantic artifacts.** Plans, lockfiles, generated manifests, diagnostics, and usage snapshots must not embed credentials.
8. **Provenance survives generation.** Generated outputs can be traced to semantic inputs, exact dependency state, extensions, and relevant overlay fingerprints.
9. **Supply-chain verification.** Hash mismatch for locked semantic content or extension distributions is a hard error.
10. **Safe agent/tooling boundary.** MCP/AI/IDE integrations consume compiler APIs and do not gain implicit permission to execute extensions, refresh dependencies, publish artifacts, or mutate workspaces.

## 17. Current scope and implementation status

### 17.1 MVP scope phase 1

The historical Phase 1/MVP has long shipped. The current stable product surface is a local compiler and language-server toolchain with semantic validation, compatibility/lineage/governance analysis, deterministic multi-target generation/import support, local registry/index behavior, editor tooling, and a browser compiler/playground that reuses the same compiler semantics.

The roadmap now focuses on stabilization rather than redefining the old MVP.

### 17.2 CLI commands

The authoritative command inventory is [CLI Reference](cli-reference.md) and `modelable --help`. Architecture treats the CLI as a host over compiler/application services, not as part of the semantic protocol.

Current important compiler workflows include validation, compilation/generation, diff/compatibility, lineage/inspection, registry snapshot operations, documentation indexing, and conversational workspace/compilation management where implemented.

## 18. Non-goals

The following remain outside the core stabilization roadmap:

- streaming execution engine;
- subscription runtime;
- materialization runtime;
- broker abstraction;
- database synchronization service;
- retry/dead-letter execution;
- distributed Modelable registry service;
- emitter breadth solely for feature-count growth;
- target/framework concepts added directly to `.mdl` when overlays/extensions suffice;
- duplicate semantic implementations for browser, agents, or integrations.

Modelable may generate contracts, plans, mappings, migrations, validation packages, or consequence actions for external systems that perform these jobs.

## 19. Language stability and compatibility rule

The existing language-stability invariant remains mandatory:

> Old stable syntax never changes meaning silently; new semantics require new syntax, an explicitly versioned protocol change, or a compatibility-preserving migration path.

This applies to `@wire`, deferred runtime-adjacent grammar, declaration/version semantics, and all other stable constructs.

Parsed content must never be silently ignored. A construct that parses but has no implemented semantics must produce an explicit diagnostic or be rejected.

## 20. Future-use stress tests

Architecture changes should be evaluated against likely future consumers without pre-implementing them.

Expected extension use cases include:

- GraphQL;
- AsyncAPI;
- additional schema formats;
- Iceberg/Delta/data-lake contracts;
- ORM integration;
- SDK generation;
- domain-specific standards;
- API migration tooling;
- AI-assisted refactoring;
- code migration generation;
- architecture governance;
- cross-repository impact analysis;
- runtime validation packages;
- MCP/agent semantic queries;
- Unity-specific C# and serialization overlays.

A future use should normally require an extension, overlay, policy, analyzer, or action generator rather than a grammar change.

## 21. Protocol ownership

Public machine-readable protocols currently planned are:

```text
modelable.plan/v0       stabilization-only unstable plan
modelable.plan/v1       stable normalized plan after identity/declaration/capability convergence
modelable.lock/v1       reproducible dependency/usage/extension/allocation state
modelable.diagnostics/v1
modelable.extension/v1
```

There is intentionally **no `modelable.semantic/v1` public protocol** at this stage. The semantic graph remains the compiler's conceptual core and internal representation until a concrete external consumer requires a separately frozen semantic protocol.

## 22. Architectural decision rule

For every new requirement:

```text
Can existing semantics represent the requirement correctly?
  │
  ├─ yes → extension / overlay / emitter / policy / analyzer / action generator
  │
  └─ no  → consider extending the semantic model
```

Avoid:

```text
new requirement
→ new grammar keyword
→ new IR class
→ update every emitter
→ target-specific compatibility branches
```

Prefer:

```text
new requirement
→ reuse semantic graph
→ add isolated extension behavior
```

This rule is the primary mechanism for keeping Modelable stable while allowing the ecosystem around it to grow.
