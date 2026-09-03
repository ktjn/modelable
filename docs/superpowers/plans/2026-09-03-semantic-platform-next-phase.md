# Semantic Platform Next-Phase Implementation Plan

> **Status:** Active plan. Track implementation with the checkboxes in this document and the matching programme section in `ROADMAP.md`.
>
> **Scope:** Post-stabilization work that turns Modelable from a capable IDL/compiler into a semantic platform with package composition, executable extensions, stable graph queries, richer identity/evolution semantics, and reproducible distribution.

## Goal

Build on the shipped stabilization baseline without expanding `.mdl` indiscriminately.

The target product boundary is:

```text
semantic packages
      │
      ▼
semantic graph
  + usage graph
  + change graph
      │
      ▼
consequence graph
      │
      ├──────────────► modelable.query/v1 ─► CLI / LSP / MCP / agents / CI
      │
      └──────────────► modelable.plan/v1 ──► trusted extensions / emitters
```

The durable product remains semantic identity, lineage, usage, change, and consequences. Emitters, package transports, policies, registries, catalogs, and runtime systems stay replaceable edges.

## Constraints

- Preserve existing stable `.mdl` meaning.
- Prefer manifests, overlays, policies, and versioned protocols over grammar additions.
- Keep compilation offline and deterministic by default.
- Do not introduce implicit executable discovery.
- Keep browser/native semantic behavior equivalent.
- Treat generated-code-affecting dependencies and extensions as pinned supply-chain inputs.
- Require cross-host/conformance coverage before a semantic slice is complete.
- Keep runtime materialization, subscriptions, broker abstraction, and database synchronization outside the core.

## Dependency order

```text
A. declaration unification ──────────────┐
                                        ├─► E. composite identity
B. package model ─► C. package locking ─┤
       │                                ├─► F. lifecycle metadata
       └──────────────► D. OCI transport┘

A + plan/v1 ─► G. WASM extension ABI

semantic/usage/change/consequence graphs ─► H. query/v1

A + consequence graph ─► I. declaration-level evolution
compatibility + usage ─► J. compatibility profiles
policy boundary ──────► K. typed semantic facets
```

Slices may run in parallel only when these dependencies are satisfied.

---

## A — Complete the generic declaration model

**Outcome:** Entity, aggregate, event, value, enum, semantic type, and projection share one normalized declaration abstraction for common behavior.

- [ ] Inventory remaining declaration-kind-specific resolution/version/identity code.
- [ ] Define the stable internal `DeclarationId`, `DeclarationVersion`, `DeclarationReference`, and common member/field views.
- [ ] Move generic version selection and reference resolution behind the common declaration boundary.
- [ ] Move common lineage/deprecation/documentation/ownership handling behind the same boundary.
- [ ] Keep kind-specific semantic rules explicit through capabilities rather than large type-conditionals.
- [ ] Remove legacy wrappers once all internal consumers use the common view.
- [ ] Add regression tests proving equivalent resolution behavior across declaration kinds.
- [ ] Add conformance scenarios covering entity, value, enum, semantic type, and projection lookup through one path.

### Acceptance

Adding a capability common to declaration kinds does not require separate identity, version-resolution, lineage, or compatibility implementations.

---

## B — Define first-class semantic packages

**Outcome:** Large model estates can compose immutable, versioned packages instead of relying on workspace/file conventions alone.

Keep package metadata outside `.mdl` initially. Prefer a TOML manifest unless implementation evidence proves another representation superior.

Proposed shape:

```toml
[package]
name = "customer.contracts"
version = "4.2.0"

[dependencies]
"identity.contracts" = ">=2,<3"

[exports]
declarations = ["customer.*"]
```

- [ ] Specify package identity and versioning rules independently of repository/file location.
- [ ] Define public exports and package-private declarations.
- [ ] Define package dependency constraints using the existing semantic version/range machinery where possible.
- [ ] Define package ownership and descriptive metadata without duplicating domain ownership semantics.
- [ ] Define canonical package content hashing.
- [ ] Define how package-local declarations map to existing canonical declaration identities.
- [ ] Define package import/resolution behavior for local workspaces.
- [ ] Reject dependency cycles or make cycle semantics explicit before implementation.
- [ ] Add package-level compatibility reporting based on exported declarations.
- [ ] Add CLI commands for validating and inspecting a package manifest.

### Acceptance

A workspace can consume two versioned semantic packages, resolve their exported declarations without source-path coupling, and produce deterministic package/declaration identities.

---

## C — Extend `modelable.lock/v1` for package resolution

**Outcome:** Package dependency resolution is completely reproducible offline.

- [ ] Add exact resolved package identity/version/content digest to lock state.
- [ ] Record source/provenance separately from semantic identity.
- [ ] Record transitive package dependencies deterministically.
- [ ] Preserve existing declaration, usage, extension, and allocation evidence.
- [ ] Define update semantics: explicit refresh only; normal validate/compile never mutates resolution implicitly.
- [ ] Detect content drift for an immutable package version.
- [ ] Add clean-checkout reconstruction tests.
- [ ] Add lock diff output suitable for code review.

### Acceptance

A clean offline checkout reproduces exactly the same package graph and semantic graph from version-controlled manifests and lock state.

---

## D — Package artifact and OCI transport

**Outcome:** Semantic packages are distributable without building a Modelable-specific registry service.

Use OCI as the preferred first transport. Keep the package format independent of OCI so filesystem/HTTP/other artifact stores remain possible.

Proposed logical artifact:

```text
modelable package
├── manifest.json
├── sources/ or normalized declarations
├── plan.json
├── package-metadata.json
└── signatures/provenance metadata
```

- [ ] Specify `modelable.package/v1` independently of transport.
- [ ] Define deterministic archive/layout rules and digest calculation.
- [ ] Define whether source, normalized semantic data, or both are required.
- [ ] Define producer/compiler version metadata without making it part of semantic identity.
- [ ] Implement local pack/unpack and validation first.
- [ ] Implement OCI push/pull by immutable digest.
- [ ] Require explicit network commands; normal compilation remains offline.
- [ ] Pin pulled package digests into `lock/v1`.
- [ ] Add provenance/signature hooks without requiring one signing backend.
- [ ] Add corruption, digest mismatch, and substitution tests.

### Acceptance

The same package can be packed locally, pushed to OCI, pulled by digest, verified, locked, and consumed with no semantic difference from the original local package.

---

## E — Composite identity keys

**Outcome:** Entities and aggregates can express ordered multi-field identity without changing canonical declaration identity semantics.

Preferred syntax is multiple existing `@key` annotations rather than a second identity declaration mechanism unless parser/diagnostic constraints make that ambiguous.

```mdl
entity OrderLine @ 1 (additive) {
  @key orderId: uuid
  @key lineNumber: int
  quantity: int
}
```

- [ ] Specify ordered key semantics and canonical ordering.
- [ ] Update validation from exactly one key to one-or-more keys for entity/aggregate.
- [ ] Keep declaration identity as `<domain>.<declaration>@<version>`; never embed instance key values in semantic paths.
- [ ] Update `primary`/index validation to match the ordered key set.
- [ ] Define compatibility rules for add/remove/reorder/type-change of key components.
- [ ] Update `plan/v1` additively if key structure is not already representable.
- [ ] Update relevant emitters through capability negotiation; unsupported targets must fail explicitly.
- [ ] Add SQL/JSON Schema/OpenAPI/Protobuf representative conformance.
- [ ] Add browser/native parity fixtures.

### Acceptance

A composite-key declaration produces deterministic semantic plans and target behavior, and changing key composition produces explicit semantic and target compatibility findings.

---

## F — External declaration lifecycle metadata

**Outcome:** Published/deprecated/retired state can evolve without mutating immutable semantic contract contents.

Do not add mutable lifecycle state to declaration bodies initially. Store lifecycle as external package/registry metadata keyed by canonical declaration identity.

Proposed states:

```text
candidate -> published -> deprecated -> retired
```

- [ ] Specify lifecycle states and allowed transitions.
- [ ] Define whether lifecycle is package-scoped, registry-snapshot-scoped, or both.
- [ ] Define replacement links using canonical declaration identities.
- [ ] Keep lifecycle metadata out of semantic signatures unless a concrete invariant requires otherwise.
- [ ] Add policy checks for new references to deprecated/retired declarations.
- [ ] Add query/CLI output for lifecycle state and replacement.
- [ ] Define consequence actions for deprecation and retirement.
- [ ] Add deterministic snapshot/lock representation where lifecycle affects build admission.

### Acceptance

A declaration can be deprecated or retired without editing its immutable `.mdl` version, and consumers receive deterministic diagnostics/consequences according to policy.

---

## G — WASM extension ABI over `modelable.plan/v1`

**Outcome:** Third-party targets/analyzers can execute through a language-neutral, sandboxable extension boundary.

WASM is the first external execution mechanism. Subprocess execution can follow using the same logical request/result protocol.

- [ ] Specify a minimal `modelable.extension-host/v1` request/result protocol.
- [ ] Use `modelable.plan/v1` as the semantic input; extensions must not import parser/internal compiler classes.
- [ ] Define artifact outputs, diagnostics, compatibility findings, and structured failures.
- [ ] Define deterministic configuration input and overlay handoff.
- [ ] Require exact extension id/version/hash/provenance pins.
- [ ] Require explicit trust/enablement; never auto-execute merely discovered binaries/modules.
- [ ] Default to no network and no ambient filesystem.
- [ ] Expose only declared input/output directories or virtual files.
- [ ] Define CPU/memory/output limits and deterministic timeout/failure behavior.
- [ ] Implement a reference extension outside the compiler package.
- [ ] Run the same reference extension in native and browser hosts where WASM support permits.
- [ ] Add malicious/invalid module tests: wrong protocol, excessive output, undeclared access, hash mismatch.
- [ ] Add subprocess host only after the WASM protocol is proven, reusing the same descriptor and result model.

### Acceptance

A separately built WASM target consumes `plan/v1`, runs under explicit least-capability policy, produces artifacts deterministically, and yields the same admitted result in supported native/browser hosts.

---

## H — Stable `modelable.query/v1`

**Outcome:** CLI, LSP, MCP, agents, CI, and future hosts query the semantic platform through one versioned protocol instead of importing internal graph implementations.

Minimum query families:

```text
declaration(id)
referencesTo(id)
lineage(path)
consumersOf(path)
dependencies(id)
dependents(id)
changes(from, to)
consequences(from, to)
```

- [ ] Define query request/response envelopes and canonical identity usage.
- [ ] Define pagination/limits for potentially large graph responses.
- [ ] Define structured graph node/edge representation reusable across query families.
- [ ] Define deterministic ordering for every response.
- [ ] Keep the first version read-only.
- [ ] Implement an in-process service consumed by CLI and LSP.
- [ ] Add JSON/stdio transport suitable for MCP/agent bridges.
- [ ] Add browser transport over the same semantic service.
- [ ] Add protocol schema and golden fixtures.
- [ ] Add compatibility rules for additive query protocol evolution.

### Acceptance

CLI and at least one non-CLI host answer lineage, usage, dependency, and consequence queries through `modelable.query/v1` without directly importing internal graph/resolver classes.

---

## I — Declaration-level evolution and lineage

**Outcome:** Renames, moves, splits, merges, and refactorings remain traceable beyond field-level `evolves` operations.

Do not immediately add broad grammar. Start with an external/versioned migration mapping consumed by semantic analysis.

Required transformations to model:

- declaration rename;
- declaration move between domains/packages;
- field moved into/out of a value object;
- declaration split;
- declaration merge;
- source declaration replaced by projection/value/semantic declaration.

- [ ] Define migration mapping identifiers using canonical declaration/path identities.
- [ ] Define one-to-one, one-to-many, and many-to-one lineage edges.
- [ ] Preserve both immediate and ultimate source lineage.
- [ ] Feed mapping edges into change and consequence graphs.
- [ ] Distinguish semantic rename/move evidence from heuristic structural similarity.
- [ ] Add validation against dangling, cyclic, and ambiguous mappings.
- [ ] Add CLI tooling to inspect and validate mappings.
- [ ] Add cross-package rename/move scenarios after package identity is stable.

### Acceptance

A declaration move or split can be represented explicitly and every affected consumer action can be traced through the consequence graph to the original semantic source.

---

## J — Named compatibility profiles

**Outcome:** Projects can state required compatibility guarantees for a consumer class without baking organization policy into `.mdl` or target evaluators.

Example external configuration:

```toml
[compatibility.public-events]
targets = ["protobuf", "avro"]
require_backward = true
require_forward = true

[compatibility.internal-api]
targets = ["openapi"]
require_backward = true
```

- [ ] Specify profile schema and deterministic inheritance/composition rules, if any.
- [ ] Bind profiles at package/workspace/CI configuration boundaries rather than declaration grammar initially.
- [ ] Evaluate profiles over semantic changes + target compatibility + known usage evidence.
- [ ] Emit one structured profile result with causal links to underlying findings.
- [ ] Feed profile failures into consequence actions.
- [ ] Add CLI selection and CI-friendly exit behavior.
- [ ] Add tests for backward-only, forward-only, full, and target-specific profiles.

### Acceptance

CI can say that a release violates `public-events` compatibility and show the exact semantic/target/consumer findings responsible.

---

## K — Typed semantic facets

**Outcome:** Governance facts can grow without turning every organization-specific concept into permanent grammar or untyped opaque annotations.

Keep the universal built-ins small: identity, ownership, classification, PII, deprecation, and lineage. Add extensible facts through typed, namespaced facet schemas.

Conceptual model:

```text
facet
  namespace
  name
  typed value
  allowed subjects
  inheritance/propagation behavior
  schema version
```

- [ ] Specify a namespaced facet identity format.
- [ ] Specify JSON-schema-like value typing or another deterministic schema mechanism.
- [ ] Define which declaration/path subjects may carry facets.
- [ ] Define projection inheritance/propagation semantics explicitly.
- [ ] Keep unknown facets preserved but not semantically interpreted without their schema.
- [ ] Allow policies to require/interpret facets without compiler grammar changes.
- [ ] Prevent target-specific representation metadata from leaking into facets; that remains overlay territory.
- [ ] Add plan/query representation.
- [ ] Add examples for retention class, jurisdiction, data subject, and confidentiality without making them built-in language annotations.

### Acceptance

An enterprise can add a typed governance fact and policies around it without modifying the parser, while lineage/projection behavior remains deterministic and inspectable.

---

## Cross-cutting work

These are gates for every slice rather than separate product features.

- [ ] Add/update `modelable-showcase` scenarios for every externally visible semantic capability.
- [ ] Maintain browser/native equivalence for semantic inputs and query results.
- [ ] Add protocol JSON Schemas for every new stable protocol.
- [ ] Require deterministic ordering and canonical serialization in golden fixtures.
- [ ] Update capability descriptors whenever a target gains/loses support.
- [ ] Keep network access opt-in and command-scoped.
- [ ] Threat-model extension/package supply-chain paths before enabling executable third-party content.
- [ ] Update architecture docs when an accepted target boundary becomes implemented.
- [ ] Move this plan to `docs/superpowers/plans/archived/` only when all required slices are complete or deliberately superseded.

## Suggested implementation sequence

1. A — complete declaration unification.
2. B + C — package semantics and lock integration.
3. G — WASM extension ABI; it can proceed in parallel once A and `plan/v1` representation needs are understood.
4. H — `query/v1` over the already shipped graph model.
5. E — composite identity keys.
6. F — lifecycle metadata.
7. D — package artifact/OCI distribution after package semantics and lock behavior are stable.
8. I — declaration-level evolution/migration mapping.
9. J — named compatibility profiles.
10. K — typed semantic facets.

Do not interpret this as a strict serial queue. B/C, G, and H can overlap after their prerequisites are stable.

## Explicit non-goals

- No central/distributed Modelable registry service.
- No package transport requirement inside normal compilation.
- No implicit network dependency resolution.
- No implicit PATH/workspace plugin execution.
- No streaming/materialization runtime.
- No broker/database synchronization abstraction.
- No grammar feature solely to configure an emitter/framework.
- No emitter proliferation as a substitute for stabilizing the platform boundary.

## Programme completion criteria

The programme is complete when:

- [ ] all declaration kinds use the common semantic declaration boundary;
- [ ] semantic packages compose through explicit exports/dependencies and deterministic lock state;
- [ ] packages can be distributed by immutable digest without a Modelable-specific service;
- [ ] a third-party WASM extension executes through a pinned, least-capability `plan/v1` boundary;
- [ ] semantic/usage/change/consequence data is accessible through `modelable.query/v1`;
- [ ] composite identity is represented consistently across semantic analysis and admitted targets;
- [ ] lifecycle metadata can change independently of immutable declaration content;
- [ ] declaration-level refactors preserve explicit lineage and consequence paths;
- [ ] compatibility requirements can be expressed as named external profiles;
- [ ] new typed governance facts can be added without parser changes;
- [ ] browser/native and external-showcase conformance cover the new platform surfaces.
