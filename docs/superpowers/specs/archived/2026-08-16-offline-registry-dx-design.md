# Offline Registry and Consequence-Driven Developer Experience — Design

Date: 2026-08-16
Status: Proposed
Scope: Offline registry snapshots, cross-application contract tracking, impact/consequence analysis, generated transformations, defaults and overrides, auto-projection inheritance, migration semantics, API convenience expansion, semantic fidelity priorities, extension boundaries, and adoption DX

## 1. Purpose

Modelable's primary value is not artifact generation by itself. The core product goal is to let applications define and consume versioned data contracts across application boundaries, evolve those contracts deliberately, and understand the consequences of change before adoption.

Generated boilerplate is a secondary but important outcome. Modelable should remove repetitive data plumbing where the compiler can prove the transformation is correct, while keeping exceptional behavior explicit and overridable.

The product should converge on this pipeline:

```text
external model sources
        |
        | explicit resolve/update
        v
+---------------------------+
| durable registry snapshot |
| exact, hashed, offline    |
+-------------+-------------+
              |
              v
      local semantic graph
              |
      +-------+--------+
      |                |
      v                v
   usage graph     generated views
      |                |
      +-------+--------+
              v
      consequence graph
              |
   +----------+----------+----------------+
   |          |          |                |
   v          v          v                v
 impact    codegen   migrations       review facts
```

The practical promise is:

> Change a model, and Modelable tells you everything that changes, everywhere, and generates as much of the required work as can be proven safe.

Normal compilation must not require a network connection. The exact external contracts used by an application must be available locally and reproducibly.

## 2. Design principles

1. **The registry snapshot is dependency state, not a hosted registry service.** Remote registries, Git repositories, HTTP artifacts, and other Modelable workspaces are discovery sources. The durable local snapshot is the compile-time source for external contracts.
2. **Resolution is explicit; compilation is offline.** Commands that update dependency state may contact external sources. `validate`, `compile`, `diff`, `impact`, editor services, and ordinary CI use the resolved snapshot without network access.
3. **Ranges express intent; snapshots contain exact identities.** A reference may allow `>=2 <3`, but the resolved snapshot stores the exact version and canonical signature selected.
4. **No mutable same-version contracts.** Every snapshotted external definition is content-addressed. If a source presents the same logical version with different canonical content, update fails rather than silently replacing it.
5. **The compiler owns facts; policy owns enforcement.** Compatibility, migration need, governance review, regeneration need, and consumer impact are compiler facts. Policy decides which facts block CI but does not redefine them.
6. **Convenience syntax expands into canonical IR.** Auto projections, API resource conventions, and inherited defaults lower into the same explicit representation used by hand-authored definitions.
7. **Generated transformations are proof-driven.** Modelable generates conversions only where the semantic graph establishes a safe mapping. It never invents a plausible inverse for an irreversible projection.
8. **Defaults cover the common case; overrides remain local and explicit.** Configuration has deterministic precedence and must be explainable.
9. **Generated code is disposable.** Override generated behavior through stable extension points, never by editing generated files.
10. **Runtime execution remains separate.** Registry snapshots, impact analysis, migration plans, event-sink contracts, and generated helpers are compiler concerns. Runtime subscriptions, replay engines, hosted synchronization, and materialization workers remain separate product decisions.
11. **Semantic fidelity beats broad but lossy generation.** Constraints, named enums, unions, presence/nullability, and target loss diagnostics are required for trustworthy impact analysis.
12. **The common case should require very little configuration.** Configuration exists to change defaults, not to describe boilerplate that the compiler can derive.

## 3. Current foundation

The existing compiler already provides most of the primitives needed for this design:

- versioned models and projections;
- exact/range/pinned resolution;
- field-level lineage and a compiler-owned property dependency graph;
- model and projection compatibility;
- target compatibility axes for source, wire, storage migration, projection rebuild, and governance review;
- auto projections for database, request, reply, and event shapes;
- API declarations and OpenAPI generation;
- deterministic registry IDs and canonical signatures;
- generated language artifacts;
- an adapter-neutral event-sink/outbox contract;
- generated Rust enum conversions as an early example of mechanical transformation removal;
- a disposable SQLite `registry.db` index.

The main missing product-level composition is:

```text
semantic graph
    -> usage graph
    -> change facts
    -> consequence graph
    -> actions/artifacts
```

Modelable is already a strong model compiler. This design makes it a consequence compiler.

## 4. Registry model

### 4.1 Three distinct concepts

The word "registry" currently risks conflating three responsibilities. This design separates them.

#### Source registry

An external location from which contracts can be discovered and resolved.

Examples:

- another Modelable Git repository;
- an HTTP artifact endpoint;
- Apicurio or another schema/artifact registry;
- a local directory;
- a future Modelable federation service.

A source registry is not required to be available during ordinary compilation.

#### Registry snapshot

The durable, exact, offline dependency state of a Modelable workspace.

It answers:

> Which external contract versions, with which exact canonical content, does this application currently compile against?

This is the authoritative local record of external dependencies.

#### Derived registry index

`registry.db` remains a rebuildable optimization for lookup, inspection, editor queries, lineage, and reporting.

Deleting it must never change dependency resolution. It is reconstructed from local `.mdl` sources plus the durable snapshot.

### 4.2 Snapshot contents

For every external contract reachable from the workspace's actual resolved references, the snapshot records at minimum:

```text
canonical reference
resolved exact version
canonical Modelable signature
content hash
normalized contract representation
source/provenance metadata
transitive contract dependencies
ownership/domain metadata required for diagnostics
lineage/dependency information required for offline impact analysis
```

The snapshot retains enough normalized semantic content to compile, resolve references, perform compatibility analysis, and explain impact without contacting the source.

Generated target artifacts are never the semantic source of truth.

### 4.3 Storage format

The first implementation should use a deterministic, reviewable lock document plus content-addressed snapshot objects.

Suggested layout:

```text
.modelable/
  registry.lock
  registry/
    objects/
      <content-hash>.json
```

`registry.lock` maps logical contract identity and dependency intent to exact object hashes. Object files contain normalized semantic snapshots.

A single deterministic archive is acceptable later if repository size or file count becomes a practical problem, but the semantic model remains equivalent.

`registry.db` stays rebuildable and is not durable dependency state.

### 4.4 Example lock entry

A workspace may author:

```mdl
projection BillingCustomer @ 1
  from customer.Customer @ >=2 <3 as c
{
  customerId <- c.customerId
  name       <- c.legalName
}
```

After resolution, the snapshot records equivalent information:

```yaml
requirements:
  customer.Customer:
    requested: ">=2 <3"
    resolved: 2
    signature: "sha256:..."
    object: "sha256:..."
    source: "company-customer-models"
```

The range remains author intent. Compilation uses the exact snapshotted `Customer@2` object.

### 4.5 Transitive closure

The snapshot includes the semantic transitive closure required by contracts actually used.

If `billing-service` consumes `customer.CustomerReply@2`, and that projection depends on `customer.Customer@2`, both are available offline even if only the projection appears directly in application source.

This is semantic reachability, not mirroring an entire remote registry.

### 4.6 Snapshot as usage evidence

The registry snapshot also becomes machine-readable evidence of what an application consumes externally.

This removes the need for handwritten `consumer {}` declarations in the common case.

Usage is derived from:

- direct external model/projection references;
- API request/response bindings;
- event contracts;
- `ref<>` dependencies;
- generated database/persistence projections where they reference external contracts;
- transitive dependencies needed to explain direct use.

Explicit consumer declarations remain useful only for dependencies that cannot be inferred from semantic references, for example externally managed consumers whose source is not a Modelable workspace.

### 4.7 Registry commands

The intended DX is dependency-manager-like:

```bash
modelable registry resolve
modelable registry status
modelable registry diff
modelable registry update
modelable registry update customer
modelable registry prune
modelable registry verify
```

Semantics:

- `resolve`: create or complete the initial snapshot from declared external requirements;
- `status`: compare author intent, local references, and current snapshot without contacting remotes by default;
- `diff`: show snapshot differences;
- `update`: contact configured sources, calculate candidate resolutions, show consequences, and update only after successful validation;
- `prune`: remove snapshot objects no longer reachable from active requirements;
- `verify`: validate signatures, hashes, transitive completeness, and lock/object consistency entirely offline.

### 4.8 No implicit refresh

These operations never refresh the snapshot automatically:

```text
validate
compile
diff
validate-compat
impact
lineage
graph export
language server/editor operations
```

Historical checkout + snapshot must remain reproducible even when all upstream sources are unavailable or have advanced.

## 5. Usage graph and application boundaries

### 5.1 Purpose

The existing dependency graph explains semantic relationships inside a workspace. This design adds a product-level usage graph answering:

> Which application-visible contract surfaces depend on this model/property, including exact external snapshots?

Nodes include:

```text
workspace/application
model version
projection version
API version
API operation
request/response contract
event contract
database/persistence projection
semantic type
external snapshot object
```

Edges are typed:

```text
consumes
projects_from
request_body
responds_with
emits
persists_as
references
field_depends_on
resolved_from_snapshot
```

### 5.2 Application identity

A workspace needs a stable application/package identity for reporting. Reuse existing workspace/package concepts where possible rather than inventing a parallel naming system.

This identity is build metadata, not a globally coordinated runtime service ID.

### 5.3 Exportable usage manifest

Expose a compact derived manifest for aggregation:

```bash
modelable registry usage --format json
```

The manifest contains exact resolved refs and signatures but does not duplicate full normalized contract bodies.

Organization-level tooling can aggregate these cheaply. The registry snapshot remains authoritative.

## 6. Consequence model

### 6.1 Compatibility is only one consequence

Current compatibility machinery already distinguishes source compatibility, wire compatibility, storage migration, projection rebuild, and governance review. These should become one public consequence model instead of several partially exposed reports.

A change can be source compatible and still require work.

Example:

```text
computed projection expression changed
  source compatibility: compatible
  projection consequence: rebuild required
```

### 6.2 Canonical consequence actions

The first stable action vocabulary:

```text
no_action
regenerate
recompile
consumer_update
storage_migration
data_backfill
projection_rebuild
event_replay
governance_review
breaking
```

These are not a single severity scale. A change may require several actions simultaneously.

### 6.3 Consequence graph

Impact output retains causal paths rather than flattening everything into messages.

Example:

```text
customer.Customer@2.email
  -> customer.CustomerReply@2.email
  -> customer.CustomerApi@2#getCustomer response
  -> billing-service registry snapshot
  -> generated TypeScript client
```

The same graph drives human explanations, CI annotations, IDE visualization, and future organization-level analysis.

### 6.4 Public command

Add:

```bash
modelable impact --from <OLD> --to <NEW>
```

OLD/NEW may be workspaces, commits materialized by caller tooling, or registry snapshots.

Cross-application aggregation:

```bash
modelable impact \
  --from old-customer \
  --to new-customer \
  --consumers ./snapshots
```

Machine-readable JSON is mandatory from the first slice.

### 6.5 Example output

```text
customer.Customer @2 -> @3

billing-service
  CustomerReply@2
    affected: Customer.email -> CustomerReply.email
    source: compatible
    action: regenerate

fraud-service
  CustomerEvent@2
    affected: Customer.status -> event payload
    wire: breaking
    action: consumer_update

reporting-service
  CustomerProjection@4
    affected: computed source expression
    action: projection_rebuild

customer-service
  CustomerDb@2
    affected: status storage representation
    action: storage_migration
```

## 7. Registry update workflow

`registry update` calculates a candidate snapshot before mutating durable state.

1. Resolve newer versions permitted by author requirements.
2. Fetch and verify exact candidate contracts.
3. Construct a staged candidate snapshot.
4. Diff current and candidate semantic graphs.
5. Calculate local consequences.
6. Render exact dependency and generated-artifact changes.
7. Fail if structural incompatibility or configured policy blocks the update.
8. Atomically replace the durable snapshot.

Example:

```text
customer.CustomerReply: 2 -> 3
customer.Customer:      2 -> 3 (transitive)

Consequences:
  generated TypeScript: regenerate
  OpenAPI client surface: unchanged
  local projection BillingCustomer: compatible
  storage: no migration
```

No dependency update should feel like an opaque refresh.

## 8. Generated conversion helpers

### 8.1 Goal

Generated types remove only part of repetitive data code. Modelable already owns field mappings and lineage, so it should also generate safe conversion helpers between canonical models, projections, API types, event payloads, database shapes, and adjacent versions.

Primary cases:

```text
Entity -> Db projection
Request projection -> Entity construction input
Entity -> Reply projection
Entity -> Event projection
Model@N -> Model@N+1
Projection@N -> Projection@N+1
```

### 8.2 Conversion classification

Every potential conversion is classified before generation:

```text
total_reversible
total_irreversible
partial_fallible
requires_hook
impossible
```

Examples:

- direct field rename with compatible types: total;
- `pick(...)`: source -> projection may be total, inverse is impossible;
- computed concatenation: forward total, inverse impossible;
- optional -> required with a declared input default: may be total;
- semantic conversion requiring application lookup: requires hook;
- aggregation/join inverse: impossible.

The compiler must never generate an inverse because fields happen to have similar names.

### 8.3 Target idioms

Use language-native patterns:

```text
Rust        From / TryFrom
C#          static/extension mapper methods
Java        static factories / mapper methods
TypeScript  pure functions
Go          functions returning value/error as needed
Python      functions/classmethods
```

### 8.4 User hooks

Generated helpers call user-owned hooks where compiler knowledge ends.

Example conceptual output:

```text
convert CustomerV2 -> CustomerV3
  copy customerId
  copy email
  resolve loyaltyTier via hook
```

Hooks are stable named extension contracts outside generated files.

### 8.5 Conversion artifacts are consequences

A model change should explicitly report whether existing generated conversions:

```text
remain valid
need regeneration
become fallible
require a new hook
become impossible
```

This belongs in `impact`, not only in code generation logs.

## 9. Configuration and override hierarchy

### 9.1 Problem

Configuration is currently distributed across `.mdl` annotations, auto-projection blocks, generate blocks, CLI flags, package declarations, target-specific wire hints, and a separate compatibility policy file.

The project needs one deterministic precedence model.

### 9.2 Precedence

```text
Modelable built-in defaults
    <
workspace defaults
    <
domain defaults
    <
model/projection overrides
    <
field overrides
    <
CLI invocation overrides
```

Later scopes override earlier scopes only for settings they explicitly define.

### 9.3 Semantic vs build configuration

Keep contract semantics in `.mdl`:

```text
field classifications
ownership
projection semantics
API bindings
wire semantics where contract-significant
```

Keep operational/build defaults in `modelable.toml`:

```toml
[defaults]
auto_projections = ["db", "request", "reply", "event"]
generate_conversions = true

[defaults.request]
exclude_annotations = ["server"]

[defaults.event]
operations = ["created", "updated", "deleted"]

[targets.rust]
conversion_style = "try-from"

[targets.postgres]
uuid_generation = "database"

[compatibility]
wire_compatibility = "breaking"
storage_migration = "migration_required"
governance_review = "review_required"
```

Do not move semantic contract facts into TOML simply because configuration syntax is convenient.

### 9.4 Explainability

Add:

```bash
modelable config explain customer.Customer@3 --target postgres
```

Output includes effective values and provenance:

```text
auto_projections.event.operations = [created, updated, deleted]
  from: workspace defaults

postgres.uuid_generation = database
  from: modelable.toml [targets.postgres]

Customer.createdAt.server_generated = true
  from: field annotation @server
```

An inheritance system without provenance is a DX regression.

### 9.5 Complete policy surface

The existing compatibility-policy work should be finished into a general policy layer rather than describing unsupported `lint:` behavior as shipped.

Policy should be able to enforce compiler facts such as:

```text
compatibility thresholds
governance review requirements
lossy target warnings
deprecated dependency usage
unversioned external references
registry staleness policy when explicitly checked
```

Structural errors remain unsuppressible.

## 10. Auto-projection inheritance

### 10.1 Current friction

Today each entity version needs another explicit `auto projections Entity @ N { ... }` block. This is repetitive when almost every version wants the same database/request/reply/event surfaces.

### 10.2 Default profile

Allow workspace/domain defaults to declare the normal projection set once.

Conceptual syntax:

```mdl
auto projections default {
  db
  request
  reply
  event
}
```

or equivalent configuration if adding grammar is not justified.

Every eligible entity/aggregate version inherits the profile unless overridden.

### 10.3 Per-model override

Exceptional models override only the differences:

```mdl
auto projections Category {
  request exclude [sortOrder]
  reply exclude [@classification("internal")]
  event on [created, deleted]
}
```

Support explicit opt-out.

### 10.4 Lowering rule

Inheritance is resolved before the canonical planning/compatibility stages. The result is ordinary explicit `ProjectionVersion` IR.

Compatibility, lineage, graph export, code generation, and impact analysis never need inheritance-specific logic.

## 11. Defaults, server generation, migration and backfill semantics

### 11.1 One `default` concept is insufficient

Modelable should distinguish:

```text
input default
constructor default
serialization default
database default
migration backfill
server-generated value
```

These have different compatibility consequences.

For example:

```mdl
createdAt: timestamp = now()
```

is ambiguous: client omission behavior, runtime constructor behavior, SQL default generation, and historical backfill are different semantics.

### 11.2 Required semantic distinctions

The language/IR should eventually represent at least:

```text
client_may_omit
server_generates_on_create
storage_default
backfill_existing_rows
wire_default
```

Exact syntax requires a separate language design, but the consequence engine must be designed around these distinct concepts now.

### 11.3 Migration planning

For supported storage targets, Modelable should derive a migration plan from model/projection changes:

```text
DDL change required
safe online additive migration
backfill required
index rebuild required
projection rebuild required
manual migration required
```

The first slice may emit a plan rather than executable migrations.

### 11.4 Backfill safety

Do not auto-generate executable backfills unless the value is deterministic from existing snapshotted data and the compiler can prove the transformation.

Otherwise emit a required hook/manual action.

### 11.5 Event replay

If a materialized projection's semantics change and rebuilding requires event history, report `event_replay` as a consequence. This does not imply Modelable owns a replay runtime.

## 12. API convention profiles

### 12.1 Keep explicit APIs canonical

The explicit `api {}` model is correct. Do not infer routes implicitly through pluralization, framework conventions, or emitter-specific annotations.

### 12.2 Add expandable convenience profiles

Common API boilerplate can still be removed through explicit compiler-expanded profiles.

Conceptual syntax:

```mdl
api CustomerApi @ 1 {
  resource Customer {
    create
    get
    update
    list
  }
}
```

The compiler expands this into ordinary explicit operations using configured conventions.

### 12.3 Inspectability

Users must be able to inspect the expanded contract:

```bash
modelable inspect customer.CustomerApi@1 --expanded
```

### 12.4 Overrides

Override individual operations rather than abandoning the profile:

```text
custom path
custom operation ID
request projection override
response override
query/path parameter override
error contract override
```

### 12.5 Required remaining API fidelity

Prioritize completing:

```text
path parameters
query parameters
standard/default error representation
security metadata once the IR supports it
operation-level compatibility
```

Convenience profiles should not be considered stable until expansion preserves the same compatibility semantics as explicit operations.

## 13. Semantic fidelity priorities: D1–D4

Presence/nullability, value constraints, named enums, and discriminated unions are not merely language completeness work. They directly determine whether Modelable can reason correctly about APIs, events, databases, conversions, and migrations.

Priority:

1. finish presence/nullability across every stable emitter;
2. value constraints;
3. named version-aware enums;
4. discriminated unions.

These enable:

```text
OpenAPI compatibility
event evolution
Avro compatibility
generated validation code
database constraints
safe conversion generation
migration/backfill analysis
accurate target-loss diagnostics
```

A target that cannot preserve one of these semantics must emit an explicit loss/consequence fact.

## 14. Extension and plugin boundary

### 14.1 Goal

Modelable should support most use cases without accumulating every organization's concerns in core grammar and emitters.

Typed namespaced annotations are the right foundation.

Conceptual example:

```mdl
@acme.retention("7y")
@acme.masking(strategy: "tokenize")
customerId: string
```

### 14.2 Plugin capabilities

A trusted compiler plugin may contribute:

```text
annotation schemas
validation rules
compatibility significance
propagation/inheritance rules
target type mappings
conversion hooks
artifact emitters
impact/consequence enrichers
```

### 14.3 Security boundary

An `.mdl` file referencing `@acme.*` must never cause arbitrary plugin installation or execution.

Plugins are explicit trusted build dependencies configured by the workspace/operator.

Unknown annotations are either preserved with diagnostics or rejected according to strict policy. They are never silently ignored.

### 14.4 Determinism

Plugin output participates in canonical compilation only if the plugin declares a stable namespace/version and deterministic behavior. Plugin identity/version must be included in generated build metadata where it affects semantic output.

## 15. Code generation as a secondary product layer

### 15.1 Generate boring application code

Once semantic fidelity and consequence analysis are reliable, Modelable should generate more than DTO declarations:

```text
model types
projection types
conversion helpers
serialization helpers
validation helpers
API client/server contract scaffolding
database row mapping
event envelope adapters
registry/signature constants
```

### 15.2 Do not generate business behavior

The boundary is mechanical transformation and contract plumbing.

Do not generate:

```text
business rules
external lookups
authorization decisions
non-deterministic enrichment
workflow orchestration
```

Those become hooks or application code.

### 15.3 One source of transformation truth

All generated conversion helpers must derive from the same projection/dependency/consequence IR used for lineage and impact. Do not build per-language mapper heuristics.

## 16. Adoption and package DX

### 16.1 Desired new-project experience

A new application should be able to reach a useful state with approximately:

```bash
uvx modelable init
modelable registry resolve
modelable validate
modelable compile
```

The generated initial configuration should contain only deviations from sensible defaults.

### 16.2 Doctor command

Add:

```bash
modelable doctor
```

Check:

```text
configuration validity
snapshot integrity
registry index rebuildability
required external tools for selected targets
plugin availability/version
stale generated artifacts
missing committed lock state
```

This is diagnostic only unless an explicit fix command is used.

### 16.3 Generated artifact manifest

Compilation should emit one machine-readable manifest covering:

```text
inputs and signatures
snapshot identity
compiler version
plugin identities
selected target profiles
generated file hashes
warnings/loss facts
```

This gives CI and downstream tooling one stable artifact boundary.

## 17. Capability and documentation integrity

A tool selling authoritative contracts cannot tolerate its own capability metadata drifting from implementation.

Current classes of drift to eliminate include:

- capability entries that still describe event operation coverage as lost after the IR starts preserving it;
- roadmap claims of compatibility/lint policy while `lint:` is rejected;
- CLI target lists lagging the actual target registry;
- old release-surface wording that conflicts with the current published line.

Rules:

1. `modelable capabilities` is generated from compiler-owned registries, not copied lists.
2. CLI reference target tables should be generated or tested directly against target registries.
3. Every capability status has a proving test reference.
4. Shipped roadmap claims must have executable evidence.
5. Documentation tests fail on stale target lists/status contradictions.

## 18. Revised product architecture

The compiler pipeline becomes:

```text
.mdl + registry snapshot + configuration
                 |
                 v
         semantic graph
                 |
        +--------+---------+
        |                  |
        v                  v
 dependency graph      usage graph
        |                  |
        +--------+---------+
                 v
            change facts
                 |
                 v
         consequence graph
                 |
     +-----------+-----------+-------------+
     |           |           |             |
     v           v           v             v
 compatibility  impact   transformations  migration plan
     |           |           |             |
     +-----------+-----------+-------------+
                 |
                 v
          target artifacts
```

The semantic graph remains the compiler core. The registry snapshot supplies exact external nodes. The usage graph explains application boundaries. The consequence graph becomes the common public model for what a change requires.

## 19. Proposed delivery sequence

### Phase 0 — correctness and naming cleanup

Before adding new behavior:

1. Rename/document `registry.db` as the derived registry index/cache rather than durable dependency state.
2. Fix capability/docs drift around current targets, event operation coverage, policy, and release wording.
3. Ensure every existing target/compatibility fact is machine-readable.

### Phase 1 — durable offline registry snapshot

1. Define snapshot object schema and deterministic canonical serialization.
2. Define `registry.lock`.
3. Resolve direct + transitive external dependencies.
4. Build `registry.db` from local sources + snapshot.
5. Implement `resolve`, `verify`, `status`, `prune`.
6. Make ordinary compile paths provably network-free.
7. Add historical checkout/reproducibility fixtures.

### Phase 2 — usage graph and impact

1. Add workspace/application identity.
2. Derive usage edges from all semantic references.
3. Export compact usage manifests.
4. Generalize current compatibility axes into consequence facts.
5. Implement `modelable impact` JSON + human output.
6. Add multi-snapshot consumer aggregation.
7. Show causal field paths.

### Phase 3 — safe registry update

1. Candidate resolution/staging.
2. Snapshot-to-snapshot diff.
3. Local consequence calculation.
4. Policy enforcement.
5. Atomic update.
6. `registry update <scope>`.

### Phase 4 — conversion helpers

1. Introduce target-neutral conversion IR.
2. Classify total/fallible/hook/impossible transformations.
3. Generate direct projection conversions.
4. Generate adjacent-version conversions.
5. Add stable user hooks.
6. Surface conversion consequences in `impact`.
7. Implement language targets incrementally, starting with concrete consumers.

### Phase 5 — defaults and inheritance

1. Define `modelable.toml` schema.
2. Implement deterministic precedence.
3. Add `config explain`.
4. Add auto-projection inheritance/default profiles.
5. Finish compatibility/lint policy surface.
6. Keep resolved inherited forms out of downstream special cases by lowering to canonical IR.

### Phase 6 — migration semantics

1. Separate server/default/backfill semantics in IR.
2. Emit migration consequence plans.
3. Add deterministic safe backfill detection.
4. Add projection rebuild/event replay facts.
5. Only later consider executable target-specific migration generation.

### Phase 7 — API convenience

1. Complete path/query/error fidelity.
2. Define expandable resource/CRUD profiles.
3. Add expanded inspection.
4. Add per-operation overrides.
5. Prove explicit-vs-expanded compatibility equivalence.

### Phase 8 — semantic fidelity and extensions

1. Complete D1 target coverage.
2. D2 constraints.
3. D3 named enums.
4. D4 discriminated unions.
5. Namespaced typed annotations.
6. Trusted plugin contract.
7. Extend target generation and consequence rules through plugins only where core semantics remain stable.

## 20. Acceptance criteria

This design is complete when the following workflow is possible without bespoke scripts:

```text
1. Application A references version ranges from external Modelable domains.
2. `registry resolve` snapshots the exact required semantic closure.
3. Application A can build, validate, inspect lineage, and generate code offline.
4. The external producer publishes a compatible or incompatible newer version.
5. `registry update` stages the candidate and explains all local consequences before changing lock state.
6. A producer can compare old/new contracts against snapshots from applications B, C, and D and see exactly which application surfaces are affected and through which fields.
7. The consequence report distinguishes regeneration, consumer changes, storage migration, backfill, projection rebuild, event replay, governance review, and hard breakage.
8. Modelable generates safe projection/version conversion helpers and requires explicit hooks where semantics cannot be derived.
9. Common db/request/reply/event projections require no per-version repetition.
10. Configuration overrides can always be explained by source and precedence.
11. Generated API convenience syntax expands to inspectable explicit canonical operations.
12. Stable targets either preserve constraints/nullability/enums/unions or report exact semantic loss.
13. Plugins are explicit trusted dependencies and unknown annotations never execute arbitrary code.
14. Capability documentation cannot silently drift from compiler behavior.
```

## 21. Non-goals

This design does not require:

- a hosted Modelable registry service;
- automatic online polling during compilation;
- runtime event delivery;
- runtime subscription execution;
- a materialization worker;
- automatic event replay execution;
- arbitrary business-logic generation;
- automatic plugin installation;
- a globally centralized service catalog.

Those can integrate with the compiler artifacts later without becoming prerequisites for the core offline workflow.

## 22. Product outcome

The registry snapshot makes an application's external contract state reproducible. The usage graph turns that state into evidence of what the application actually depends on. The consequence graph turns model changes into actionable work. Generated transformations and inherited defaults remove mechanical code without hiding semantics.

The resulting product is not primarily a schema generator:

```text
Modelable = versioned semantic contracts
          + offline dependency snapshots
          + cross-application consequence analysis
          + proof-driven boilerplate elimination
```

That should be the organizing principle for future roadmap decisions.