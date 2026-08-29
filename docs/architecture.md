# Modelable Architecture

> **Authority:** This document defines the intended product and architectural boundaries for Modelable. Implementation details may lag behind it, but new work should move toward these boundaries rather than expand older coupling.

## 1. Product thesis

Modelable is a semantic and consequence compiler for versioned, domain-owned data contracts.

Its core responsibility is to answer four questions:

1. What does a data contract mean?
2. Where did every field and declaration come from?
3. What changes when that contract evolves?
4. What must downstream systems do as a consequence?

Modelable is not primarily a code generator, schema registry, runtime, integration platform, database abstraction, or catalog. Those are consumers of the semantic model and consequence analysis.

The intended architecture is:

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
modelable.plan/v1
   ↓
emitters / analyzers / policies / integrations
```

The semantic graph and consequence graph are the product. Everything around them should remain replaceable.

## 2. Design principles

### 2.1 Semantic core, replaceable edges

The language describes domain semantics. It must not accumulate implementation details for individual emitters, frameworks, databases, brokers, SDKs, or deployment environments.

Target-specific behavior belongs in extensions, overlays, policies, adapters, or generated artifacts.

### 2.2 One semantic implementation

CLI, browser, LSP, CI, build plugins, agents, and future server surfaces must reuse the same semantic engine. A host may differ in transport and persistence, but must not reimplement Modelable semantics.

### 2.3 Stable meaning before feature breadth

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

The grammar should change only when the requirement cannot be represented correctly through those mechanisms.

### 2.4 Nominal identity over structural copying

Reusable semantic declarations must preserve declaring identity and version. Enums, semantic types, values, entities, events, aggregates, and projections should not be duplicated structurally when a nominal reference can represent the same contract.

### 2.5 Explicit derivation

Every derived field must retain source lineage. Selection, rename, computation, join, filtering, aggregation, conversion, and projection chaining must produce inspectable derivation edges.

### 2.6 Compatibility is layered

Semantic compatibility and target compatibility are different concerns.

Semantic analysis identifies facts such as:

- field removed
- requiredness changed
- type changed
- enum narrowed
- key changed
- projection source changed

Target evaluators interpret those facts for Protobuf, OpenAPI, Avro, SQL, generated SDKs, or other consumers.

### 2.7 Offline and deterministic by default

Compilation must not require a network service. Exact dependency state, source provenance, semantic identity, and usage should be reproducible from version-controlled inputs and deterministic snapshots.

### 2.8 Runtime is outside the core

Modelable may generate runtime contracts and validation packages, but it should not become a broker abstraction, streaming engine, database synchronization runtime, materializer, or distributed registry.

Other systems may consume Modelable artifacts to implement those concerns.

## 3. Core contracts

Modelable should stabilize three deliberately versioned contracts.

### 3.1 Semantic graph

The semantic graph is the canonical representation of meaning after syntax has been resolved.

It owns:

- declaration identity
- domain ownership
- versions
- fields and members
- type identity
- references
- projections
- derivations
- lineage
- semantic annotations
- compatibility-relevant facts

Parser-specific objects are not a public extension API.

The internal Python representation may evolve. The semantic meaning may not change silently.

### 3.2 Plan document

`modelable.plan/v1` is the stable target-neutral representation consumed by generators and analyzers.

It must be:

- deterministic
- serializable
- schema-versioned
- independent of Python object identity
- sufficient for emitters without access to parser internals
- usable by browser and native hosts

A plan should contain normalized declarations, resolved references, lineage, compatibility-relevant metadata, and target-neutral generation facts.

### 3.3 Extension protocol

Extensions must depend on stable contracts rather than compiler internals.

An extension descriptor should expose at least:

```text
id
version
accepted plan versions
capabilities
configuration schema
output kinds
compatibility support
```

The in-process Python API may be convenient, but the long-term boundary should also support subprocesses and WASM so extensions can be implemented independently of the compiler language.

## 4. Unified declaration model

Modelable should converge on one declaration family:

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

Common declaration concepts should be modeled once:

- qualified semantic identity
- exact version
- ownership
- documentation
- compatibility policy
- members or fields
- references
- lineage
- deprecation state where supported

Declaration kinds may impose different constraints, but they should not create parallel resolution, versioning, or compatibility systems.

### 4.1 Semantic identity

Every reusable declaration must have a canonical identity independent of source file location and target output naming.

Conceptually:

```text
customer.Customer@4
customer.CustomerStatus@2
customer.CustomerId@1
billing.BillingCustomer@3
```

Field identity extends that path:

```text
customer.Customer@4.email
```

These identities are used by overlays, plan documents, lockfiles, lineage, usage evidence, and consequence analysis.

### 4.2 Enums and semantic types

Enums and semantic types are first-class versioned declarations.

Consumers reference them nominally. A reference carries declaration identity and version, not a copied structural representation.

Inline syntax may remain as authoring convenience, but compiler normalization should prefer explicit declarations when identity matters.

## 5. Projection as the universal derivation mechanism

A projection is a named, versioned derivation of one or more semantic declarations.

Projection should not be limited to DTO generation.

Valid uses include:

- API request contract
- API reply contract
- persistence shape
- event payload
- analytics dataset
- materialized read model contract
- consumer-specific subset
- enum subset
- public compatibility view
- cross-domain composite view

The same lineage and compatibility machinery should apply regardless of source declaration kind.

Auto projections are authoring sugar. They must normalize into ordinary explicit projection semantics before later compiler phases.

## 6. Target-specific overlays

Emitter and platform configuration must not expand the semantic language indefinitely.

Target-specific configuration belongs in an external overlay, preferably TOML.

Example:

```toml
[typescript."customer.Customer@4.customerId"]
type = "CustomerId"

[protobuf."customer.Customer@4.customerId"]
number = 1

[sql-postgres."customer.Customer@4"]
table = "customers"
```

Overlays address canonical semantic identities, never parser positions or source line numbers.

The overlay mechanism may later carry:

- serialization names
- framework attributes
- SQL table/column mapping
- Protobuf field numbers
- SDK naming
- ORM hints
- deployment-specific bindings
- Unity or other framework-specific generation details

This replaces target-specific semantic annotations such as `@wire` over time. Existing syntax may remain temporarily for compatibility, but target configuration should move out of the semantic IR.

## 7. Registry and lockfile

The authoritative registry model is an offline deterministic snapshot, not a mandatory service.

`modelable.lock/v1` should capture the exact state required to reproduce resolution and impact analysis, including:

- exact declaration versions
- content hashes
- source provenance
- transitive dependencies
- semantic identities
- declarations actually used
- fields/projections actually used where available
- generation or plan fingerprints where useful

A SQLite registry may remain as a disposable local index or cache over this information. It is not the semantic authority.

Remote schema registries and catalogs are adapters around generated artifacts and snapshots.

## 8. Usage graph

Declared consumers are weaker evidence than actual compilation usage.

A consuming application should produce a snapshot proving what it compiled against. Aggregating these snapshots creates the usage graph.

Example:

```text
customer.Customer@4
├── web-frontend
├── billing-service
└── crm-import
```

Usage edges may point to whole declarations, projections, or individual fields.

This allows Modelable to distinguish theoretical compatibility from actual blast radius.

## 9. Change and consequence graphs

A diff is not the final product of evolution analysis.

Modelable should derive an explicit graph:

```text
Change
  ↓ impacts
Semantic declaration
  ↓ invalidates / affects
Projection
  ↓ changes
Artifact
  ↓ requires
Consumer action
```

Consequences should be structured nodes and edges rather than a growing list of string statuses.

Typical terminal actions include:

- no action
- recompile
- regenerate
- migrate data
- update consumer
- review policy violation
- breaking/manual intervention

Every reported consequence should retain its causal path so tooling can answer:

- what breaks?
- why?
- which declaration caused it?
- which projection propagated it?
- which generated artifact changes?
- which repository or consumer is affected?
- what can be automated?

## 10. Compatibility architecture

Compatibility runs in two layers.

### 10.1 Semantic compatibility

Semantic compatibility operates only on the semantic graph.

It produces change facts independent of output target.

Examples:

- declaration removed
- field added/removed
- requiredness changed
- nullability changed
- type widened/narrowed
- enum member added/removed
- identity changed
- source version changed
- projection mapping changed

### 10.2 Target compatibility

Target-specific evaluators consume semantic change facts plus target metadata.

Examples:

- Protobuf field number reuse
- OpenAPI client incompatibility
- Avro reader/writer compatibility
- destructive SQL migration
- generated language API break

Target compatibility must not be embedded into generic semantic diff code.

## 11. Capability negotiation

Target support should become declarative and extension-owned rather than a central hardcoded matrix.

A target advertises support for capabilities such as:

```text
records
enums
semantic-types
unions
maps
constraints
lineage
compatibility
```

Before emission, Modelable compares the normalized plan with target capabilities and produces deterministic diagnostics for unsupported constructs.

This prevents semantic additions from requiring scattered emitter-specific detection logic.

## 12. Policy extensions

Governance facts belong in the semantic graph. Organization- or regulation-specific policy belongs in evaluators.

Avoid growing fixed annotations for every regime or organization.

Preferred shape:

```text
semantic facts
   ↓
policy evaluator
   ↓
diagnostics / consequences
```

Policies may inspect ownership, classification, PII, lineage, target overlays, storage projections, or usage relationships without changing the core language.

## 13. Host architecture

The compiler core should be independent of filesystem, network, process, UI, and transport assumptions.

Conceptual API:

```text
input:
  workspace files
  configuration
  dependency snapshot

output:
  diagnostics
  semantic graph
  plan
  compatibility facts
  consequences
```

Hosts provide I/O:

```text
CLI
Browser
LSP
CI
Build plugin
MCP/agent integration
Future server
```

The browser implementation is an architectural conformance surface. Browser and native compilation of the same workspace must produce equivalent semantic results.

## 14. Showcase as executable specification

`modelable-showcase` should act as an external conformance suite rather than only a demonstration application.

It should exercise:

- canonical models
- enums and semantic types
- projections
- API generation
- event generation
- persistence generation
- multiple programming languages
- evolution across versions
- compatibility analysis
- conversions
- browser compilation
- native compilation
- real generated consumer builds

A significant semantic feature should not be considered complete until at least one realistic showcase scenario proves that the abstraction works across boundaries.

## 15. Stability classes

### Stable

These surfaces require explicit versioning and migration rules:

- `.mdl` semantics
- canonical semantic identity
- version rules
- semantic compatibility facts
- `modelable.plan/v1`
- `modelable.lock/v1`
- diagnostic identifiers

### Extensible

These are expected to grow independently:

- emitters
- importers
- policies
- analyzers
- target compatibility evaluators
- catalog adapters
- registry adapters
- overlays

### Internal

These may change without ecosystem compatibility guarantees:

- parser implementation classes
- internal Python graph representation
- CLI implementation
- cache database schema
- compiler pass organization

## 16. Protocol versioning

Public machine-readable contracts should use explicit protocol identifiers:

```text
modelable.semantic/v1
modelable.plan/v1
modelable.lock/v1
modelable.diagnostics/v1
modelable.extension/v1
```

Implementation classes must not accidentally become protocols.

## 17. Runtime boundary

The compiler may generate contracts for runtime systems, including:

- event envelopes
- transactional outbox schemas
- runtime validation schemas
- persistence mappings
- migration plans
- stream schemas

The following are outside the Modelable core roadmap:

- streaming execution engine
- materialization runtime
- broker abstraction
- database synchronization service
- retry/dead-letter engine
- distributed registry service

If these capabilities are needed, Modelable should generate enough semantic information for another system to implement them.

## 18. Future-use stress tests

Architecture changes should be evaluated against likely future consumers without pre-implementing them.

Expected extension use cases include:

- GraphQL
- AsyncAPI
- additional schema formats
- Iceberg/Delta/data-lake contracts
- ORM integration
- SDK generation
- domain-specific standards
- API migration tooling
- AI-assisted refactoring
- code migration generation
- architecture governance
- cross-repository impact analysis
- runtime validation packages
- MCP/agent semantic queries
- Unity-specific C# and serialization overlays

A future use should normally require an extension, overlay, policy, or analyzer rather than a new grammar construct.

## 19. Architectural decision rule

For every new requirement, apply this test:

```text
Can existing semantics represent the requirement correctly?
  │
  ├─ yes → extension / overlay / emitter / policy / analyzer
  │
  └─ no  → consider extending the semantic model
```

The anti-pattern is:

```text
new requirement
→ new grammar keyword
→ new IR class
→ update every emitter
→ target-specific compatibility branches
```

The desired pattern is:

```text
new requirement
→ reuse semantic graph
→ add isolated extension behavior
```

This rule is the primary mechanism for keeping Modelable stable while allowing the ecosystem around it to grow.