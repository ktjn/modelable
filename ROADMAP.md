# Roadmap

Modelable is entering a stabilization phase.

The product already has broad language, compatibility, lineage, code generation, import, browser, and tooling capability. The next priority is not adding more surface area. It is making the semantic core stable enough that future capability can be added without repeatedly changing grammar, IR, compatibility logic, and every emitter.

The architecture source of truth is [docs/architecture.md](docs/architecture.md).

## Goal

Stabilize Modelable around this product boundary:

```text
semantic graph
    +
usage graph
    +
change graph
    ↓
consequence graph
    ↓
versioned plan
    ↓
extensions
```

The semantic graph and consequence graph are the durable product. Emitters, policies, adapters, registries, catalogs, framework integrations, and runtime consumers remain replaceable edges.

## Operating rules

1. Correctness and false compatibility results are release blockers.
2. New broad grammar features are paused unless existing semantics cannot represent the requirement correctly.
3. New target-specific behavior should prefer overlays or extensions over core annotations.
4. New emitters must consume normalized compiler output rather than duplicate semantic resolution.
5. Browser and native compilation must remain semantically equivalent.
6. Significant semantic changes require realistic external conformance coverage in `modelable-showcase`.
7. Runtime execution features remain outside the core roadmap.

## Phase 1 — Freeze semantic identity

### Outcome

One canonical identity model for all reusable semantic declarations.

### Work

- Define canonical qualified identities for declarations and fields.
- Ensure identity is independent of source file location and emitter naming.
- Unify resolution rules for entities, aggregates, events, values, enums, semantic types, and projections.
- Continue nominal enum and semantic-type references rather than copying structural definitions.
- Remove declaration-kind-specific resolution paths where equivalent generic logic can be used.
- Define explicit invariants for version identity and cross-domain references.

### Acceptance

The compiler can identify every reusable semantic declaration using a stable canonical identity such as:

```text
customer.Customer@4
customer.Customer@4.email
customer.CustomerStatus@2
```

The identity can be serialized and reused by plans, overlays, lockfiles, lineage, usage evidence, and diagnostics.

## Phase 2 — Define `modelable.plan/v1`

### Outcome

Emitters and analyzers depend on a stable normalized contract instead of parser/internal Python classes.

### Work

- Define a versioned JSON-compatible plan schema.
- Include resolved declarations, versions, field types, nominal references, projections, lineage, and target-neutral generation facts.
- Make plan generation deterministic.
- Add golden conformance fixtures.
- Ensure browser and native hosts produce equivalent plans.
- Migrate emitters incrementally to consume the plan boundary.
- Treat Python implementation classes as internal.

### Acceptance

A standalone tool can consume `modelable.plan/v1` without importing parser or semantic-validation internals.

## Phase 3 — Unify declarations and projections

### Outcome

Avoid parallel implementations for each semantic declaration kind.

### Work

- Establish a common declaration abstraction for:
  - entity
  - aggregate
  - event
  - value
  - enum
  - semantic type
  - projection
- Centralize ownership, versioning, documentation, reference, compatibility, and deprecation behavior where semantics are shared.
- Treat projections as the universal named/versioned derivation mechanism.
- Support projections of enum and other declaration types without introducing separate subset mechanisms.
- Normalize auto projections into ordinary projection semantics early in the pipeline.

### Acceptance

Adding a new declaration capability does not require recreating version resolution, identity, lineage, and compatibility infrastructure.

## Phase 4 — Separate target configuration from semantics

### Outcome

Target-specific representation choices stop expanding `.mdl` and semantic IR.

### Work

- Design a TOML overlay format keyed by canonical semantic identity.
- Move new target naming, serialization, framework, SQL, Protobuf, SDK, and deployment hints into overlays.
- Define deterministic overlay precedence and validation.
- Expose overlay configuration schemas through target descriptors.
- Plan deprecation/migration of `@wire` and other target-specific semantic annotations.
- Keep semantic metadata such as ownership, classification, and PII in the semantic graph.

Example:

```toml
[protobuf."customer.Customer@4.customerId"]
number = 1

[sql-postgres."customer.Customer@4"]
table = "customers"
```

### Acceptance

A new framework-specific integration, including Unity-specific C# generation, can be configured without adding a Unity/framework keyword to `.mdl`.

## Phase 5 — Introduce extension descriptors and capability negotiation

### Outcome

Targets become discoverable components rather than entries in increasingly centralized conditionals.

### Work

- Define `modelable.extension/v1`.
- Define extension descriptors containing:
  - id
  - version
  - supported plan versions
  - capabilities
  - configuration schema
  - output kinds
  - compatibility support
- Define standard semantic capabilities such as records, enums, semantic types, maps, unions, constraints, lineage, and compatibility.
- Validate a plan against target capabilities before emission.
- Move target capability ownership into target implementations.
- Keep an in-process Python extension path while defining a language-neutral subprocess/WASM boundary.

### Acceptance

Unsupported semantic constructs fail through one compiler-owned capability check rather than emitter-specific ad-hoc logic.

## Phase 6 — Formalize `modelable.lock/v1`

### Outcome

The registry becomes reproducible dependency/usage state rather than infrastructure.

### Work

- Define deterministic lock/snapshot format.
- Record:
  - exact declaration versions
  - content hashes
  - source provenance
  - transitive dependencies
  - canonical semantic identities
  - declarations actually used
  - fields/projections actually used where observable
  - optional plan/generation fingerprints
- Make local SQLite registry/index state reconstructable from version-controlled inputs and lock data.
- Keep remote schema registries and catalogs as adapters.
- Avoid requiring a Modelable service for normal compilation.

### Acceptance

A clean offline checkout can reproduce resolution and prove exactly which semantic contracts a consumer compiled against.

## Phase 7 — Build the usage graph

### Outcome

Impact analysis is based on actual consumers rather than only theoretical references or manually maintained consumer declarations.

### Work

- Produce usage evidence from compilation.
- Aggregate usage snapshots across applications/repositories.
- Track whole-declaration, projection, and field-level usage where possible.
- Make declared `consumer {}` metadata optional/non-authoritative unless a future concrete use requires it.
- Expose usage queries to CLI, CI, IDE, and agent surfaces.

### Acceptance

Given a declaration version, Modelable can identify the known applications and projections that actually depend on it.

## Phase 8 — Replace flat consequences with a consequence graph

### Outcome

Model evolution produces explainable causal paths and actionable downstream work.

### Work

- Replace growing string-based consequence statuses with structured nodes and edges.
- Represent chains such as:

```text
field removal
  ↓
projection affected
  ↓
generated schema changes
  ↓
consumer update required
```

- Preserve causal paths for every terminal action.
- Support queries for:
  - what breaks
  - why
  - which projection propagated it
  - which artifacts change
  - which consumers are affected
  - what can be regenerated automatically
  - what requires migration/manual intervention
- Keep simple CLI summaries as views over the graph.

### Acceptance

Every reported impact can be traced from root semantic change to affected consumer action.

## Phase 9 — Separate semantic and target compatibility

### Outcome

Core compatibility produces target-neutral facts; extensions interpret them for wire/storage/API constraints.

### Work

- Define a canonical semantic change vocabulary.
- Ensure generic diff logic knows nothing about Protobuf numbers, SQL migration strategy, Avro reader/writer rules, or generated-language syntax.
- Move those rules to target compatibility evaluators.
- Feed target results into the consequence graph.
- Keep compatibility deterministic and independently testable.

### Acceptance

Adding a new target compatibility evaluator does not require modifying semantic diff algorithms.

## Phase 10 — Policy extension boundary

### Outcome

Governance grows without adding permanent language annotations for every regulation or organization.

### Work

- Define a policy evaluator interface over semantic/usage/consequence data.
- Keep facts such as PII, classification, ownership, and lineage in core semantics.
- Implement organization/regulation-specific checks outside the fixed annotation set.
- Allow policies to produce diagnostics and consequences.
- Define configuration and severity handling outside source semantics where appropriate.

### Acceptance

A custom enterprise policy can be added without a grammar or semantic-IR change.

## Phase 11 — Make `modelable-showcase` an executable conformance suite

### Outcome

Real consumer builds detect cross-target semantic regressions before release.

### Work

Exercise at least:

- canonical models
- semantic types
- enums
- enum projections/subsets
- nested/value types
- API request/reply projections
- events
- persistence projections
- multiple programming-language emitters
- Protobuf/OpenAPI/Avro/SQL
- version evolution
- compatibility analysis
- generated conversions
- browser compilation
- native compilation
- real generated consumer compilation

Add matrix coverage for major `FieldType × declaration kind × target` combinations.

### Acceptance

A semantic feature is not considered complete until a realistic cross-boundary scenario validates it.

## Phase 12 — Stabilize host boundaries

### Outcome

CLI, browser, LSP, CI, build plugins, MCP, and future server surfaces become thin hosts around one compiler.

### Work

- Remove filesystem/network/process assumptions from compiler-core APIs where practical.
- Define host input as workspace files + config + dependency snapshot.
- Define host output as diagnostics + semantic graph + plan + compatibility/consequence results.
- Keep browser compiler as a required conformance surface.
- Expose semantic queries through a transport-neutral API suitable for agents and tooling.

### Acceptance

A new host can be implemented without duplicating parsing, semantic resolution, compatibility, or lineage behavior.

## Deferred product areas

The following remain outside the core roadmap unless the product thesis changes:

- streaming execution engine
- subscription runtime
- materialization runtime
- broker abstraction
- database synchronization service
- retry/dead-letter execution
- distributed Modelable registry service

Modelable may generate contracts, plans, mappings, migrations, or validation packages for these systems.

## Future-use design tests

Future uses should be accommodated primarily through extensions rather than preemptive grammar additions.

Expected stress cases include:

| Use | Expected mechanism |
|---|---|
| GraphQL | emitter + compatibility evaluator |
| AsyncAPI | emitter |
| additional wire/schema formats | emitter |
| Iceberg/Delta | emitter |
| ORM/framework bindings | overlay + emitter |
| Unity | C# emitter extension + overlay |
| SDK generation | emitter |
| industry standards | extension package |
| enterprise governance | policy evaluator |
| catalog integration | adapter |
| schema registry integration | adapter |
| API migration tooling | consequence graph + action generator |
| AI-assisted refactoring | semantic/usage/consequence query API |
| code migrations | action generator |
| cross-repo blast radius | lock snapshots + usage graph |
| runtime validation | generated package |
| MCP/agent integration | host/query protocol |

## Explicit non-goals for stabilization

Do not spend stabilization capacity on:

- adding emitters solely for breadth
- adding grammar syntax for target configuration
- making SQLite registry state authoritative
- building a remote registry service
- implementing runtime materialization/subscriptions
- creating duplicate semantic implementations for browser or integrations

## Contribution decision rule

Before extending the language, answer:

```text
Can existing semantic constructs represent this correctly?
  │
  ├─ yes → extension / overlay / emitter / analyzer / policy
  │
  └─ no  → propose a semantic-model change
```

A proposal for a semantic-model change must document why projections, semantic types, overlays, and extension capabilities are insufficient.

## Completion criteria for stabilization

The stabilization program is complete when:

- canonical semantic identity is defined and used consistently
- emitters can consume `modelable.plan/v1`
- external target configuration has a stable overlay mechanism
- extension capability negotiation is implemented
- dependency/usage state has a deterministic lock format
- consequences form an explainable graph
- semantic and target compatibility are separated
- browser/native semantic conformance is enforced
- showcase provides realistic cross-target conformance
- significant new integrations can be added without changing `.mdl`

At that point Modelable can resume broad feature growth with substantially lower architectural cost.