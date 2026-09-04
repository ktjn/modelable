# Roadmap

Modelable's stabilization baseline is complete.

The latest published release is **1.13.2**.

The product already has broad language, compatibility, lineage, code generation, import, browser, and tooling capability. The next priority is to grow from a capable IDL/compiler into a semantic platform without destabilizing the core language or reintroducing declaration/emitter duplication.

The architecture source of truth is [docs/architecture.md](docs/architecture.md). The previous shipped-state roadmap is retained as [docs/roadmap-archive-2026-08.md](docs/roadmap-archive-2026-08.md).

## Current execution status

### Stabilization baseline

- [x] Phase 1 — canonical identity/path grammar baseline.
- [ ] Phase 2 — declaration/projection unification complete end-to-end. The baseline is shipped, but legacy declaration-specific wrappers/paths remain.
- [x] Phase 3 — `modelable.plan/v0` migration boundary.
- [x] Phase 4 — deterministic version-aware target overlays.
- [ ] Phase 5 — external extension execution. Descriptors, capabilities, provenance pins, trust policy, and a native third-party WASM host are shipped; virtual capability handoff, browser execution, and subprocess execution remain.
- [x] Phase 6 — stable `modelable.plan/v1` boundary.
- [x] Phase 7 — usage graph baseline.
- [x] Phase 8 — deterministic `modelable.lock/v1` baseline.
- [x] Phase 9 — structured consequence graph baseline.
- [x] Phase 10 — layered semantic/target compatibility baseline.
- [x] Phase 11 — external policy evaluator boundary.
- [x] Phase 12 — browser/native/showcase conformance as a continuous release gate.

Completed programmes retained as implementation history:

- [Offline registry and consequence delivery](docs/superpowers/plans/archived/2026-08-21-offline-registry-dx-delivery.md)
- [Model evolution slices](docs/superpowers/plans/archived/2026-08-22-model-evolution-slices-roadmap.md)

The active post-stabilization implementation plan is:

- [Semantic platform next phase](docs/superpowers/plans/2026-09-03-semantic-platform-next-phase.md)

## Product boundary

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

The semantic graph and consequence graph are the durable product. Emitters, policies, adapters, package transports, registries, catalogs, framework integrations, and runtime consumers remain replaceable edges.

## Operating rules

1. **Correctness first.** Confirmed false compatibility results are release blockers.
2. **No silent loss.** Parsed content that is silently ignored or discarded without an explicit diagnostic is a release blocker for the affected construct.
3. **Language stability.** Old stable syntax never changes meaning silently. New semantics require new syntax, an explicitly versioned protocol change, or a compatibility-preserving migration path.
4. **Grammar freeze by default.** New broad grammar features are paused unless existing semantics cannot represent the requirement correctly.
5. **Target behavior stays at the edge.** New target/framework behavior should prefer overlays or extensions over core annotations.
6. **One normalized compiler boundary.** New emitters and analyzers consume normalized compiler output rather than duplicate semantic resolution.
7. **Browser/native equivalence.** Browser and native compilation remain semantically equivalent.
8. **Conformance before completion.** Significant semantic changes require realistic external conformance coverage in `modelable-showcase` or an equivalent cross-surface fixture.
9. **Runtime stays external.** Runtime execution features remain outside the core roadmap.
10. **Security is part of extensibility.** Executable extensions, dependency refresh, and generated-code-affecting configuration require explicit provenance/trust rules.
11. **Offline by default.** Validate/compile/diff/query do not implicitly contact package services, registries, or extension sources.
12. **Package and extension identity is immutable.** Resolution may use ranges, but lock state records exact content digests and provenance.

## Post-stabilization semantic platform programme

This programme is dependency-ordered, not a strict serial queue. Detailed tasks and acceptance criteria live in [the active implementation plan](docs/superpowers/plans/2026-09-03-semantic-platform-next-phase.md).

### A — Complete generic declaration unification

**Priority:** P0

- [x] Define one common internal declaration identity/version/reference surface for entity, aggregate, event, value, enum, semantic type, and projection.
- [ ] Move shared version resolution, lineage, ownership, documentation, and deprecation behavior behind it.
- [ ] Replace remaining declaration-kind-specific resolution paths where semantics are equivalent.
- [ ] Remove legacy wrappers after all consumers migrate.
- [x] Add cross-declaration conformance fixtures.

**Done when:** adding a capability common to declaration kinds does not recreate resolution, identity, lineage, or compatibility infrastructure.

### B — First-class semantic packages

**Priority:** P0

Keep package metadata outside `.mdl` initially, preferably in a deterministic TOML manifest.

- [x] Define immutable package identity/version/content hashing.
- [x] Define public exports and package-private declarations.
- [x] Define dependency constraints and package graph rules.
- [x] Define deterministic local package resolution.
- [x] Define package-level compatibility over exported declarations.
- [x] Add package validation/inspection CLI surfaces.

**Done when:** multiple independently versioned semantic packages compose without coupling canonical identities to file/repository locations.

### C — Package-aware `modelable.lock/v1`

**Priority:** P0

- [x] Record exact resolved package versions and content digests.
- [x] Record package provenance and deterministic transitive dependencies.
- [x] Make dependency refresh explicit; normal compilation never silently changes locked packages.
- [x] Detect immutable-version content drift.
- [x] Add clean-offline-checkout reproduction tests.

**Done when:** manifests + lock state reproduce the exact package and semantic graphs offline.

### D — `modelable.package/v1` and OCI transport

**Priority:** P1

OCI is the preferred first transport, but the logical package artifact must remain transport-independent.

- [x] Specify deterministic `modelable.package/v1` contents and digest rules.
- [x] Implement local pack/unpack/verify first.
- [ ] Add OCI push/pull by immutable digest.
- [ ] Pin pulled digests into `lock/v1`.
- [x] Keep all network operations explicit commands.
- [ ] Add provenance/signature hooks without coupling to one signing system.

**Done when:** a locally packed semantic package can round-trip through OCI with identical verified semantic content.

### E — Composite identity keys

**Priority:** P1

- [x] Allow one-or-more ordered `@key` fields on entities/aggregates.
- [x] Keep canonical declaration identity independent of instance-key values.
- [x] Align `primary`/index semantics with the ordered key set.
- [x] Define semantic compatibility for add/remove/reorder/type-change of key components.
- [x] Admit support per target through capabilities; unsupported targets fail explicitly.
- [x] Add representative SQL/JSON Schema/OpenAPI/Protobuf and browser/native conformance.

**Done when:** composite identity behaves deterministically across semantic analysis and admitted targets.

### F — External declaration lifecycle metadata

**Priority:** P1

Declaration bodies remain immutable. Lifecycle should initially live in external package/registry metadata keyed by canonical identity.

Proposed lifecycle:

```text
candidate -> published -> deprecated -> retired
```

- [x] Specify lifecycle states and transition rules.
- [x] Define canonical replacement links.
- [x] Define lifecycle state as explicit registry-snapshot metadata when it affects build admission.
- [x] Add policy checks for new references to deprecated/retired contracts.
- [x] Expose lifecycle/replacement through CLI and query surfaces.
- [x] Feed lifecycle transitions into consequences where appropriate.

**Done when:** a declaration can be deprecated/retired without editing its immutable semantic version.

### G — WASM extension ABI

**Priority:** P0

WASM is the first third-party execution mechanism. Subprocess execution may follow using the same logical protocol.

- [x] Specify `modelable.extension-host/v1` request/result protocol.
- [x] Use `modelable.plan/v1` as semantic input; no parser/internal compiler imports.
- [x] Support artifact outputs, diagnostics, compatibility findings, and structured failures.
- [x] Require exact extension id/version/hash/provenance pins.
- [x] Require explicit trust/enablement; never execute extensions merely because they are discoverable.
- [x] Default to no network and no ambient filesystem.
- [x] Pass only explicitly declared virtual UTF-8 input files and returned artifacts.
- [x] Add CPU/memory/output limits and deterministic failure behavior.
- [x] Build a reference extension outside the compiler package.
- [ ] Prove native/browser execution where WASM host support permits.
- [x] Add hostile/invalid module conformance tests.

**Done when:** a separately built WASM extension consumes `plan/v1` and produces deterministic admitted results under least-capability policy.

### H — Stable `modelable.query/v1`

**Priority:** P0

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

- [x] Specify versioned request/response envelopes.
- [x] Define deterministic graph node/edge and ordering rules.
- [x] Define limits/pagination for large graph responses.
- [x] Keep v1 read-only.
- [ ] Migrate CLI/LSP graph queries to one in-process service.
- [x] Add JSON/stdio transport suitable for MCP/agent bridges.
- [x] Add browser support over the same semantic service.
- [x] Check in protocol schema and golden fixtures.

**Done when:** at least CLI plus one non-CLI host query semantic/usage/change/consequence data without importing internal resolver/graph implementations.

### I — Declaration-level evolution and lineage

**Priority:** P1

Start with an external/versioned migration mapping rather than broad new grammar.

- [x] Represent declaration rename and domain/package move.
- [x] Represent field moves into/out of value objects.
- [x] Represent one-to-many split and many-to-one merge lineage.
- [x] Preserve immediate and ultimate source lineage.
- [x] Feed mappings into change/consequence graphs.
- [x] Reject dangling, cyclic, and ambiguous mappings.
- [x] Add cross-package move scenarios after package identity stabilizes.

**Done when:** declaration refactors preserve explicit causal lineage rather than appearing only as remove/add pairs.

### J — Named compatibility profiles

**Priority:** P1

Profiles remain external configuration rather than `.mdl` semantics.

- [x] Specify profile schema for backward/forward/full and target-specific requirements.
- [x] Bind profiles at the explicit CLI/policy boundary.
- [x] Evaluate profiles over semantic changes, target compatibility, and known usage evidence.
- [x] Emit structured profile findings with causal links to lower-level findings.
- [x] Feed profile failures into consequences.
- [x] Add CI-friendly CLI selection and exit behavior.

**Done when:** CI can report that a named compatibility contract failed and explain the exact semantic/target/consumer causes.

### K — Typed semantic facets

**Priority:** P2

Keep universal built-ins small: identity, ownership, classification, PII, deprecation, and lineage. New enterprise/governance facts use typed namespaced facets.

- [x] Specify namespaced facet identity and schema versioning.
- [x] Define typed values and allowed semantic subjects.
- [x] Define projection inheritance/propagation rules.
- [x] Preserve unknown facets without interpreting them when their schema is unavailable.
- [x] Expose facets to policy evaluators, plans, and query results.
- [x] Keep target-specific representation metadata in overlays, not facets.
- [x] Add examples for retention class, jurisdiction, data subject, and confidentiality.

**Done when:** a new typed governance fact and policies around it can be introduced without parser changes.

## Programme-level progress

- [ ] A — generic declaration model complete.
- [x] B — semantic package model complete.
- [x] C — package-aware lock state complete.
- [ ] D — package artifact + OCI transport complete.
- [x] E — composite identities complete.
- [x] F — lifecycle metadata complete.
- [ ] G — WASM extension ABI complete.
- [ ] H — `modelable.query/v1` complete.
- [ ] I — declaration-level evolution mappings complete.
- [ ] J — compatibility profiles complete.
- [ ] K — typed semantic facets complete.

Recommended implementation order:

1. A — declaration unification.
2. B + C — package model and lock integration.
3. G — WASM extension ABI, in parallel once A/`plan/v1` representation needs are understood.
4. H — query protocol over the shipped graph model.
5. E — composite identity.
6. F — lifecycle metadata.
7. D — OCI/package distribution after B/C semantics stabilize.
8. I — declaration-level refactor lineage.
9. J — compatibility profiles.
10. K — typed semantic facets.

## Continuous gates

These apply to every active slice.

- [ ] Browser/native semantic equivalence remains green.
- [ ] `modelable-showcase` or equivalent external conformance covers each new semantic surface before completion.
- [ ] New stable protocols have checked-in schemas and deterministic golden fixtures.
- [ ] Target capability descriptors are updated when support changes.
- [ ] Normal compile/validate/query paths remain network-independent.
- [ ] Executable extensions/package refresh remain explicit and provenance-pinned.
- [ ] Repository-health, typing, coverage, and release checks remain green.

## Current/deferred syntax disposition

Runtime-adjacent syntax already exists and cannot silently disappear:

- `subscription` remains parsed but explicitly `DEFERRED`; no runtime execution is added.
- projection `materialisation` remains parsed but explicitly `DEFERRED`.
- workspace `registry {}` / `peers` forms with no semantic effect remain explicitly `DEFERRED`.
- `consumer {}` remains deferred/non-authoritative; usage evidence is preferred.
- `binding {}` retains its implemented compile-time subset; unsupported opaque content remains explicitly `DEFERRED`.

No parsed construct may be silently discarded. Future removal/replacement requires an explicit language migration under Operating rule 3.

## Shipped product record retained during stabilization

The old roadmap mixed shipped history with future work. That history remains in [docs/roadmap-archive-2026-08.md](docs/roadmap-archive-2026-08.md) rather than being deleted.

### Conversational Compilation Management

Conversational Compilation Management is shipped through CLI chat and the native VS Code participant. The completed design remains archived at:

`docs/superpowers/specs/archived/2026-07-19-conversational-compilation-management-design.md`

This remains a supported shipped surface while semantic-platform work changes compiler internals beneath it.

## Legacy slice compatibility index

Historical comments, tests, documentation, and deep links still use these names. Preserve the headings even when their work maps to newer programme slices.

### Slice A1 — correct optionality compatibility under the current model

Shipped correctness work. Maps to continuous correctness gates and layered compatibility.

### Slice A2 — create one property-dependency graph

Shipped dependency-graph work. Foundational to usage/consequence/query work.

### Slice A3 — validate all expression positions

Shipped correctness work. Continues under Operating rules 1–2.

### Slice A4 — fix semantic-type resolution ambiguity

Shipped resolution work. Foundational to programme A.

### Slice B1 — add a canonical capability manifest

Shipped capability foundation. Programme G completes executable extension hosting.

### Slice B2 — reconcile current documentation claims

Shipped documentation/capability consistency work.

### Slice B3 — eliminate silently ignored syntax

Shipped `DEFERRED` diagnostic behavior. Preserved by Operating rule 2.

### Slice C1 — projection-to-projection compatibility

Shipped projection compatibility work.

### Slice C2 — extend existing version resolution to `ref<>` types

Shipped resolution work. Programme A continues declaration-wide unification.

### Slice C3 — generalize existing target compatibility

Shipped target-compatibility abstraction. Programme J adds named compatibility contracts above it.

### Slice C4 — configurable compatibility and lint policy

Shipped policy foundation. Programme J adds named compatibility profiles; programme K adds typed extensible facts.

### Slice D1 — separate presence and nullability

Historical language-evolution slice. Any remaining work is subject to Operating rules 3–4.

### Slice D2 — value and semantic type evolution

Historical language-evolution work; programme A finishes common declaration infrastructure.

### Slice D3 — enum declaration convergence

Historical enum work; programme A finishes common declaration infrastructure.

### Slice D4 — discriminated unions

Shipped/future language capability; additional grammar only proceeds from concrete semantic need.

### Slice D5 — resolve composite-key support

Composite keys are accepted by core semantic validation with ordered primary
index checking; target capability negotiation and emitter conformance remain in
Programme E.

### Slice D6 — model lifecycle status

Lifecycle status remains absent from immutable declaration grammar/IR. Programme F intentionally models lifecycle externally first.

### Slice F1 — nominal semantic types beyond Rust

Target coverage remains demand-driven and capability-negotiated.

### Slice F2 — OpenAPI emission

OpenAPI emission is shipped. This heading remains for existing deep links.

### Slice G1 — critical compatibility coverage

Continuous coverage ratchet.

### Slice G2 — strict typing baseline reduction

Continuous typing ratchet.

### Slice G3 — conformance fixtures

Shipped/continuous conformance foundation; remains a release gate.

## Deferred product areas

The following remain outside the core roadmap unless the product thesis changes:

- streaming execution engine;
- subscription runtime;
- materialization runtime;
- broker abstraction;
- database synchronization service;
- retry/dead-letter execution;
- distributed Modelable registry service.

Modelable may generate contracts, plans, mappings, migrations, validation packages, or consequence actions for these systems.

## Future-use design tests

| Use | Expected mechanism |
|---|---|
| GraphQL | emitter + compatibility evaluator |
| AsyncAPI | emitter |
| additional wire/schema formats | extension/emitter |
| Iceberg/Delta | extension/emitter |
| ORM/framework bindings | overlay + extension |
| Unity | C# extension + overlay |
| SDK generation | extension/emitter |
| industry standards | extension package |
| enterprise governance | typed facet + policy evaluator |
| catalog integration | adapter |
| schema registry integration | adapter |
| API migration tooling | consequence graph + action generator |
| AI-assisted refactoring | `modelable.query/v1` |
| code migrations | declaration evolution mapping + action generator |
| cross-repo blast radius | packages + lock snapshots + usage graph |
| runtime validation | generated package |
| MCP/agent integration | `modelable.query/v1` transport |

## Explicit non-goals

Do not spend semantic-platform capacity on:

- adding emitters solely for breadth;
- adding grammar syntax for target configuration;
- making SQLite registry state authoritative;
- building a remote/distributed Modelable registry service;
- making package resolution implicitly networked;
- executing plugins merely because they are present on PATH or in a workspace;
- implementing runtime materialization/subscriptions;
- creating duplicate semantic implementations for browser or integrations.

## Contribution decision rule

Before extending the language:

```text
Can existing semantic constructs represent this correctly?
  │
  ├─ yes → extension / overlay / package metadata / migration mapping / policy / facet
  │
  └─ no  → propose a semantic-model change
```

A semantic-model proposal must document why projections, semantic types, overlays, extension capabilities, package metadata, migration mappings, facets, and policy/action mechanisms are insufficient.

## Stabilization completion criteria

The shipped stabilization baseline remains complete when these invariants stay true:

- canonical declaration identity and nested semantic path grammar are defined and used consistently;
- declarations/projections share common baseline resolution/version/lineage infrastructure;
- `modelable.plan/v1` remains stable and parser-independent;
- external target configuration uses deterministic version-aware overlays;
- extension capability negotiation and provenance/trust rules are enforced;
- usage evidence feeds deterministic `modelable.lock/v1`;
- compatibility-critical target allocations are lock state, not optional config;
- consequences form an explainable graph;
- semantic and target compatibility remain separated;
- browser/native semantic conformance is enforced;
- showcase provides realistic cross-target conformance;
- significant integrations can be added without changing `.mdl`.

The post-stabilization programme extends this baseline rather than replacing it.
